"""GPU-drawn view for RdpWidget (issue #126): shows the remote desktop as a
texture through Qt's RHI -- Metal on macOS, Direct3D 11 on Windows,
OpenGL on Linux -- so scaling and getting pixels on screen happen on the
GPU instead of in QPainter's CPU raster engine.

RdpWidget still owns everything else (input, letterboxing math, the
status label); this child only draws. It covers RdpWidget completely and
is transparent to mouse events, so the parent keeps receiving them. If
the GPU path can't be used -- no RHI backend, or only a software one
like llvmpipe, which would be slower than QPainter -- `unavailable` fires
and RdpWidget falls back to painting the frame itself.
"""

import logging
import os
import re
import sys
import struct
from collections.abc import Callable
from importlib.resources import files

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QOffscreenSurface,
    QOpenGLContext,
    QRhi,
    QRhiBuffer,
    QRhiCommandBuffer,
    QRhiDepthStencilClearValue,
    QRhiGraphicsPipeline,
    QRhiSampler,
    QRhiShaderResourceBinding,
    QRhiShaderStage,
    QRhiTexture,
    QRhiTextureSubresourceUploadDescription,
    QRhiTextureUploadDescription,
    QRhiTextureUploadEntry,
    QRhiVertexInputAttribute,
    QRhiVertexInputBinding,
    QRhiVertexInputLayout,
    QRhiViewport,
    QShader,
)
from PySide6.QtWidgets import QRhiWidget, QWidget

logger = logging.getLogger(__name__)

# Set to 1 to use the GPU view even on a software renderer (llvmpipe and
# the like) -- for testing the GPU path on machines without a real GPU.
FORCE_ENV = "IT_TOOLBOX_RDP_FORCE_GPU"

# Software rasterizers, by the device name their driver reports. QRhi only
# marks some of them as CpuDevice (OpenGL on Mesa's llvmpipe, for one, is
# reported as a normal device), and drawing through one costs more CPU than
# QPainter does.
_SOFTWARE_RENDERERS = re.compile(r"llvmpipe|softpipe|lavapipe|swiftshader|software|basic render", re.IGNORECASE)

# Four vertices (triangle strip), each x, y (clip space) then u, v.
_VERTEX_FORMAT = "16f"
_VERTEX_BYTES = struct.calcsize(_VERTEX_FORMAT)


# Set once any view finds only a software renderer, so later sessions in
# this run don't create one at all: the first QRhiWidget in a window
# switches that whole window to RHI compositing for good, which through a
# software renderer costs more than the QPainter path saves. None = unknown.
_gpu_usable: bool | None = None


def gpu_rendering_usable() -> bool:
    """Whether creating an RdpGpuView is worth it on this machine -- a
    cheap check made before the first one, so a machine without a real GPU
    never pays for RHI compositing at all.

    Only Linux can be probed up front (QRhiWidget renders through OpenGL
    there, and Qt's own OpenGL classes report the renderer); on Windows
    (Direct3D) and macOS (Metal) the view checks for itself when it starts
    and falls back then.
    """
    global _gpu_usable
    if os.environ.get(FORCE_ENV) == "1":
        return True
    if _gpu_usable is None:
        _gpu_usable = _probe_opengl() if sys.platform.startswith("linux") else True
    return _gpu_usable


def _probe_opengl() -> bool:
    surface = QOffscreenSurface()
    surface.create()
    context = QOpenGLContext()
    if not context.create() or not context.makeCurrent(surface):
        logger.info("RDP: no usable OpenGL, drawing sessions with QPainter")
        return False
    try:
        renderer = context.functions().glGetString(_GL_RENDERER) or ""
    finally:
        context.doneCurrent()
        surface.destroy()
    if _SOFTWARE_RENDERERS.search(renderer):
        logger.info("RDP: OpenGL is software-only (%s), drawing sessions with QPainter", renderer)
        return False
    return True


_GL_RENDERER = 0x1F01


def _load_shader(name: str) -> QShader:
    # Precompiled with pyside6-qsb from the .vert/.frag next to them (see
    # resources/shaders/README.md), with GLSL, HLSL and MSL variants so one
    # file serves every backend.
    data = files("it_toolbox.resources").joinpath("shaders", name).read_bytes()
    return QShader.fromSerialized(data)


class RdpGpuView(QRhiWidget):
    unavailable = Signal(str)  # reason

    def __init__(self, target_rect: Callable[[], QRect], on_rendered: Callable[[], None], parent: QWidget):
        super().__init__(parent)
        # The rect, in widget coordinates, the image is drawn into --
        # RdpWidget's own letterboxing, so drawing and input mapping can
        # never disagree.
        self._target_rect = target_rect
        # Called once a new frame has actually been drawn, like RdpWidget's
        # paintEvent does in the CPU path (it lets the worker send the next).
        self._on_rendered = on_rendered
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._image: QImage | None = None
        self._image_dirty = False
        self._rhi: QRhi | None = None
        self._texture: QRhiTexture | None = None
        self._texture_format = None
        self._sampler: QRhiSampler | None = None
        self._vbuf: QRhiBuffer | None = None
        self._srb = None
        self._pipeline: QRhiGraphicsPipeline | None = None
        self._given_up = False
        self.renderFailed.connect(lambda: self._give_up("the GPU renderer failed to start"))

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._image_dirty = True
        self.update()

    def _give_up(self, reason: str, software: bool = False) -> None:
        global _gpu_usable
        if software:
            _gpu_usable = False
        if not self._given_up:
            self._given_up = True
            logger.info("RDP: not drawing on the GPU (%s), falling back to QPainter", reason)
            self.unavailable.emit(reason)

    # --- QRhiWidget overrides ------------------------------------------

    # An exception escaping initialize()/render() is swallowed by the
    # binding and leaves the view showing nothing forever -- so both turn
    # any error into falling back to the CPU path instead.

    def initialize(self, cb: QRhiCommandBuffer) -> None:  # noqa: N802 - Qt override
        try:
            self._initialize()
        except Exception:
            logger.exception("RDP GPU view failed to initialize")
            self._give_up("the GPU renderer failed to start")

    def render(self, cb: QRhiCommandBuffer) -> None:  # noqa: N802 - Qt override
        try:
            self._render(cb)
        except Exception:
            logger.exception("RDP GPU view failed to render")
            self._give_up("the GPU renderer failed")

    def _initialize(self) -> None:
        rhi = self.rhi()
        if rhi is None:
            self._give_up("no GPU renderer")
            return
        if rhi is not self._rhi:
            # A new QRhi (first show, or the widget moved to another
            # window) invalidates everything created from the old one.
            self._rhi = rhi
            self._texture = self._sampler = self._vbuf = self._srb = self._pipeline = None
            info = rhi.driverInfo()
            device = info.deviceName.data().decode(errors="replace")
            logger.info("RDP GPU view: %s on %s", rhi.backendName(), device)
            software = info.deviceType == info.DeviceType.CpuDevice or _SOFTWARE_RENDERERS.search(device)
            if software and os.environ.get(FORCE_ENV) != "1":
                self._give_up(f"only a software renderer is available ({device})", software=True)
                return
        if self._pipeline is None:
            self._create_pipeline(rhi)

    def _create_pipeline(self, rhi: QRhi) -> None:
        # BGRA8 matches the frame's bytes (QImage.Format_RGB32 on a
        # little-endian host) so uploads need no per-pixel conversion; RGBA8
        # (with a conversion per frame) only where a backend lacks it.
        if rhi.isTextureFormatSupported(QRhiTexture.Format.BGRA8):
            self._texture_format = QRhiTexture.Format.BGRA8
        else:
            self._texture_format = QRhiTexture.Format.RGBA8
        self._sampler = rhi.newSampler(
            QRhiSampler.Filter.Linear,
            QRhiSampler.Filter.Linear,
            QRhiSampler.Filter.None_,
            QRhiSampler.AddressMode.ClampToEdge,
            QRhiSampler.AddressMode.ClampToEdge,
        )
        self._sampler.create()
        self._vbuf = rhi.newBuffer(QRhiBuffer.Type.Dynamic, QRhiBuffer.UsageFlag.VertexBuffer, _VERTEX_BYTES)
        self._vbuf.create()
        # A 1x1 placeholder until the first frame, so the bindings and the
        # pipeline can be built up front.
        self._create_texture(rhi, 1, 1)

        self._pipeline = rhi.newGraphicsPipeline()
        self._pipeline.setTopology(QRhiGraphicsPipeline.Topology.TriangleStrip)
        self._pipeline.setShaderStages([
            QRhiShaderStage(QRhiShaderStage.Type.Vertex, _load_shader("rdp_frame.vert.qsb")),
            QRhiShaderStage(QRhiShaderStage.Type.Fragment, _load_shader("rdp_frame.frag.qsb")),
        ])
        layout = QRhiVertexInputLayout()
        layout.setBindings([QRhiVertexInputBinding(4 * 4)])
        layout.setAttributes([
            QRhiVertexInputAttribute(0, 0, QRhiVertexInputAttribute.Format.Float2, 0),
            QRhiVertexInputAttribute(0, 1, QRhiVertexInputAttribute.Format.Float2, 2 * 4),
        ])
        self._pipeline.setVertexInputLayout(layout)
        self._pipeline.setSampleCount(self.renderTarget().sampleCount())
        self._pipeline.setShaderResourceBindings(self._srb)
        self._pipeline.setRenderPassDescriptor(self.renderTarget().renderPassDescriptor())
        if not self._pipeline.create():
            self._pipeline = None
            self._give_up("couldn't create the GPU pipeline")

    def _create_texture(self, rhi: QRhi, width: int, height: int) -> None:
        self._texture = rhi.newTexture(self._texture_format, QSize(width, height))
        self._texture.create()
        self._srb = rhi.newShaderResourceBindings()
        self._srb.setBindings([
            QRhiShaderResourceBinding.sampledTexture(
                0, QRhiShaderResourceBinding.StageFlag.FragmentStage, self._texture, self._sampler
            )
        ])
        self._srb.create()
        if self._pipeline is not None:
            # Same layout as before, so the pipeline stays valid with the
            # rebuilt bindings (QRhi's "layout compatible" rule).
            self._pipeline.setShaderResourceBindings(self._srb)

    def _render(self, cb: QRhiCommandBuffer) -> None:
        if self._given_up or self._pipeline is None:
            return
        rhi = self._rhi
        updates = rhi.nextResourceUpdateBatch()
        rendered_new_frame = False
        if self._image is not None and self._image_dirty:
            image = self._image
            if self._texture.pixelSize() != image.size():
                self._create_texture(rhi, image.width(), image.height())
            if self._texture_format != QRhiTexture.Format.BGRA8:
                image = image.convertToFormat(QImage.Format.Format_RGBA8888)
            updates.uploadTexture(
                self._texture,
                QRhiTextureUploadDescription(QRhiTextureUploadEntry(0, 0, QRhiTextureSubresourceUploadDescription(image))),
            )
            self._image_dirty = False
            rendered_new_frame = True

        output = self.renderTarget().pixelSize()
        draw = self._image is not None
        if draw:
            updates.updateDynamicBuffer(self._vbuf, 0, _VERTEX_BYTES, self._vertices(rhi))
        cb.beginPass(self.renderTarget(), QColor(Qt.GlobalColor.black), QRhiDepthStencilClearValue(1.0, 0), updates)
        if draw:
            cb.setGraphicsPipeline(self._pipeline)
            cb.setViewport(QRhiViewport(0, 0, output.width(), output.height()))
            cb.setShaderResources()
            cb.setVertexInput(0, [(self._vbuf, 0)])
            cb.draw(4)
        cb.endPass()
        if rendered_new_frame:
            self._on_rendered()

    def releaseResources(self) -> None:  # noqa: N802 - Qt override
        self._texture = self._sampler = self._vbuf = self._srb = self._pipeline = None
        self._rhi = None

    def _vertices(self, rhi: QRhi) -> bytes:
        # The target rect in widget (logical) coordinates maps to clip space
        # by the widget's own logical size -- device pixel ratio cancels out.
        rect = self._target_rect()
        w, h = max(self.width(), 1), max(self.height(), 1)
        left = 2 * rect.x() / w - 1
        right = 2 * (rect.x() + rect.width()) / w - 1
        top = 1 - 2 * rect.y() / h
        bottom = 1 - 2 * (rect.y() + rect.height()) / h
        if not rhi.isYUpInNDC():  # Vulkan: clip-space Y points down
            top, bottom = -top, -bottom
        # Texture coordinates have their origin at the image's top-left on
        # every backend for an uploaded QImage.
        return struct.pack(
            _VERTEX_FORMAT,
            left, top, 0.0, 0.0,
            left, bottom, 0.0, 1.0,
            right, top, 1.0, 0.0,
            right, bottom, 1.0, 1.0,
        )
