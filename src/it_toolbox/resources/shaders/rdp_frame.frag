#version 440
// Samples the remote desktop texture; the sampler's linear filtering is
// what does the scaling the CPU path did with SmoothPixmapTransform.
layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 fragColor;
layout(binding = 0) uniform sampler2D frame;

void main()
{
    fragColor = vec4(texture(frame, v_uv).rgb, 1.0);
}
