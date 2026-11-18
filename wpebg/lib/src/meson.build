lib_sources = [
  'wpebg-player.c',
  'wpebg-effect.c',
]

lib_headers = [
  'wpebg-player.h',
  'wpebg-effect.h',
]

wpebg_lib = shared_library(
  'wpebg-' + api_version,
  lib_sources + lib_headers,
  dependencies: deps,
  c_args: ['-DWPEBG_PLUGIN_PATH="@0@"'.format(get_option('plugin_path'))],
  version: meson.project_version(),
  soversion: '0',
  install: true,
  install_dir: get_option('libdir'),
)

# Clutter-18.gir and Cogl-18.gir live in mutter's own private directory, not
# on the default search path, so the scanner is pointed at it — see
# shaderbg/lib for what happens without it.
mutter_girdir = libmutter_dep.get_variable(pkgconfig: 'girdir')

wpebg_gir = gnome.generate_gir(
  wpebg_lib,
  sources: lib_sources + lib_headers,
  nsversion: api_version,
  namespace: 'WpeBg',
  symbol_prefix: 'wpebg',
  identifier_prefix: 'WpeBg',
  includes: ['GObject-2.0', 'Clutter-' + mutter_api_version, 'Cogl-' + mutter_api_version],
  extra_args: ['--include-uninstalled=' + mutter_girdir / 'Clutter-@0@.gir'.format(mutter_api_version)],
  dependencies: deps,
  install: true,
  install_dir_gir: get_option('datadir') / 'gir-1.0',
  install_dir_typelib: get_option('libdir') / 'girepository-1.0',
  fatal_warnings: false,
)
