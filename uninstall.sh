#!/usr/bin/env bash
set -euo pipefail

dry_run=false
assume_yes=false
remove_package=false

usage() {
    sed -n '1,100p' <<'EOF'
Usage: ./uninstall.sh [options]

Options:
  --dry-run          Print planned removals without applying them
  --yes              Accept prompt defaults
  --remove-package   Remove gamescope-session-cachyos if this project installed it
  -h, --help         Show this help
EOF
}

while (($#)); do
    case "$1" in
        --dry-run) dry_run=true ;;
        --yes) assume_yes=true ;;
        --remove-package) remove_package=true ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [[ $EUID -eq 0 ]]; then
    printf '%s\n' 'Run this uninstaller as the desktop user, not with sudo.' >&2
    exit 1
fi

user_home="${HOME:?HOME is not set}"
state_dir="$user_home/.local/state/cachyos-gamemode"
state_file="$state_dir/install-state.json"
plugin_dir="$user_home/.config/DankMaterialShell/plugins/cachyosGameMode"
guard_file="$user_home/.config/inhibit-short-session-tracker"

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

if [[ ! -f $state_file ]]; then
    printf 'Install state not found at %s; refusing an untracked uninstall.\n' "$state_file" >&2
    exit 1
fi
command -v jq >/dev/null || { printf '%s\n' 'jq is required for tracked uninstall.' >&2; exit 1; }

package_was_installed="$(jq -r '.package_was_installed // false' "$state_file")"
autologin_was_enabled="$(jq -r '.autologin_was_enabled // false' "$state_file")"
remember_user_was_enabled="$(jq -r '.remember_user_was_enabled // false' "$state_file")"
remember_session_was_enabled="$(jq -r '.remember_session_was_enabled // false' "$state_file")"
greeter_settings_changed="$(jq -r '.greeter_settings_changed // true' "$state_file")"
guard_was_present="$(jq -r '.guard_was_present // false' "$state_file")"
plugin_installed="$(jq -r '.plugin_installed // false' "$state_file")"

verify_owned_file() {
    local path="$1"
    local marker="$2"
    if [[ -e $path ]] && ! grep -Fq -- "$marker" "$path" 2>/dev/null; then
        printf 'Refusing to remove an unrecognized file: %s\n' "$path" >&2
        exit 1
    fi
}

verify_owned_file /usr/local/bin/cachyos-sessionctl 'cachyos-sessionctl:'
verify_owned_file /usr/libexec/cachyos-session-handoff 'cachyos-session-handoff:'
verify_owned_file /usr/local/bin/steamos-session-select 'CachyOS Game Mode compatibility wrapper'
verify_owned_file /usr/local/bin/start-gamescope-session 'CachyOS Game Mode environment scrubber'
verify_owned_file /usr/share/polkit-1/actions/org.cachyos.gamemode.policy \
    'org.cachyos.gamemode.switch-session'
verify_owned_file /etc/cachyos-gamemode.conf 'gamescope_session = gamescope-session.desktop'

if ! $assume_yes; then
    read -r -p 'Remove the CachyOS Game Mode integration? [y/N] ' answer
    [[ ${answer:-n} == [Yy]* ]] || { printf '%s\n' 'Cancelled.'; exit 0; }
fi

if [[ $plugin_installed == true ]]; then
    if [[ -d $plugin_dir ]] \
        && ! grep -Eq '"id"[[:space:]]*:[[:space:]]*"cachyosGameMode"' \
            "$plugin_dir/plugin.json" 2>/dev/null; then
        printf 'Refusing to remove an unrecognized plugin directory: %s\n' "$plugin_dir" >&2
        exit 1
    fi
    if $dry_run; then
        show_command dms ipc call plugins disable cachyosGameMode
    else
        dms ipc call plugins disable cachyosGameMode >/dev/null 2>&1 || true
    fi
    run rm -rf -- "$plugin_dir"
fi

for file in \
    /usr/local/bin/cachyos-sessionctl \
    /usr/libexec/cachyos-session-handoff \
    /usr/local/bin/steamos-session-select \
    /usr/local/bin/start-gamescope-session \
    /usr/share/polkit-1/actions/org.cachyos.gamemode.policy \
    /etc/cachyos-gamemode.conf; do
    run sudo rm -f -- "$file"
done

if [[ $guard_was_present == false ]]; then
    run rm -f -- "$guard_file"
fi

if [[ $greeter_settings_changed == true ]]; then
    if $dry_run; then
        show_command dms ipc call settings set greeterRememberLastUser "$remember_user_was_enabled"
        show_command dms ipc call settings set greeterRememberLastSession "$remember_session_was_enabled"
        show_command dms ipc call settings set greeterAutoLogin "$autologin_was_enabled"
        show_command dms greeter sync --autologin
    else
        dms ipc call settings set greeterRememberLastUser "$remember_user_was_enabled" >/dev/null
        dms ipc call settings set greeterRememberLastSession "$remember_session_was_enabled" >/dev/null
        dms ipc call settings set greeterAutoLogin "$autologin_was_enabled" >/dev/null
        dms greeter sync --autologin
    fi
fi

if $remove_package && [[ $package_was_installed == false ]] \
    && pacman -Q gamescope-session-cachyos >/dev/null 2>&1; then
    run sudo pacman -Rns gamescope-session-cachyos
fi

run rm -f -- "$state_file"
if ! $dry_run; then
    rmdir "$state_dir" 2>/dev/null || true
fi

printf '%s\n' 'CachyOS Game Mode integration removed.'
