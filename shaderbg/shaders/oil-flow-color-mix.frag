// Oil flow color mix — biasia
// https://www.shadertoy.com/view/w3dSWj
// Imported; see README.md for how, and sources.nix for the speed.

void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
    vec2 uv = fragCoord/iResolution.xy;
    
    vec3 colors[4];
    colors[3] = vec3(224., 83., 22.) / 255.0;   
    colors[1] = vec3(172., 182., 169.) / 255.0; 
    colors[2] = vec3(30., 50., 101.) / 255.0;   
    colors[0] = vec3(0., 0., 0.) / 255.0;       

    uv *= 3.5;
    
    float t = 0.0;
    float len;
    
    float d = -(iTime * 0.3);
    
    float d2 = d, d3 = d;
    
    for (float i = 0.0; i < 3.0; ++i) {
        len = length(vec2(t,d));
        t += cos(i + d - t * uv.x + sin(len));
        d2 += cos((uv.y+0.4) + t + cos(len));
        d3 += cos((uv.y-0.4) * i + t + cos(len));
        d += cos(uv.y * i + t + cos(len))*2.0;
    }
    
    d += (iTime * 0.3);
    d2 += (iTime * 0.3);
    d3 += (iTime * 0.3);
    
    float d_norm = cos(d) * 0.5 + 0.5;
    float d_norm2 = cos(d2) * 0.5 + 0.5;
    float d_norm3 = cos(d3) * 0.5 + 0.5;
    float t_norm = cos(t) * 0.5 + 0.5;
    float dt_norm = cos(d * t) * 0.5 + 0.5;
    
    vec3 baseColor = mix(colors[1], colors[0], d_norm);
    vec3 secondBaseColor = mix(baseColor, colors[2], d_norm2);
    vec3 finalColor = mix(secondBaseColor, colors[3], d_norm3);
    
    vec3 final = vec3(d2);
    
    fragColor = vec4(baseColor,1.0);
}
