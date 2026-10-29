Shaders for the RDP GPU view (`widgets/rdp_gpu_view.py`). The app loads
the precompiled `.qsb` files, so after editing a `.vert`/`.frag` rebuild
them with the `pyside6-qsb` tool that ships with PySide6:

    pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o rdp_frame.vert.qsb rdp_frame.vert
    pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o rdp_frame.frag.qsb rdp_frame.frag
