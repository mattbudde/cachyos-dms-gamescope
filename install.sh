#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
dry_run=false
assume_yes=false
install_package=true
install_plugin=true
enable_autologin=true
desktop_session=""
initial_target="desktop"

usage() {
    sed -n '1,120p' <<'EOF'
Usage: ./install.sh [options]

Options:
  --dry-run                    Print planned changes without applying them
  --yes                        Accept recommended prompt defaults
  --desktop-session ID         Desktop session file (default: niri.desktop)
  --initial-target TARGET      desktop or gamescope (default: desktop)
  --no-package                 Do not install gamescope-session-cachyos
  --no-plugin                  Do not install the DMS launcher/bar plugin
  --no-autologin               Do not enable/sync DMS greetd auto-login
  -h, --help                   Show this help
EOF
}

while (($#)); do
    case "$1" in
        --dry-run) dry_run=true ;;
        --yes) assume_yes=true ;;
        --desktop-session)
            shift
            [[ $# -gt 0 ]] || { printf '%s\n' '--desktop-session requires a value' >&2; exit 2; }
            desktop_session="$1"
            ;;
        --initial-target)
            shift
            [[ $# -gt 0 ]] || { printf '%s\n' '--initial-target requires a value' >&2; exit 2; }
            initial_target="$1"
            ;;
        --no-package) install_package=false ;;
        --no-plugin) install_plugin=false ;;
        --no-autologin) enable_autologin=false ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

[[ $initial_target == desktop || $initial_target == gamescope ]] || {
    printf '%s\n' '--initial-target must be desktop or gamescope' >&2
    exit 2
}

if [[ $EUID -eq 0 ]]; then
    printf '%s\n' 'Run this installer as the desktop user, not with sudo.' >&2
    exit 1
fi

login_user="${USER:-$(id -un)}"
user_home="${HOME:?HOME is not set}"
state_dir="$user_home/.local/state/cachyos-gamemode"
state_file="$state_dir/install-state.json"
plugin_dir="$user_home/.config/DankMaterialShell/plugins/cachyosGameMode"
guard_file="$user_home/.config/inhibit-short-session-tracker"

say() {
    printf '%s\n' "$*"
}

show_command() {
    printf '  +'
    printf ' %q' "$@"
    printf '\n'
}

run() {
    if $dry_run; then
        show_command "$@"
    else
        "$@"
    fi
}

ask() {
    local prompt="$1"
    local default="${2:-yes}"
    local answer
    if $assume_yes; then
        [[ $default == yes ]]
        return
    fi
    if [[ $default == yes ]]; then
        read -r -p "$prompt [Y/n] " answer
        [[ ${answer:-y} == [Yy]* ]]
    else
        read -r -p "$prompt [y/N] " answer
        [[ ${answer:-n} == [Yy]* ]]
    fi
}

desktop_file_exists() {
    local session_id="$1"
    [[ -f "/usr/share/wayland-sessions/$session_id" \
        || -f "/usr/local/share/wayland-sessions/$session_id" \
        || -f "$user_home/.local/share/wayland-sessions/$session_id" ]]
}

validate_session_id() {
    local value="$1"
    [[ $value =~ ^[A-Za-z0-9._+-]+\.desktop$ ]]
}

read_bool_setting() {
    local setting="$1"
    local value
    value="$(dms ipc call settings get "$setting" 2>/dev/null || printf false)"
    [[ $value == true ]] && printf true || printf false
}

say 'CachyOS Game Mode live-handoff installer'
say

if [[ -r /etc/os-release ]]; then
    os_id="$(sed -n 's/^ID=//p' /etc/os-release | tr -d '"' | head -n1)"
else
    os_id=""
fi
if [[ $os_id != cachyos ]]; then
    printf 'This installer targets CachyOS; detected ID=%q.\n' "$os_id" >&2
    exit 1
fi

command -v pacman >/dev/null || { printf '%s\n' 'pacman is required.' >&2; exit 1; }
command -v python3 >/dev/null || { printf '%s\n' 'python3 is required.' >&2; exit 1; }
command -v pkexec >/dev/null || { printf '%s\n' 'pkexec is required.' >&2; exit 1; }
command -v dms >/dev/null || { printf '%s\n' 'DMS CLI is required.' >&2; exit 1; }
command -v rg >/dev/null || { printf '%s\n' 'ripgrep (rg) is required.' >&2; exit 1; }

display_manager="$(systemctl show -p Id --value display-manager 2>/dev/null || true)"
if [[ $display_manager != greetd.service ]]; then
    printf 'Expected greetd.service, but display-manager is %q.\n' "$display_manager" >&2
    exit 1
fi

if [[ -z $desktop_session ]]; then
    if desktop_file_exists niri.desktop; then
        desktop_session=niri.desktop
    elif desktop_file_exists plasma.desktop; then
        desktop_session=plasma.desktop
    else
        printf '%s\n' 'Could not find niri.desktop or plasma.desktop.' >&2
        exit 1
    fi
fi
validate_session_id "$desktop_session" || {
    printf 'Unsafe desktop session id: %q\n' "$desktop_session" >&2
    exit 1
}
desktop_file_exists "$desktop_session" || {
    printf 'Desktop session %q was not found.\n' "$desktop_session" >&2
    exit 1
}

package_was_installed=false
if pacman -Q gamescope-session-cachyos >/dev/null 2>&1; then
    package_was_installed=true
fi

autologin_was_enabled="$(read_bool_setting greeterAutoLogin)"
remember_user_was_enabled="$(read_bool_setting greeterRememberLastUser)"
remember_session_was_enabled="$(read_bool_setting greeterRememberLastSession)"

guard_was_present=false
[[ -e $guard_file ]] && guard_was_present=true
plugin_managed=false
greeter_settings_managed=false

if [[ -f $state_file ]] && command -v jq >/dev/null; then
    # Preserve the original pre-install state across an idempotent reinstall.
    package_was_installed="$(jq -r '.package_was_installed // false' "$state_file")"
    autologin_was_enabled="$(jq -r '.autologin_was_enabled // false' "$state_file")"
    remember_user_was_enabled="$(jq -r '.remember_user_was_enabled // false' "$state_file")"
    remember_session_was_enabled="$(jq -r '.remember_session_was_enabled // false' "$state_file")"
    guard_was_present="$(jq -r '.guard_was_present // false' "$state_file")"
    plugin_managed="$(jq -r '.plugin_installed // false' "$state_file")"
    greeter_settings_managed="$(jq -r '.greeter_settings_changed // false' "$state_file")"
fi

$install_plugin && plugin_managed=true
$enable_autologin && greeter_settings_managed=true

record_install_state() {
    say 'Recording install state before making changes...'
    if $dry_run; then
        show_command mkdir -p "$state_dir"
        say "  + write $state_file"
        return
    fi

    mkdir -p "$state_dir"
    local state_temp
    state_temp="$(mktemp "$state_dir/.install-state.XXXXXX")"
    printf '{\n  "package_was_installed": %s,\n  "autologin_was_enabled": %s,\n  "remember_user_was_enabled": %s,\n  "remember_session_was_enabled": %s,\n  "greeter_settings_changed": %s,\n  "guard_was_present": %s,\n  "plugin_installed": %s,\n  "desktop_session": "%s"\n}\n' \
        "$package_was_installed" "$autologin_was_enabled" \
        "$remember_user_was_enabled" "$remember_session_was_enabled" \
        "$greeter_settings_managed" "$guard_was_present" "$plugin_managed" \
        "$desktop_session" > "$state_temp"
    chmod 0600 "$state_temp"
    mv -f "$state_temp" "$state_file"
}

say "User:             $login_user"
say "Desktop target:   $desktop_session"
say "Game target:      gamescope-session.desktop"
say "Initial target:   $initial_target"
say "Display manager:  $display_manager"
say "Install package:  $install_package"
say "Install plugin:   $install_plugin"
say "Enable auto-login: $enable_autologin"
say

if ! $assume_yes && ! ask 'Continue with this configuration?' yes; then
    say 'Cancelled.'
    exit 0
fi

for destination in \
    /usr/local/bin/cachyos-sessionctl \
    /usr/libexec/cachyos-session-handoff \
    /usr/local/bin/steamos-session-select \
    /usr/local/bin/start-gamescope-session; do
    if [[ -e $destination ]] && ! rg -q 'CachyOS Game Mode|cachyos-session' "$destination" 2>/dev/null; then
        printf 'Refusing to overwrite unrelated file: %s\n' "$destination" >&2
        exit 1
    fi
done

if [[ -e /etc/cachyos-gamemode.conf ]] \
    && ! rg -q 'gamescope_session[[:space:]]*=[[:space:]]*gamescope-session\.desktop' \
        /etc/cachyos-gamemode.conf 2>/dev/null; then
    printf '%s\n' 'Refusing to overwrite unrelated file: /etc/cachyos-gamemode.conf' >&2
    exit 1
fi
if [[ -e /usr/share/polkit-1/actions/org.cachyos.gamemode.policy ]] \
    && ! rg -q 'org\.cachyos\.gamemode\.switch-session' \
        /usr/share/polkit-1/actions/org.cachyos.gamemode.policy 2>/dev/null; then
    printf '%s\n' 'Refusing to overwrite an unrelated CachyOS Game Mode polkit policy.' >&2
    exit 1
fi

if [[ -d $plugin_dir ]] && ! rg -q '"id"[[:space:]]*:[[:space:]]*"cachyosGameMode"' "$plugin_dir/plugin.json" 2>/dev/null; then
    printf 'Refusing to overwrite unrelated plugin directory: %s\n' "$plugin_dir" >&2
    exit 1
fi

if [[ ! -d /var/cache/dms-greeter/.local/state \
    || ! -w /var/cache/dms-greeter/.local/state ]]; then
    printf '%s\n' 'The current user cannot update the DMS greeter memory directory.' >&2
    printf '%s\n' 'Verify that the DMS greeter is installed and that this user belongs to the greeter group.' >&2
    exit 1
fi

record_install_state

if $install_package && ! pacman -Q gamescope-session-cachyos >/dev/null 2>&1; then
    say 'Installing CachyOS Gamescope session package...'
    run sudo pacman -S --needed gamescope-session-cachyos
fi

if ! $dry_run && ! desktop_file_exists gamescope-session.desktop; then
    printf '%s\n' 'gamescope-session.desktop is missing; install gamescope-session-cachyos first.' >&2
    exit 1
fi

say 'Installing session handoff commands and policy...'
run sudo install -D -o root -g root -m 0755 \
    "$project_dir/src/cachyos-sessionctl" /usr/local/bin/cachyos-sessionctl
run sudo install -D -o root -g root -m 0755 \
    "$project_dir/src/cachyos-session-handoff" /usr/libexec/cachyos-session-handoff
run sudo install -D -o root -g root -m 0755 \
    "$project_dir/src/steamos-session-select" /usr/local/bin/steamos-session-select
run sudo install -D -o root -g root -m 0755 \
    "$project_dir/src/start-gamescope-session" /usr/local/bin/start-gamescope-session
run sudo install -D -o root -g root -m 0644 \
    "$project_dir/polkit/org.cachyos.gamemode.policy" \
    /usr/share/polkit-1/actions/org.cachyos.gamemode.policy

config_temp="$(mktemp /tmp/cachyos-gamemode.conf.XXXXXX)"
trap 'rm -f -- "$config_temp"' EXIT
printf '%s\n' \
    '[session]' \
    "login_user = $login_user" \
    "desktop_session = $desktop_session" \
    'gamescope_session = gamescope-session.desktop' \
    'dms_cache_dir = /var/cache/dms-greeter' \
    'greetd_runfile = /run/greetd.run' \
    'greetd_service = greetd.service' > "$config_temp"
run sudo install -o root -g root -m 0644 "$config_temp" /etc/cachyos-gamemode.conf

if ! $guard_was_present; then
    say 'Enabling the Steam short-session repair guard for initial testing...'
    run install -D -m 0644 /dev/null "$guard_file"
fi

if $install_plugin; then
    say 'Installing DMS launcher/bar plugin...'
    run mkdir -p "$plugin_dir"
    run cp -a "$project_dir/dms-plugin/cachyosGameMode/." "$plugin_dir/"
    run rm -f -- \
        "$plugin_dir/CachyOSGameModeLauncher.qml" \
        "$plugin_dir/CachyOSGameModeWidget.qml"
    if ! $dry_run; then
        # Unload first so a launcher-only install cannot leave DMS's component
        # map in a stale loaded state while it is upgraded to a composite plugin.
        dms ipc call plugins disable cachyosGameMode >/dev/null 2>&1 || true
        dms ipc call plugin-scan scan >/dev/null 2>&1 || true
        for _ in {1..20}; do
            if dms ipc call plugin-scan list 2>/dev/null \
                | cut -f1 | rg -qx cachyosGameMode; then
                break
            fi
            sleep 0.1
        done
        dms ipc call plugin-scan rescan cachyosGameMode >/dev/null 2>&1 || true
        for _ in {1..20}; do
            if dms ipc call plugin-scan list 2>/dev/null \
                | cut -f1 | rg -qx cachyosGameMode; then
                break
            fi
            sleep 0.1
        done
        dms ipc call plugins enable cachyosGameMode >/dev/null 2>&1 || true
    else
        show_command dms ipc call plugins disable cachyosGameMode
        show_command dms ipc call plugin-scan scan
        show_command dms ipc call plugin-scan rescan cachyosGameMode
        show_command dms ipc call plugins enable cachyosGameMode
    fi
fi

if $enable_autologin; then
    say 'Enabling DMS remembered-session auto-login...'
    if ! $dry_run; then
        dms ipc call settings set greeterRememberLastUser true >/dev/null
        dms ipc call settings set greeterRememberLastSession true >/dev/null
        dms ipc call settings set greeterAutoLogin true >/dev/null
        dms greeter sync --autologin
        if ! rg -q '^\[initial_session\]' /etc/greetd/config.toml \
            || ! rg -q '(dms-greeter|dms[[:space:]]+greeter)[[:space:]]+launch-session.*--from-memory' \
                /etc/greetd/config.toml; then
            printf '%s\n' 'DMS did not create the expected greetd initial_session.' >&2
            exit 1
        fi
    else
        show_command dms ipc call settings set greeterRememberLastUser true
        show_command dms ipc call settings set greeterRememberLastSession true
        show_command dms ipc call settings set greeterAutoLogin true
        show_command dms greeter sync --autologin
    fi
else
    say 'Warning: live handoff needs an existing DMS greetd initial_session; auto-login setup was skipped.'
fi

say "Selecting initial remembered target: $initial_target"
if $dry_run; then
    show_command /usr/local/bin/cachyos-sessionctl set "$initial_target"
else
    /usr/local/bin/cachyos-sessionctl set "$initial_target"
fi

say
if $dry_run; then
    say 'Dry run complete; no system or user configuration was changed.'
else
    say 'Installation complete.'
    if $install_plugin; then
        say 'Restarting DMS to refresh its external QML component cache...'
        dms restart >/dev/null 2>&1 || true
    fi
    say 'Save open work, then run:'
    say '  cachyos-sessionctl switch gamescope --confirm'
    say 'In DMS Launcher, type: :session'
fi
