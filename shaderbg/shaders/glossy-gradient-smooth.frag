// Glossy gradient smooth — biasia
// https://www.shadertoy.com/view/t3VGWz
// Imported; see README.md for how, and sources.nix for the speed.

void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
    // Normalized pixel coordinates (from 0 to 1)
    vec2 uv = fragCoord/iResolution.xy;
    
    float d = -(iTime * 0.3);
    float a = 0.0;
    
    for (float i = 0.0; i < 9.0; ++i) {
        a += cos(d + i * uv.x - a);
        d += 0.5*sin(a + i * uv.y);
    }
    
    d += (iTime * 0.3);
    
    float r = cos(uv.x * a)*0.7+0.3;
    float g = cos(uv.y * d)*0.5+0.2;
    float b = cos(a+d)*0.3+0.5;
    vec3 col = vec3(r,g,b);
    col = cos(col * cos(vec3(d, a, 2.5)) * 0.5 + 0.5);
    
    
    //vec3 col = vec3(cos(uv * vec2(d, a)) * 0.6 + 0.4, cos(a + d) * 0.5 + 0.5);
    //col = cos(col * cos(vec3(d, a, 2.5)) * 0.5 + 0.5);
    

    // Output to screen
    fragColor = vec4(col,1.0);
}
