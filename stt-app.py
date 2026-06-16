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
import wave
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")
gi.require_version("Notify", "0.7")
from gi.repository import Gtk, GLib, Gdk
from gi.repository import AppIndicator3 as AppIndicator
from gi.repository import Notify

API_KEY = "iPMGv6F5sMwEOMjqGGtKQnMPjCA7EjYc"
API_URL = "https://api.lemonfox.ai/v1/audio/transcriptions"
AUDIO_FILE = "/tmp/stt-recording.wav"
PID_FILE = "/tmp/stt-app.pid"
BEEP_FILE = "/tmp/stt-beep.wav"

recording = False
processing = False
arecord_proc = None
TYPETOOL = "wtype" if os.environ.get("XDG_SESSION_TYPE") == "wayland" else "xdotool"

with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))
gen_beep()

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

def ding():
    subprocess.Popen(["paplay", BEEP_FILE],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def snack(msg, icon="microphone"):
    n = Notify.Notification.new("STT", msg, icon)
    n.set_timeout(2000)
    n.show()

def update_ui():
    if processing:
        toggle_label.set_text("Processing...")
        toggle_item.set_sensitive(False)
        indicator.set_title("Processing...")
    elif recording:
        toggle_label.set_text("Stop Recording")
        toggle_item.set_sensitive(True)
        indicator.set_title("Recording...")
    else:
        toggle_label.set_text("Start Recording")
        toggle_item.set_sensitive(True)
        indicator.set_title("Idle — click or Ctrl+Alt+V")

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
    text = ""
    try:
        r = subprocess.run(
            ["curl", "-s", API_URL,
             "-H", f"Authorization: Bearer {API_KEY}",
             "-F", f"file=@{AUDIO_FILE}",
             "-F", "language=english",
             "-F", "response_format=json"],
            capture_output=True, text=True, timeout=30)
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
    if processing:
        return
    if not recording:
        start_record()
    else:
        stop_record()

def on_signal(*_args):
    GLib.idle_add(on_toggle, None)
    return True

def quit_app(*_args):
    if recording and arecord_proc:
        arecord_proc.terminate()
    os.unlink(PID_FILE)
    os.unlink(BEEP_FILE)
    Notify.uninit()
    Gtk.main_quit()

Notify.init("stt-type")

indicator = AppIndicator.Indicator.new(
    "stt-type", "audio-input-microphone",
    AppIndicator.IndicatorCategory.APPLICATION_STATUS)
indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

toggle_item = Gtk.MenuItem.new_with_label("Start Recording")
toggle_label = toggle_item.get_child()
toggle_item.connect("activate", on_toggle)

menu = Gtk.Menu()
menu.append(toggle_item)
menu.append(Gtk.SeparatorMenuItem())
qi = Gtk.MenuItem.new_with_label("Quit")
qi.connect("activate", quit_app)
menu.append(qi)
menu.show_all()
indicator.set_menu(menu)

update_ui()

GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, on_signal)

Gtk.main()
