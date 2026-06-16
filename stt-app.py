#!/usr/bin/env python3
# ponytail: tray app, click start/stop, SIGUSR1 toggle via Cinnamon shortcut
import subprocess
import threading
import time
import signal
import os
import json
import math
import struct
import sys
import wave
import cairo
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")
gi.require_version("Notify", "0.7")
from gi.repository import Gtk, GLib, Gdk
from gi.repository import AppIndicator3 as AppIndicator
from gi.repository import Notify

# ponytail: --dev uses separate temp files so prod + dev run side-by-side
DEV = "--dev" in sys.argv
SUFFIX = "-dev" if DEV else ""

API_URL = "https://api.lemonfox.ai/v1/audio/transcriptions"
AUDIO_FILE = f"/tmp/stt{SUFFIX}-recording.wav"
PID_FILE = f"/tmp/stt{SUFFIX}-app.pid"
BEEP_FILE = f"/tmp/stt{SUFFIX}-beep.wav"
ICON_IDLE = f"/tmp/stt{SUFFIX}-icon-idle.png"
ICON_WARN = f"/tmp/stt{SUFFIX}-icon-warn.png"
ICON_REC  = f"/tmp/stt{SUFFIX}-icon-rec.png"
KEY_FILE = os.path.expanduser("~/.config/stt/key")
LANG_FILE = os.path.expanduser("~/.config/stt/language")

recording = False
processing = False
arecord_proc = None
TYPETOOL = "wtype" if os.environ.get("XDG_SESSION_TYPE") == "wayland" else "xdotool"

def load_key():
    try:
        with open(KEY_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

API_KEY = load_key()

def load_language():
    try:
        with open(LANG_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return "english"

LANGUAGE = load_language()

with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))

def gen_beep():
    rate, freq, dur = 44100, 800, 0.1
    n = int(rate * dur)
    data = struct.pack("<" + "h" * n, *(
        int(32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)
    ))
    with wave.open(BEEP_FILE, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(data)

def gen_icons():
    specs = [("idle", (0.15, 0.55, 0.92)),   # blue — ready
             ("warn", (0.92, 0.55, 0.15)),   # orange — no key / error
             ("rec",  (0.92, 0.15, 0.12))]   # red — recording
    for name, color in specs:
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 22, 22)
        ctx = cairo.Context(s)
        ctx.arc(11, 11, 9, 0, 2 * math.pi)
        ctx.set_source_rgb(*color)
        ctx.fill()
        s.write_to_png(f"/tmp/stt{SUFFIX}-icon-{name}.png")

def ding():
    subprocess.Popen(["paplay", BEEP_FILE],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def snack(msg, icon="microphone"):
    n = Notify.Notification.new("STT" if not DEV else "STT DEV", msg, icon)
    n.set_timeout(2000)
    n.show()

def update_ui():
    dev = "DEV " if DEV else ""
    if processing:
        toggle_label.set_text("Processing...")
        toggle_item.set_sensitive(False)
        indicator.set_icon_full(ICON_WARN, "")
        indicator.set_title(dev + "Processing...")
    elif recording:
        toggle_label.set_text("Stop Recording")
        toggle_item.set_sensitive(True)
        indicator.set_icon_full(ICON_REC, "")
        indicator.set_title(dev + "Recording...")
    elif API_KEY:
        toggle_label.set_text("Start Recording")
        toggle_item.set_sensitive(True)
        indicator.set_icon_full(ICON_IDLE, "")
        indicator.set_title(dev + "Ready — click or Alt+S")
    else:
        toggle_label.set_text("Set API Key First")
        toggle_item.set_sensitive(False)
        indicator.set_icon_full(ICON_WARN, "")
        indicator.set_title(dev + "No API key — use Set API Key")

def start_record():
    global recording, arecord_proc
    recording = True
    update_ui()
    ding()
    arecord_proc = subprocess.Popen(
        ["arecord", "-f", "S16_LE", "-r", "16000", "-c", "1", AUDIO_FILE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    snack("Recording... speak now")

def stop_record():
    global recording, processing, arecord_proc
    recording = False
    update_ui()
    ding()
    if arecord_proc:
        arecord_proc.terminate()
        try:
            arecord_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            arecord_proc.kill()
        arecord_proc = None
    processing = True
    threading.Thread(target=transcribe, daemon=True).start()

def transcribe():
    global processing
    GLib.idle_add(lambda: snack("Transcribing..."))
    time.sleep(0.3)
    if not API_KEY:
        GLib.idle_add(lambda: snack("No API key set — use tray menu", "dialog-error"))
        processing = False
        GLib.idle_add(update_ui)
        return
    text = ""
    try:
        cmd = ["curl", "-s", API_URL,
               "-H", f"Authorization: Bearer {API_KEY}",
               "-F", f"file=@{AUDIO_FILE}",
               "-F", "response_format=json"]
        if LANGUAGE != "auto":
            cmd += ["-F", f"language={LANGUAGE}"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        text = json.loads(r.stdout).get("text", "")
    except Exception as e:
        GLib.idle_add(lambda: snack(f"API error: {e}", "dialog-error"))
    if text:
        # clipboard as safety net (works on X11 + Wayland)
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.set_text(text, -1)
        prim = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
        prim.set_text(text, -1)
        # type it
        if TYPETOOL == "wtype":
            subprocess.run(["wtype", text])
        else:
            subprocess.run(["xdotool", "type", "--", text])
        GLib.idle_add(lambda: snack("Typed!"))
    else:
        GLib.idle_add(lambda: snack("No speech detected", "dialog-warning"))
    processing = False
    GLib.idle_add(update_ui)

def on_toggle(_widget):
    global recording, processing
    if not API_KEY:
        snack("Set API key first — use tray menu", "dialog-error")
        return
    if processing:
        return
    if not recording:
        start_record()
    else:
        stop_record()

def on_signal(*_args):
    if not API_KEY:
        GLib.idle_add(lambda: snack("Set API key first — use tray menu", "dialog-error"))
        return True
    GLib.idle_add(on_toggle, None)
    return True

def quit_app(*_args):
    if recording and arecord_proc:
        arecord_proc.terminate()
    os.unlink(PID_FILE)
    os.unlink(BEEP_FILE)
    for f in (ICON_IDLE, ICON_WARN, ICON_REC):
        os.unlink(f)
    Notify.uninit()
    Gtk.main_quit()

def set_api_key(_widget):
    dialog = Gtk.Dialog(title="Set API Key", buttons=(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_OK, Gtk.ResponseType.OK))
    dialog.set_default_size(420, -1)
    box = dialog.get_content_area()
    box.set_spacing(6)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.add(Gtk.Label(label="Lemon Fox API Key (lemonfox.ai)"))
    entry = Gtk.Entry()
    entry.set_visibility(False)
    entry.set_placeholder_text("sk-...")
    current = load_key()
    if current:
        entry.set_text(current)
    box.add(entry)
    box.show_all()
    if dialog.run() == Gtk.ResponseType.OK:
        key = entry.get_text().strip()
        if key:
            os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
            with open(KEY_FILE, "w") as f:
                f.write(key)
            global API_KEY
            API_KEY = key
            GLib.idle_add(update_ui)
            snack("API key saved", "dialog-information")
    dialog.destroy()

LANGUAGES = [
    ("auto", "Auto-detect (recommended)"),
    ("english", "English"),
    ("chinese", "Chinese"),
    ("spanish", "Spanish"),
    ("french", "French"),
    ("german", "German"),
    ("portuguese", "Portuguese"),
    ("russian", "Russian"),
    ("japanese", "Japanese"),
    ("korean", "Korean"),
    ("arabic", "Arabic"),
    ("hindi", "Hindi"),
    ("italian", "Italian"),
    ("dutch", "Dutch"),
    ("turkish", "Turkish"),
    ("polish", "Polish"),
    ("swedish", "Swedish"),
    ("vietnamese", "Vietnamese"),
    ("thai", "Thai"),
    ("hebrew", "Hebrew"),
    ("greek", "Greek"),
]

def set_language(_widget):
    dialog = Gtk.Dialog(title="Set Language", buttons=(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_OK, Gtk.ResponseType.OK))
    dialog.set_default_size(320, -1)
    box = dialog.get_content_area()
    box.set_spacing(6)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.add(Gtk.Label(label="Transcription language:"))
    combo = Gtk.ComboBoxText()
    current = load_language()
    active_idx = 0
    for i, (code, name) in enumerate(LANGUAGES):
        combo.append(code, name)
        if code == current:
            active_idx = i
    combo.set_active(active_idx)
    box.add(combo)
    box.show_all()
    if dialog.run() == Gtk.ResponseType.OK:
        code = combo.get_active_id()
        if code:
            os.makedirs(os.path.dirname(LANG_FILE), exist_ok=True)
            with open(LANG_FILE, "w") as f:
                f.write(code)
            global LANGUAGE
            LANGUAGE = code
            snack(f"Language: {dict(LANGUAGES).get(code, code)}", "dialog-information")
    dialog.destroy()

Notify.init("stt-type")

indicator = AppIndicator.Indicator.new(
    "stt-type" if not DEV else "stt-type-dev", "audio-input-microphone",
    AppIndicator.IndicatorCategory.APPLICATION_STATUS)
indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

toggle_item = Gtk.MenuItem.new_with_label("Start Recording")
toggle_label = toggle_item.get_child()
toggle_item.connect("activate", on_toggle)

menu = Gtk.Menu()
menu.append(toggle_item)
menu.append(Gtk.SeparatorMenuItem())
mi_key = Gtk.MenuItem.new_with_label("Set API Key...")
mi_key.connect("activate", set_api_key)
menu.append(mi_key)
ml = Gtk.MenuItem.new_with_label("Set Language...")
ml.connect("activate", set_language)
menu.append(ml)
qi = Gtk.MenuItem.new_with_label("Quit")
qi.connect("activate", quit_app)
menu.append(qi)
menu.show_all()
indicator.set_menu(menu)

update_ui()

gen_icons()
gen_beep()

GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, on_signal)

Gtk.main()
