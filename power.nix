# Suspend/resume workarounds and the debugging scaffolding for them.
# All of this is transitional — see the notes on when each can go.

{ config, pkgs, ... }:

{
  # On 2026-09-20 this machine hung resuming from S3: it entered "PM: suspend
  # entry (deep)" and never came back, with nothing in the journal because the
  # hang was over before userspace thawed. The cause was firmware — BIOS 3.50
  # aborted \_SB.ALIB and \_SB.PMF._DSM with AE_AML_LOOP_TIMEOUT, AMD's own
  # power-handoff ACPI methods, on exactly the failing path. BIOS 4.43 clears
  # all four errors, so no mem_sleep_default override is needed: deep is
  # already the default.
  #
  # no_console_suspend keeps the console alive across the transition, so a
  # regression leaves something on screen instead of vanishing silently. Safe
  # to drop once sleep has been reliable a while.
  boot.kernelParams = [ "no_console_suspend" ];

  # The 2.4 GHz mouse receiver woke the machine overnight — a sensor twitch or
  # RF noise on the dongle is enough. The keyboard still wakes it.
  services.udev.extraRules = ''
    ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="1ea7", ATTR{idProduct}=="0066", ATTR{power/wakeup}="disabled"
  '';

  # A resume hang reaches no journal, but pm_trace stashes a hash of the last
  # device resume callback in the RTC, where it survives a power-cycle and is
  # printed on the next boot:
  #
  #     sudo dmesg | grep -iE 'hash matches|Magic number'
  #
  # The cost is a scrambled RTC clock after a hang; NTP fixes it shortly after
  # the next boot. Drop this unit once suspend is reliable again.
  systemd.services.arm-pm-trace = {
    description = "Arm PM trace to debug resume hangs";
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = "echo 1 > /sys/power/pm_trace";
  };
}
