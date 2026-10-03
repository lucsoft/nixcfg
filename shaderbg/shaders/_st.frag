// TEMPORAER: harte Kanten bei st = 0.5 in beiden Achsen.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 st = cogl_tex_coord_in[0].st;
    float a = step(0.5, st.s);
    float b = step(0.5, st.t);
    fragColor = vec4(a, b, 1.0 - a * b, 1.0);
}
