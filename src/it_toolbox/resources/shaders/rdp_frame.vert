#version 440
// Full-quad vertex shader for RdpWidget's GPU view: positions come in
// clip space already letterboxed by the CPU side, uv is the texture coord.
layout(location = 0) in vec2 position;
layout(location = 1) in vec2 uv;
layout(location = 0) out vec2 v_uv;

void main()
{
    v_uv = uv;
    gl_Position = vec4(position, 0.0, 1.0);
}
