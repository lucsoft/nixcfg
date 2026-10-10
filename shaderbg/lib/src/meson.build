lib_sources = [
  'shaderbg-effect.c',
  'shaderbg-gpu-timer.c',
]

lib_headers = [
  'shaderbg-effect.h',
]

shaderbg_lib = shared_library(
  'shaderbg-' + api_version,
  lib_sources + ['shaderbg-gpu-timer.h'],
  dependencies: deps,
  version: meson.project_version(),
  soversion: '0',
  install: true,
  install_dir: get_option('libdir'),
)

# Clutter-18.gir and Cogl-18.gir live in mutter's own private directory, not
# on the default search path, so the scanner is pointed at it. Without this
# ShaderBgEffect's parent type cannot be resolved and GJS gets a class with
# no ClutterEffect behind it.
mutter_girdir = libmutter_dep.get_variable(pkgconfig: 'girdir')

# Only the effect is scanned. The timer is plain C with GL function pointers
# in it, nothing that belongs in a typelib.
shaderbg_gir = gnome.generate_gir(
  shaderbg_lib,
  sources: ['shaderbg-effect.c', 'shaderbg-effect.h'],
  nsversion: api_version,
  namespace: 'ShaderBg',
  symbol_prefix: 'shaderbg',
  identifier_prefix: 'ShaderBg',
  includes: ['GObject-2.0', 'Clutter-' + mutter_api_version, 'Cogl-' + mutter_api_version],
  extra_args: ['--include-uninstalled=' + mutter_girdir / 'Clutter-@0@.gir'.format(mutter_api_version)],
  dependencies: deps,
  install: true,
  install_dir_gir: get_option('datadir') / 'gir-1.0',
  install_dir_typelib: get_option('libdir') / 'girepository-1.0',
  fatal_warnings: false,
)
