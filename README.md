# CachyOS DMS Gamescope

> [!CAUTION]
> This project was developed primarily with AI assistance. Always review and
> understand the scripts before running them on your own machine, especially
> commands that use `sudo`, modify auto-login settings, install polkit rules, or
> restart the display manager.

Live switching between a CachyOS desktop session and the native
Gamescope/Steam session, integrated with the Dank Material Shell (DMS).

```text
Desktop → DMS DankBar or launcher → Gamescope + Steam
Gamescope → Steam “Switch to Desktop” → Desktop
```

No reboot is required. A live switch updates the session remembered by the DMS
greeter, re-arms greetd's one-shot auto-login, and restarts `greetd`. Restarting
the display manager ends the current graphical session, so save your work
before switching.

> [!WARNING]
> This is an independent integration that changes greetd auto-login settings
> and installs a narrowly scoped polkit action. Read [Security and session
> behavior](#security-and-session-behavior) before installing it.

## What it provides

- A DMS DankBar widget with an **Enter Game Mode** action and remembered-session
  controls.
- DMS launcher actions under the `:session` trigger.
- `cachyos-sessionctl` for selecting, switching, and inspecting sessions.
- Steam **Power → Switch to Desktop** integration from inside Gamescope.
- A Gamescope launcher shim that removes stale desktop display variables during
  a live handoff.
- A tracked uninstaller that restores the DMS greeter settings recorded before
  installation.

The installer uses the official `gamescope-session-cachyos` package. It does
not install the larger `cachyos-handheld` meta-package or replace the existing
DMS/greetd desktop setup.

## Requirements and compatibility

- A desktop CachyOS installation using `greetd` as `display-manager.service`.
- Dank Material Shell and its greetd greeter configuration.
- DMS 1.5.0 or newer for the composite launcher/DankBar plugin.
- Niri or Plasma, or another installed Wayland session supplied explicitly with
  `--desktop-session NAME.desktop`.
- `sudo`, `pacman`, Python 3, `pkexec`/polkit, `systemctl`, `rg`, and `jq`.
- `kdialog` or `zenity` for confirmation dialogs launched from the DMS widget.

The current known-working combination is CachyOS with DMS 1.5.3,
`gamescope-session-cachyos` 1.1.6, and greetd 0.10.3. These are test versions,
not strict pins. Desktop and handheld hardware vary, so verify display routing,
audio, input, refresh rate, HDR, and suspend on your system.

## Install

Run the installer as your normal desktop user, not as root:

```bash
git clone https://github.com/mattbudde/cachyos-dms-gamescope.git
cd cachyos-dms-gamescope
./install.sh --dry-run
./install.sh
```

The dry run prints the planned commands without changing system or user
configuration. The normal installer is interactive; review its detected user,
desktop session, display manager, and initial target before continuing.

Useful non-interactive options:

```bash
./install.sh --yes --desktop-session niri.desktop --initial-target desktop
./install.sh --yes --no-package --no-plugin
./install.sh --yes --no-autologin
```

`--no-autologin` is intended for systems that already have a compatible DMS
greetd `initial_session`; otherwise live handoff cannot start the remembered
session automatically.

After installation, add **CachyOS Game Mode** in **Settings → Appearance →
DankBar Layout**. You can also open the DMS launcher and type `:session`.

## Command-line use

```bash
cachyos-sessionctl status
cachyos-sessionctl doctor
cachyos-sessionctl switch gamescope --confirm
cachyos-sessionctl switch desktop --confirm
cachyos-sessionctl set gamescope
cachyos-sessionctl set desktop
```

- `status` shows the active desktop and the session remembered by DMS.
- `doctor` checks whether a live switch can work: installed files, greetd, greeter
  memory, the plugin, and display routing. Warnings do not fail the command;
  `--json` prints the same report for scripts.
- `set` changes the remembered session for the next DMS login without ending
  the current session.
- `switch` changes the remembered session and performs a live handoff.
- `--confirm` opens a graphical confirmation dialog when possible.
- `--yes` skips confirmation and is intended for trusted automation.

## Choosing a Game Mode monitor

```bash
cachyos-sessionctl display list                  # connected monitors, on or off on the desktop
cachyos-sessionctl display set gamescope DP-1    # Gamescope starts on DP-1 when connected
cachyos-sessionctl display set gamescope auto    # back to the Gamescope package default
cachyos-sessionctl display set desktop eDP-1     # niri focuses eDP-1 after every login
cachyos-sessionctl display set desktop auto      # internal panel if present, else first by name
cachyos-sessionctl status                        # shows both choices
```

`display list` and the DankBar popout show every monitor niri reports as
connected, including one you have turned off on the desktop. A TV that is off
in niri is still a valid Game Mode monitor: Gamescope drives it directly, so
it appears marked `off` (or "off on desktop" in the popout) and can be pinned.
Under any other desktop, `display list` prints one line and exits without
listing anything.

The DankBar popout lists those monitors under **Game Mode monitor**;
pick one before **Enter Game Mode**. The choice is stored in
`~/.config/cachyos-gamemode/display.conf` and survives reinstalls and
uninstalls. When Gamescope starts, the launcher shim passes the chosen
connector as `OUTPUT_CONNECTOR=NAME,*`, so an unplugged monitor falls back to
any connected output. When niri starts, an autostart entry runs
`cachyos-sessionctl display restore-desktop`, which focuses the desktop
primary; under any other desktop it exits without doing anything.

## How the handoff works

1. `cachyos-sessionctl` atomically updates the DMS greeter's `memory.json` with
   the selected desktop file.
2. The polkit helper removes `/run/greetd.run`, re-arming greetd's one-shot
   initial session, and queues a restart of `greetd.service`.
3. DMS launches the remembered session from its greetd `initial_session`.
4. In Gamescope, the `/usr/local/bin/steamos-session-select` compatibility
   wrapper handles Steam's `desktop` action and performs the reverse handoff.

The project installs `/usr/local/bin/start-gamescope-session` ahead of the
package-owned `/usr/bin` command. The wrapper clears stale `WAYLAND_DISPLAY`,
`DISPLAY`, compositor socket, and Xauthority variables before invoking the
official CachyOS launcher. Without that cleanup, a persistent user systemd
manager can make Gamescope behave like a nested compositor after a live switch.

## Security and session behavior

- A live switch terminates the entire current graphical session. Unsaved work
  will be lost.
- Enabling DMS greetd auto-login allows anyone with physical access to reach the
  configured user's graphical session without entering that user's password.
  Disk encryption and the lock screen are separate protections.
- The polkit policy allows only an active local user to invoke the fixed
  `/usr/libexec/cachyos-session-handoff` helper. The helper accepts only
  `desktop` or `gamescope`, validates its root-owned configuration, verifies the
  configured caller, and only re-arms/restarts `greetd.service`.
- The integration supports one configured login user at a time.

## First Gamescope test

The installer creates `~/.config/inhibit-short-session-tracker` unless it
already exists. The official CachyOS session checks this file before performing
its short-session auto-repair, preventing it from resetting Steam state while
the integration is being tested.

1. Save all desktop work.
2. Run `cachyos-sessionctl switch gamescope --confirm`.
3. Verify Steam, audio, controllers, display selection, refresh rate, and
   sleep/resume.
4. Use Steam's **Power → Switch to Desktop** action.
5. After several successful round trips, remove the temporary guard:

   ```bash
   rm ~/.config/inhibit-short-session-tracker
   ```

If Gamescope exits immediately, greetd consumes the re-armed one-shot and falls
back to the DMS greeter instead of repeatedly launching a broken session.

## Files installed

```text
/usr/local/bin/cachyos-sessionctl
/usr/local/bin/steamos-session-select
/usr/local/bin/start-gamescope-session
/usr/libexec/cachyos-session-handoff
/usr/share/polkit-1/actions/org.cachyos.gamemode.policy
/etc/cachyos-gamemode.conf
~/.config/DankMaterialShell/plugins/cachyosGameMode/
~/.config/autostart/cachyos-gamemode-restore-display.desktop
~/.local/state/cachyos-gamemode/install-state.json
```

The installer also manages the DMS remembered-user, remembered-session, and
auto-login settings unless `--no-autologin` is used.

## Uninstall

Preview the tracked removal first:

```bash
./uninstall.sh --dry-run
./uninstall.sh
```

To also remove `gamescope-session-cachyos` when it was not present before this
project installed it:

```bash
./uninstall.sh --remove-package
```

The uninstaller refuses to proceed without its install-state file and checks
ownership markers before removing system files.

## Troubleshooting

Check the selected and active sessions, then whether a live switch can work:

```bash
cachyos-sessionctl status
cachyos-sessionctl doctor
```

`doctor` covers the files, greetd, greeter memory, plugin, and monitor choice.
If the plugin is loaded but absent from the bar, add it in the DankBar Layout
settings. After changing plugin files during development, `dms restart` clears
Quickshell's external-component cache.

## Development checks

The test suite uses temporary fake DMS/greetd trees and never restarts the live
display manager:

```bash
./tests/run.sh
```

## Upstream projects

- [CachyOS Gamescope session](https://github.com/CachyOS/gamescope-session)
- [CachyOS gaming guide](https://wiki.cachyos.org/configuration/gaming/)
- [Dank Material Shell](https://github.com/AvengeMedia/DankMaterialShell)
- [greetd configuration manual](https://man.archlinux.org/man/greetd.5.en)

This project is not affiliated with or endorsed by CachyOS, DankLinux, Valve,
or the upstream Gamescope projects.
