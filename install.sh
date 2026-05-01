#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/tab-search"
BINDING="${1:-<Super>F8}"
BINDING_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/"

echo "==> Installing dependencies..."
sudo apt install -y rofi python3.12 python3-gi gir1.2-atspi-2.0 xdotool libglib2.0-bin

echo "==> Registering GNOME keybinding ($BINDING)..."
gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['$BINDING_PATH']"
gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BINDING_PATH" name    "Terminal Tab Search"
gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BINDING_PATH" command "$SCRIPT"
gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$BINDING_PATH" binding "$BINDING"

echo
echo "Done. Press $BINDING to open the tab switcher."
echo "To use a different key: $0 '<Super>F9'  (or any other combo)"
echo "Note: Super+<letter> combos are intercepted by GNOME Shell — use Super+F<N> or similar."
