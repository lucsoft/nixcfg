project('wpebg', 'c',
  version: '0.1.0',
  license: 'GPL-3.0-or-later',
  meson_version: '>= 0.56.0',
  default_options: [
    'warning_level=2',
    'c_std=gnu11',
  ],
)

api_version = '1.0'

# Named literally, as in shaderbg/lib: a mutter bump fails to configure here
# rather than building something the Shell would refuse to load.
mutter_api_version = '18'
mutter_req = '>= 50.0'

libmutter_dep = dependency('libmutter-' + mutter_api_version, version: mutter_req)

deps = [
  dependency('glib-2.0', version: '>= 2.76'),
  dependency('gobject-2.0', version: '>= 2.76'),
  dependency('gio-2.0', version: '>= 2.76'),
  dependency('graphene-gobject-1.0', version: '>= 1.10.2'),
  dependency('mutter-clutter-' + mutter_api_version, version: mutter_req),
  dependency('mutter-cogl-' + mutter_api_version, version: mutter_req),
  libmutter_dep,
  dependency('gstreamer-1.0', version: '>= 1.24'),
  dependency('gstreamer-app-1.0', version: '>= 1.24'),
  dependency('gstreamer-video-1.0', version: '>= 1.24'),
]

gnome = import('gnome')

subdir('src')
