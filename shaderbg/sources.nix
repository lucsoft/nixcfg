# The shader set, in the order it rotates through: one per day, picked as
# days-since-epoch modulo the length of this list. Appending shifts which day
# every later entry lands on, which does not matter — the rotation keeps no
# state and nothing is owed to a particular date.
#
# `speed` is the time scale a shader ships with. Shadertoy shaders are authored
# against a small preview pane and a good many of them are unwatchable at full
# size and full speed, so everything imported starts at 0.5 — a deliberately
# slow first guess, not a judgement about that shader.
#
# Tuning happens in the extension's preferences, which writes into the `speeds`
# GSettings key rather than here: one value per shader, set once, remembered.
# A shader with no entry there follows the number below, which is also what the
# reset button goes back to. Once a value has settled, move it into this file
# so it survives as part of the configuration.
#
# `id` is the Shadertoy id, as in https://www.shadertoy.com/view/<id>, and is
# kept for attribution rather than for fetching: Shadertoy defaults to
# CC BY-NC-SA and this repository is public. `null` marks a shader written
# here rather than imported.
#
# Filling this list is what shaderbg/import.js is for — see README.md.

[
  {
    id = null;
    file = "drift.frag";
    name = "drift";
    author = "lucsoft";
    speed = 1.0;
  }
  {
    id = "Dds3WB";
    file = "fork-nixie-tube-clock.frag";
    name = "Fork Nixie Tube Clock";
    author = "picoplanetdev";
    speed = 0.5;
  }
  {
    id = "4slXW7";
    file = "2d-voxels.frag";
    name = "2D Voxels";
    author = "nimitz";
    speed = 0.5;
  }
  {
    id = "33cGDj";
    file = "clearly-a-bug.frag";
    name = "Clearly a bug";
    author = "mrange";
    speed = 0.5;
  }
  {
    id = "MtSBDc";
    file = "golfing-ether-361-chars.frag";
    name = "Golfing Ether - 361 chars";
    author = "GregRostami";
    speed = 0.5;
  }
  {
    id = "4s2yW1";
    file = "bokeh-paralax.frag";
    name = "Bokeh Paralax";
    author = "knarkowicz";
    speed = 0.5;
  }
  {
    id = "llS3RK";
    file = "worley-noise-waters.frag";
    name = "Worley Noise Waters";
    author = "Kyle273";
    speed = 0.5;
  }
  {
    id = "lslGWr";
    file = "simplicity.frag";
    name = "Simplicity";
    author = "JoshP";
    speed = 0.5;
  }
  {
    id = "mds3DX";
    file = "generative-art-deco-4.frag";
    name = "generative art deco 4";
    author = "morisil";
    speed = 0.5;
  }
  {
    id = "MdyGzR";
    file = "lights-in-smoke.frag";
    name = "Lights in Smoke";
    author = "ehj1";
    speed = 0.5;
  }
  {
    id = "XXtBRr";
    file = "balatro-background-shaders.frag";
    name = "Balatro Background Shaders";
    author = "xxidbr9";
    speed = 0.5;
  }
  {
    id = "MsjSW3";
    file = "ether.frag";
    name = "Ether";
    author = "nimitz";
    speed = 0.5;
  }
  {
    id = "wlVGWd";
    file = "cineshader-fbm.frag";
    name = "CineShader - FBM";
    author = "latyr";
    speed = 0.5;
  }
  {
    id = "XlfGRj";
    file = "star-nest.frag";
    name = "Star Nest";
    author = "Kali";
    speed = 0.5;
  }
  {
    id = "lsl3RH";
    file = "warping-procedural-2.frag";
    name = "Warping - procedural 2";
    author = "iq";
    speed = 0.5;
  }
  {
    id = "3l23Rh";
    file = "protean-clouds.frag";
    name = "Protean clouds";
    author = "nimitz";
    speed = 0.5;
  }
  {
    id = "mtyGWy";
    file = "shader-art-coding-introduction.frag";
    name = "Shader Art Coding Introduction";
    author = "kishimisu";
    speed = 0.5;
  }
]
