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
# This is the *base*. The extension's preferences store a factor on top of it,
# per shader, in the `speeds` GSettings key, and the two multiply. So the
# number here keeps meaning something after the slider has been touched, the
# reset button has somewhere to go back to, and a value that has settled can be
# folded in here by multiplying it in and clearing the factor.
#
# `scale` is optional and almost never wanted. The extension times each shader
# once and draws the demanding ones at half or a quarter of the screen's
# resolution by itself; a number here overrides that measurement outright and
# is the place to put a shader whose look depends on being drawn at full
# resolution, or one the timing gets wrong.
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
    speed = 0.05;
  }
  {
    id = "33cGDj";
    file = "clearly-a-bug.frag";
    name = "Clearly a bug";
    author = "mrange";
    speed = 0.05;
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
    speed = 1.5;
  }
  {
    id = "lslGWr";
    file = "simplicity.frag";
    name = "Simplicity";
    author = "JoshP";
    speed = 0.1;
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
    speed = 0.1;
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
    speed = 0.1;
  }
  {
    id = "3l23Rh";
    file = "protean-clouds.frag";
    name = "Protean clouds";
    author = "nimitz";
    speed = 0.05;
  }
  {
    id = "mtyGWy";
    file = "shader-art-coding-introduction.frag";
    name = "Shader Art Coding Introduction";
    author = "kishimisu";
    speed = 0.1;
  }
  {
    id = "XsXXDn";
    file = "creation-by-silexars.frag";
    name = "Creation by Silexars";
    author = "Danguafer";
    speed = 0.5;
  }
  {
    id = "Mt3GWs";
    file = "structured-vol-sampling.frag";
    name = "Structured Vol Sampling";
    author = "huwb";
    speed = 0.01;
  }
  {
    id = "lsBfDz";
    file = "tiny-clouds.frag";
    name = "[SH17A] Tiny Clouds";
    author = "stubbe";
    speed = 0.1;
  }
  {
    id = "4sXGRM";
    file = "oceanic.frag";
    name = "Oceanic";
    author = "frankenburgh";
    speed = 0.5;
  }
  {
    id = "tdG3Rd";
    file = "base-warp-fbm.frag";
    name = "Base warp fBM";
    author = "trinketMage";
    speed = 0.04;
  }
  {
    id = "XlSSzK";
    file = "sun-surface.frag";
    name = "Sun surface";
    author = "Duke";
    speed = 0.25;
  }
  {
    id = "DdcfzH";
    file = "lava-lamp-gradient.frag";
    name = "Lava Lamp Gradient";
    author = "welches";
    speed = 0.5;
  }
  {
    id = "t3VGWz";
    file = "glossy-gradient-smooth.frag";
    name = "Glossy gradient smooth";
    author = "biasia";
    speed = 0.5;
  }
  {
    id = "w3dSWj";
    file = "oil-flow-color-mix.frag";
    name = "Oil flow color mix";
    author = "biasia";
    speed = 0.5;
  }
  {
    id = "wdyczG";
    file = "gradient-flow.frag";
    name = "Gradient Flow";
    author = "hahnzhu";
    speed = 0.5;
  }
]
