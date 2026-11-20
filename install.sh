#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: bash install.sh [install|activate|remove] [plugin-source-directory]"
}

fail() {
    printf '%s\n' "$*" >&2
    exit 1
}

case "${1:-install}" in
    -h|--help) usage; exit 0 ;;
    install|activate|remove) action="${1:-install}" ;;
    *) usage >&2; exit 2 ;;
esac
if (( $# > 2 )); then
    usage >&2
    exit 2
fi
(( EUID != 0 )) || fail "Run this as your SteamOS desktop user. The script calls sudo when needed."

source_dir="${2:-$(dirname -- "${BASH_SOURCE[0]}")}"
hook_files=(install.py sleep_control.py)
plugin_files=(main.py plugin.json package.json dist/index.js install.py sleep_control.py LICENSE)

required_files=("${hook_files[@]}")
if [[ "$action" == install ]]; then
    required_files=("${plugin_files[@]}")
fi
for file in "${required_files[@]}"; do
    path="$source_dir/$file"
    [[ -f "$path" && ! -L "$path" && -r "$path" ]] || fail "Missing or unreadable plugin file: $path"
done

plugin_parent="$HOME/homebrew/plugins"
plugin_dir="$plugin_parent/Boiler-S2S4-Switcher"
plugin_stage=
hook_stage=

cleanup() {
    if [[ -n "$plugin_stage" ]]; then
        sudo rm -rf -- "$plugin_stage"
    fi
    if [[ -n "$hook_stage" ]]; then
        sudo rm -f -- "$hook_stage/install.py" "$hook_stage/sleep_control.py"
        sudo rmdir -- "$hook_stage"
    fi
}
trap cleanup EXIT

install_decky_files() {
    if [[ -e "$plugin_dir" || -L "$plugin_dir" ]]; then
        [[ -d "$plugin_dir" && ! -L "$plugin_dir" ]] || fail "Unexpected Decky path: $plugin_dir"
        for file in "${plugin_files[@]}"; do
            cmp -s -- "$source_dir/$file" "$plugin_dir/$file" ||
                fail "A different plugin is already in $plugin_dir. Use the matching source to activate or remove its system integration."
        done
        return
    fi

    plugin_stage=$(sudo mktemp -d -- "$HOME/homebrew/.boiler-s2s4.XXXXXX")
    sudo install -d -m 0755 -- "$plugin_stage/dist"
    for file in "${plugin_files[@]}"; do
        sudo install -T -m 0644 -- /dev/stdin "$plugin_stage/$file" < "$source_dir/$file"
    done
    sudo chmod 0755 -- "$plugin_stage"
    sudo mv -nT -- "$plugin_stage" "$plugin_dir"
    if sudo test -d "$plugin_stage"; then
        fail "The Decky plugin folder appeared during installation. Inspect $plugin_dir before retrying."
    fi
    plugin_stage=
}

if [[ "$action" == install ]]; then
    [[ -d "$plugin_parent" && ! -L "$plugin_parent" ]] ||
        fail "Decky's standard plugin folder is missing: $plugin_parent. For a custom Decky path, install the ZIP in Decky and use activate."
    install_decky_files
fi

hook_stage=$(sudo mktemp -d -- /root/boiler-s2s4.XXXXXX)
for file in "${hook_files[@]}"; do
    sudo install -T -m 0644 -- /dev/stdin "$hook_stage/$file" < "$source_dir/$file"
done

hook_action="$action"
if [[ "$action" == install ]]; then
    hook_action=activate
fi
sudo /usr/bin/python3 -I -B "$hook_stage/install.py" "$hook_action"

case "$action" in
    install)
        echo "Plugin files and system hook are installed. Reloading Decky."
        sudo /usr/bin/systemctl restart plugin_loader.service
        ;;
    remove)
        echo "System hook removed in this SteamOS slot. Remove it in any other installed slot before uninstalling the plugin in Decky."
        ;;
esac
