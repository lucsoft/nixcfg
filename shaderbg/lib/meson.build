project('shaderbg', 'c',
  version: '0.1.0',
  license: 'GPL-3.0-or-later',
  meson_version: '>= 0.56.0',
  default_options: [
    'warning_level=2',
    'c_std=gnu11',
  ],
)

api_version = '1.0'

# meson.build names libmutter-18 literally, which is the ABI mutter 50 ships.
# A mutter bump moves that number, and this fails to configure rather than
# building something the Shell would refuse to load.
mutter_api_version = '18'
mutter_req = '>= 50.0'

glib_dep     = dependency('glib-2.0', version: '>= 2.66')
gobject_dep  = dependency('gobject-2.0', version: '>= 2.66')
graphene_dep = dependency('graphene-gobject-1.0', version: '>= 1.10.2')
clutter_dep  = dependency('mutter-clutter-' + mutter_api_version, version: mutter_req)
cogl_dep     = dependency('mutter-cogl-' + mutter_api_version, version: mutter_req)
libmutter_dep = dependency('libmutter-' + mutter_api_version, version: mutter_req)

# The timer query is reached through eglGetProcAddress: mutter 50 dropped
# epoxy and links libGL/libGLESv2/libEGL itself, so there is no loader to
# borrow and the EXT entry points have to be resolved by hand.
egl_dep = dependency('egl')

deps = [
  glib_dep,
  gobject_dep,
  graphene_dep,
  clutter_dep,
  cogl_dep,
  libmutter_dep,
  egl_dep,
]

gnome = import('gnome')

subdir('src')
