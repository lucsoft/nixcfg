# Suspend/resume workarounds and the debugging scaffolding for them.
# All of this is transitional — see the notes on when each can go.

{ config, pkgs, ... }:

{
  # disable my mouse from waking up the pc
  services.udev.extraRules = ''
    ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="1ea7", ATTR{idProduct}=="0066", ATTR{power/wakeup}="disabled"
  '';
}
