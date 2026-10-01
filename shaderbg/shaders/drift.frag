// drift — the shader that ships with the extension, written for it rather than
// imported. Deliberately cheap: no loops, no raymarching, no texture lookups.
// That makes it the baseline to measure the imported ones against, and it is
// what the extension falls back to when sources.nix is empty.
//
// The palette bottoms out around 0.07 rather than 0.02. A first version sat at
// 0.05–0.16, which is 13–41 out of 255: on screen that is indistinguishable
// from a black rectangle, and it cost an afternoon of chasing a rendering bug
// that was never there.

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;

    float t = iTime * 0.1;

    float band = sin((uv.x + uv.y * 0.35) * 3.0 + t)
               + sin((uv.x * 2.3 - uv.y * 0.70) * 2.0 - t * 0.7) * 0.5;
    band = band * 0.25 + 0.5;

    vec3 col = mix(vec3(0.07, 0.08, 0.14), vec3(0.28, 0.20, 0.42), band);

    // A touch of horizontal grain, enough to keep large flat areas from
    // banding on an 8-bit panel.
    col += 0.015 * sin(uv.y * 40.0 + t * 2.0);

    fragColor = vec4(col, 1.0);
}
