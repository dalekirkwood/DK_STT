#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/stt"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
AUTO_DIR="$HOME/.config/autostart"

echo "=== STT Type Installer ==="

# ── deps ──
echo "[1/6] Installing apt dependencies..."
sudo apt install -y python3-gi gir1.2-appindicator3-0.1 gir1.2-notify-0.7 xdotool curl
if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
    sudo apt install -y wtype 2>/dev/null || true
fi

# ── dirs ──
echo "[2/6] Creating directories..."
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APPS_DIR" "$AUTO_DIR"

# ── copy ──
echo "[3/6] Installing files..."
cp "$SCRIPT_DIR/stt-app.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/stt" "$BIN_DIR/"
chmod +x "$INSTALL_DIR/stt-app.py" "$BIN_DIR/stt"

# ── desktop entry (app menu + autostart) ──
echo "[4/6] Creating app menu entry + autostart..."
cat > "$APPS_DIR/stt.desktop" << EOF
[Desktop Entry]
Type=Application
Name=STT Type
Comment=Speech-to-text keyboard — Ctrl+Alt+V to toggle recording
Exec=python3 $INSTALL_DIR/stt-app.py
Icon=audio-input-microphone
Categories=Utility;
Terminal=false
EOF
cp "$APPS_DIR/stt.desktop" "$AUTO_DIR/"

# ── keyboard shortcut ──
echo "[5/6] Registering Ctrl+Alt+V shortcut..."
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
        dconf write /org/cinnamon/desktop/keybindings/custom-keybindings/custom4/binding "['<Control><Alt>V']"
        echo "  Cinnamon: Ctrl+Alt+V → stt"
        ;;
    *[Gg][Nn][Oo][Mm][Ee]*)
        echo "  GNOME: open Settings → Keyboard → Custom Shortcuts:"
        echo "    Name: STT Toggle  |  Command: stt  |  Key: Ctrl+Alt+V"
        ;;
    *)
        echo "  Map Ctrl+Alt+V in your DE settings to run:  stt"
        ;;
esac

# ── launch ──
echo "[6/6] Starting STT Type..."
if [ -f /tmp/stt-app.pid ]; then
    kill "$(cat /tmp/stt-app.pid)" 2>/dev/null || true
    sleep 0.5
fi
python3 "$INSTALL_DIR/stt-app.py" &>/dev/null &

echo ""
echo "Installed! Microphone icon in tray."
echo ""
echo "  Ctrl+Alt+V  — toggle recording"
echo "  stt          — toggle from terminal"
echo "  Tray menu    — click Start/Stop Recording"
