#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/stt"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
AUTO_DIR="$HOME/.config/autostart"

echo "=== STT Type Installer ==="

# ── deps ──
echo "[1/7] Installing apt dependencies..."
sudo apt install -y python3-gi gir1.2-appindicator3-0.1 gir1.2-notify-0.7 xdotool curl alsa-utils
if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
    sudo apt install -y wtype ydotool wl-clipboard 2>/dev/null || true
    sudo usermod -aG input "$USER" 2>/dev/null || true
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger --sysname-match=uinput 2>/dev/null || true
    systemctl --user enable --now ydotool.service 2>/dev/null || true
fi

# ── dirs ──
echo "[2/7] Creating directories..."
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APPS_DIR" "$AUTO_DIR"
mkdir -p "$HOME/.config/stt"

# ── API key ──
echo "[3/7] Lemon Fox API key..."
KEY_FILE="$HOME/.config/stt/key"
if [ -f "$KEY_FILE" ]; then
    echo "  Existing key found. Press Enter to keep it, or type a new one."
fi
echo -n "  API key (from lemonfox.ai/keys): "
read -r USER_KEY
if [ -n "$USER_KEY" ]; then
    echo "$USER_KEY" > "$KEY_FILE"
    echo "  Saved."
elif [ ! -f "$KEY_FILE" ]; then
    echo "  No key set. Use tray menu 'Set API Key' later."
fi
if [ ! -f "$HOME/.config/stt/provider" ]; then
    echo "lemonfox" > "$HOME/.config/stt/provider"
fi
if [ ! -f "$HOME/.config/stt/language" ]; then
    echo "english" > "$HOME/.config/stt/language"
fi
if [ ! -f "$HOME/.config/stt/translate" ]; then
    echo "0" > "$HOME/.config/stt/translate"
fi
if [ ! -f "$HOME/.config/stt/prompt" ]; then
    touch "$HOME/.config/stt/prompt"
fi
# migrate old key file to new per-provider format
if [ -f "$HOME/.config/stt/key" ] && [ ! -f "$HOME/.config/stt/key.lemonfox" ]; then
    cp "$HOME/.config/stt/key" "$HOME/.config/stt/key.lemonfox"
fi

# ── copy ──
echo "[4/7] Installing files..."
cp "$SCRIPT_DIR/stt-app.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/stt" "$BIN_DIR/"
chmod +x "$INSTALL_DIR/stt-app.py" "$BIN_DIR/stt"

# ── desktop entry (app menu + autostart) ──
echo "[5/7] Creating app menu entry + autostart..."
cat > "$APPS_DIR/stt.desktop" << EOF
[Desktop Entry]
Type=Application
Name=STT Type
Comment=Speech-to-text keyboard — Alt+S to toggle recording
Exec=python3 $INSTALL_DIR/stt-app.py
Icon=audio-input-microphone
Categories=Utility;
Terminal=false
EOF
cp "$APPS_DIR/stt.desktop" "$AUTO_DIR/"

# ── keyboard shortcut ──
echo "[6/7] Registering Alt+S shortcut..."
case "$XDG_CURRENT_DESKTOP" in
    *[Cc]innamon*)
        LIST=$(dconf read /org/cinnamon/desktop/keybindings/custom-list 2>/dev/null || true)
        if ! echo "$LIST" | grep -q "custom4"; then
            if echo "$LIST" | grep -q "^@as"; then
                dconf write /org/cinnamon/desktop/keybindings/custom-list "['custom4']"
            else
                NEW=$(echo "$LIST" | sed "s/\]/', 'custom4']/")
                dconf write /org/cinnamon/desktop/keybindings/custom-list "$NEW"
            fi
        fi
        dconf write /org/cinnamon/desktop/keybindings/custom-keybindings/custom4/name "'STT Toggle'"
        dconf write /org/cinnamon/desktop/keybindings/custom-keybindings/custom4/command "'stt'"
        dconf write /org/cinnamon/desktop/keybindings/custom-keybindings/custom4/binding "['<Alt>s']"
        echo "  Cinnamon: Alt+S → stt"
        ;;
    *[Gg][Nn][Oo][Mm][Ee]*)
        # GNOME custom keybinding via gsettings
        KPATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/stt-toggle/"
        EXISTING=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null || true)
        if ! echo "$EXISTING" | grep -q "stt-toggle"; then
            if [ "$EXISTING" = "@as []" ]; then
                gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['${KPATH}']"
            else
                NEW=$(echo "$EXISTING" | sed "s|\]$|, '${KPATH}']|")
                gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$NEW"
            fi
            gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${KPATH}" name 'STT Toggle'
            gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${KPATH}" command 'stt'
            gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${KPATH}" binding '<Alt>s'
            echo "  GNOME: Alt+S → stt"
        else
            echo "  GNOME: Alt+S shortcut already exists"
        fi
        # tray extension check — GNOME 50 needs one
        if ! gnome-extensions list --enabled 2>/dev/null | grep -qiE 'appindicator|status-tray|tray-icons'; then
            echo ""
            echo "  ⚠  GNOME needs a tray icon extension to show the mic icon:"
            echo "     Install 'Status Tray' → https://extensions.gnome.org/extension/9164/"
            echo "     Or: sudo apt install gnome-shell-extension-manager"
            echo "     Then log out and back in."
        fi
        ;;
    *)
        echo "  Map Alt+S in your DE settings to run:  stt"
        ;;
esac

# ── launch ──
echo "[7/7] Starting STT Type..."
if [ -f /tmp/stt-app.pid ]; then
    kill "$(cat /tmp/stt-app.pid)" 2>/dev/null || true
    sleep 0.5
fi
python3 "$INSTALL_DIR/stt-app.py" &>/dev/null &

echo ""
echo "Installed! Microphone icon in tray."
echo ""
echo "  Alt+S        — toggle recording"
echo "  stt           — toggle from terminal"
echo "  Tray menu     — Start/Stop Recording, Set API Key..."
echo "  App menu     — search 'STT Type' in launcher"
if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
    echo ""
    echo "  Wayland: ydotool + wl-clipboard installed for typing."
    echo "  If typing doesn't work, LOG OUT AND BACK IN (input group)."
    echo "  Wrong microphone? Run 'pavucontrol' → Input Devices to switch."
fi
