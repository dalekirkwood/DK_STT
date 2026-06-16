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

try:
    from faster_whisper import WhisperModel
    LOCAL_AVAILABLE = True
except ImportError:
    LOCAL_AVAILABLE = False

# ponytail: --dev uses separate temp files so prod + dev run side-by-side
DEV = "--dev" in sys.argv
SUFFIX = "-dev" if DEV else ""

PROVIDERS = [
    ("lemonfox", "Lemon Fox (cheapest)"),
    ("openai",   "OpenAI Whisper (best accuracy)"),
    ("groq",     "Groq (fastest)"),
    ("custom",   "Custom URL..."),
]
PROVIDERS.append(("local", "Local Whisper (offline)"))
PROVIDER_URLS = {
    "lemonfox": "https://api.lemonfox.ai/v1/audio/transcriptions",
    "openai":   "https://api.openai.com/v1/audio/transcriptions",
    "groq":     "https://api.groq.com/openai/v1/audio/transcriptions",
    "custom":   "",  # stored in ~/.config/stt/custom-url
}
PROVIDER_MODEL = {
    "groq":     "whisper-large-v3-turbo",
}
# Groq & OpenAI need ISO-639-1 codes; Lemon Fox uses full names
LANGUAGE_ISO = {
    "english": "en", "chinese": "zh", "spanish": "es", "french": "fr",
    "german": "de", "portuguese": "pt", "russian": "ru", "japanese": "ja",
    "korean": "ko", "arabic": "ar", "hindi": "hi", "italian": "it",
    "dutch": "nl", "turkish": "tr", "polish": "pl", "swedish": "sv",
    "vietnamese": "vi", "thai": "th", "hebrew": "he", "greek": "el",
    "catalan": "ca", "indonesian": "id", "finnish": "fi", "ukrainian": "uk",
    "malay": "ms", "czech": "cs", "romanian": "ro", "danish": "da",
    "hungarian": "hu", "tamil": "ta", "norwegian": "no", "urdu": "ur",
    "croatian": "hr", "bulgarian": "bg", "lithuanian": "lt", "latin": "la",
    "maori": "mi", "malayalam": "ml", "welsh": "cy", "slovak": "sk",
    "telugu": "te", "persian": "fa", "latvian": "lv", "bengali": "bn",
    "serbian": "sr", "azerbaijani": "az", "slovenian": "sl", "kannada": "kn",
    "estonian": "et", "macedonian": "mk", "breton": "br", "basque": "eu",
    "icelandic": "is", "armenian": "hy", "nepali": "ne", "mongolian": "mn",
    "bosnian": "bs", "kazakh": "kk", "albanian": "sq", "swahili": "sw",
    "galician": "gl", "marathi": "mr", "punjabi": "pa", "sinhala": "si",
    "khmer": "km", "shona": "sn", "yoruba": "yo", "somali": "so",
    "afrikaans": "af", "occitan": "oc", "georgian": "ka", "belarusian": "be",
    "tajik": "tg", "sindhi": "sd", "gujarati": "gu", "amharic": "am",
    "yiddish": "yi", "lao": "lo", "uzbek": "uz", "faroese": "fo",
    "haitian creole": "ht", "pashto": "ps", "turkmen": "tk", "nynorsk": "nn",
    "maltese": "mt", "sanskrit": "sa", "luxembourgish": "lb", "myanmar": "my",
    "tibetan": "bo", "tagalog": "tl", "malagasy": "mg", "assamese": "as",
    "tatar": "tt", "hawaiian": "haw", "lingala": "ln", "hausa": "ha",
    "bashkir": "ba", "javanese": "jv", "sundanese": "su", "cantonese": "yue",
    "burmese": "my", "valencian": "ca", "flemish": "nl",
}

AUDIO_FILE = f"/tmp/stt{SUFFIX}-recording.wav"
PID_FILE = f"/tmp/stt{SUFFIX}-app.pid"
BEEP_FILE = f"/tmp/stt{SUFFIX}-beep.wav"
ICON_IDLE = f"/tmp/stt{SUFFIX}-icon-idle.png"
ICON_WARN = f"/tmp/stt{SUFFIX}-icon-warn.png"
ICON_REC  = f"/tmp/stt{SUFFIX}-icon-rec.png"
PROVIDER_FILE = os.path.expanduser("~/.config/stt/provider")
LANG_FILE = os.path.expanduser("~/.config/stt/language")
TRANS_FILE = os.path.expanduser("~/.config/stt/translate")
PROMPT_FILE = os.path.expanduser("~/.config/stt/prompt")
DICT_FILE = os.path.expanduser("~/.config/stt/dictionary")
NOTIF_FILE = os.path.expanduser("~/.config/stt/notifications")
LOCAL_MODEL_FILE = os.path.expanduser("~/.config/stt/local-model")
CUSTOM_URL_FILE = os.path.expanduser("~/.config/stt/custom-url")
OLD_KEY_FILE = os.path.expanduser("~/.config/stt/key")

# ── provider + key ──
def _key_path(provider=None):
    if provider is None:
        provider = PROVIDER
    return os.path.expanduser(f"~/.config/stt/key.{provider}")

def load_provider():
    try:
        return open(PROVIDER_FILE).read().strip()
    except FileNotFoundError:
        return "lemonfox"

PROVIDER = load_provider()

# one-time migration: old ~/.config/stt/key → key.lemonfox
if os.path.exists(OLD_KEY_FILE) and not os.path.exists(_key_path("lemonfox")):
    os.makedirs(os.path.dirname(OLD_KEY_FILE), exist_ok=True)
    import shutil
    shutil.copy(OLD_KEY_FILE, _key_path("lemonfox"))

def load_key():
    try:
        return open(_key_path()).read().strip()
    except FileNotFoundError:
        return ""

API_KEY = load_key()

def get_api_url():
    if PROVIDER == "custom":
        try:
            return open(CUSTOM_URL_FILE).read().strip()
        except FileNotFoundError:
            return ""
    return PROVIDER_URLS.get(PROVIDER, PROVIDER_URLS["lemonfox"])

API_URL = get_api_url()

recording = False
processing = False
arecord_proc = None
spin_id = 0
spin_frame = 0
SPIN_FRAMES = 8
ICON_SPIN = [f"/tmp/stt{SUFFIX}-spin-{i}.png" for i in range(SPIN_FRAMES)]
TYPETOOL = "wtype" if os.environ.get("XDG_SESSION_TYPE") == "wayland" else "xdotool"

def load_language():
    try:
        with open(LANG_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return "english"

LANGUAGE = load_language()

def load_translate():
    try:
        return open(TRANS_FILE).read().strip() == "1"
    except FileNotFoundError:
        return False

TRANSLATE = load_translate()

def load_prompt():
    try:
        with open(PROMPT_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

PROMPT = load_prompt()

def load_dictionary():
    try:
        with open(DICT_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

DICTIONARY = load_dictionary()

def load_notifications():
    try:
        return open(NOTIF_FILE).read().strip() == "1"
    except FileNotFoundError:
        return True  # default: show notifications

NOTIFICATIONS = load_notifications()

def load_local_model_name():
    try:
        return open(LOCAL_MODEL_FILE).read().strip()
    except FileNotFoundError:
        return "base"

_local_whisper_model = None
_local_whisper_size = None

def get_local_model():
    global _local_whisper_model, _local_whisper_size
    model_size = load_local_model_name()
    if _local_whisper_model is not None and _local_whisper_size == model_size:
        return _local_whisper_model
    if _local_whisper_model is not None:
        del _local_whisper_model
    _local_whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
    _local_whisper_size = model_size
    return _local_whisper_model

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
    pix = Gtk.IconTheme.get_default().load_icon(
        "audio-input-microphone", 22, Gtk.IconLookupFlags.FORCE_SIZE)
    specs = [("idle", (0.15, 0.55, 0.92)),   # blue — ready
             ("warn", (0.92, 0.55, 0.15)),   # orange — no key / error
             ("rec",  (0.92, 0.15, 0.12))]   # red — recording
    for name, color in specs:
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 22, 22)
        ctx = cairo.Context(s)
        Gdk.cairo_set_source_pixbuf(ctx, pix, 0, 0)
        ctx.paint()
        ctx.set_source_rgb(*color)
        ctx.set_operator(cairo.Operator.ATOP)
        ctx.paint()
        s.write_to_png(f"/tmp/stt{SUFFIX}-icon-{name}.png")
    # spinner frames: orange mic + rotating white arc
    for i in range(SPIN_FRAMES):
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 22, 22)
        ctx = cairo.Context(s)
        Gdk.cairo_set_source_pixbuf(ctx, pix, 0, 0)
        ctx.paint()
        ctx.set_source_rgb(0.92, 0.55, 0.15)
        ctx.set_operator(cairo.Operator.ATOP)
        ctx.paint()
        ctx.set_operator(cairo.Operator.OVER)
        ctx.set_source_rgba(1, 1, 1, 0.9)
        ctx.set_line_width(1.8)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        start = (i * 2 * math.pi / SPIN_FRAMES) - math.pi / 2
        ctx.arc(11, 11, 6.5, start, start + math.pi / 1.5)
        ctx.stroke()
        s.write_to_png(ICON_SPIN[i])

def ding():
    subprocess.Popen(["paplay", BEEP_FILE],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def snack(msg, icon="microphone"):
    if not NOTIFICATIONS and icon not in ("dialog-error", "dialog-warning"):
        return
    n = Notify.Notification.new("STT" if not DEV else "STT DEV", msg, icon)
    n.set_timeout(2000)
    n.show()

def spin_tick():
    global spin_frame
    spin_frame = (spin_frame + 1) % SPIN_FRAMES
    indicator.set_icon_full(ICON_SPIN[spin_frame], "")
    return True

def update_ui():
    global spin_id
    dev = "DEV " if DEV else ""
    if processing:
        toggle_label.set_text("Processing...")
        toggle_item.set_sensitive(False)
        if not spin_id:
            spin_id = GLib.timeout_add(125, spin_tick)
        indicator.set_title(dev + "Processing...")
    else:
        if spin_id:
            GLib.source_remove(spin_id)
            spin_id = 0
        if recording:
            toggle_label.set_text("Stop Recording")
            toggle_item.set_sensitive(True)
            indicator.set_icon_full(ICON_REC, "")
            indicator.set_title(dev + "Recording...")
        elif API_KEY or PROVIDER == "local":
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
    ding()
    if arecord_proc:
        arecord_proc.terminate()
        try:
            arecord_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            arecord_proc.kill()
        arecord_proc = None
    processing = True
    update_ui()
    threading.Thread(target=transcribe, daemon=True).start()

def _transcribe_local():
    global processing
    model = get_local_model()
    language_code = LANGUAGE_ISO.get(LANGUAGE) if LANGUAGE != "auto" else None
    prompt_text = DICTIONARY
    if DICTIONARY and PROMPT:
        prompt_text += "\n" + PROMPT
    elif PROMPT:
        prompt_text = PROMPT
    try:
        segments, info = model.transcribe(
            AUDIO_FILE,
            language=language_code,
            initial_prompt=prompt_text or None,
            beam_size=5,
        )
        text = " ".join(s.strip() for s in (seg.text for seg in segments)).strip()
    except Exception as e:
        GLib.idle_add(lambda: snack(f"Local Whisper: {e}", "dialog-error"))
        processing = False
        GLib.idle_add(update_ui)
        return
    if text:
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.set_text(text, -1)
        prim = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
        prim.set_text(text, -1)
        if TYPETOOL == "wtype":
            subprocess.run(["wtype", text])
        else:
            subprocess.run(["xdotool", "type", "--", text])
        GLib.idle_add(lambda: snack("Typed!"))
    else:
        GLib.idle_add(lambda: snack("No speech detected", "dialog-warning"))
    processing = False
    GLib.idle_add(update_ui)

def transcribe():
    global processing
    GLib.idle_add(lambda: snack("Transcribing..."))
    if PROVIDER == "local":
        _transcribe_local()
        return
    if not API_KEY:
        GLib.idle_add(lambda: snack("No API key set — use tray menu", "dialog-error"))
        processing = False
        GLib.idle_add(update_ui)
        return
    MAX_RETRIES = 4
    RETRY_DELAY = 6
    text = ""
    cmd = ["curl", "-s", API_URL,
           "-H", f"Authorization: Bearer {API_KEY}",
           "-F", f"file=@{AUDIO_FILE}",
           "-F", "response_format=json"]
    if LANGUAGE != "auto":
        code = LANGUAGE_ISO.get(LANGUAGE, "") if PROVIDER in ("groq", "openai") else LANGUAGE
        if code:
            cmd += ["-F", f"language={code}"]
    if TRANSLATE and PROVIDER != "groq":
        cmd += ["-F", "translate=true"]
    # ponytail: dictionary words + prompt concatenated into one prompt param
    prompt_text = DICTIONARY
    if DICTIONARY and PROMPT:
        prompt_text += "\n" + PROMPT
    elif PROMPT:
        prompt_text = PROMPT
    if prompt_text:
        cmd += ["-F", f"prompt={prompt_text}"]
    if PROVIDER in PROVIDER_MODEL:
        cmd += ["-F", f"model={PROVIDER_MODEL[PROVIDER]}"]
    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            GLib.idle_add(lambda a=attempt: snack(
                f"Retrying ({a}/{MAX_RETRIES})...", "emblem-synchronizing"))
            time.sleep(RETRY_DELAY)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            resp = json.loads(r.stdout)
            if "error" in resp:
                msg = resp["error"].get("message", str(resp["error"]))
                GLib.idle_add(lambda m=msg: snack(f"API error: {m}", "dialog-error"))
                break
            text = resp.get("text", "").strip()
            if text:
                break
            break  # empty text — silent audio, don't retry
        except Exception:
            if attempt == MAX_RETRIES:
                GLib.idle_add(lambda: snack(
                    f"Failed after {MAX_RETRIES} attempts — check connection", "dialog-error"))
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
    if not API_KEY and PROVIDER != "local":
        snack("Set API key first — use tray menu", "dialog-error")
        return
    if processing:
        return
    if not recording:
        start_record()
    else:
        stop_record()

def on_signal(*_args):
    if not API_KEY and PROVIDER != "local":
        GLib.idle_add(lambda: snack("Set API key first — use tray menu", "dialog-error"))
        return True
    GLib.idle_add(on_toggle, None)
    return True

def quit_app(*_args):
    global spin_id
    if spin_id:
        GLib.source_remove(spin_id)
        spin_id = 0
    if recording and arecord_proc:
        arecord_proc.terminate()
    os.unlink(PID_FILE)
    os.unlink(BEEP_FILE)
    for f in (ICON_IDLE, ICON_WARN, ICON_REC):
        os.unlink(f)
    for f in ICON_SPIN:
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
    box.add(Gtk.Label(label=f"API Key for {dict(PROVIDERS).get(PROVIDER, PROVIDER)}:"))
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
            os.makedirs(os.path.dirname(_key_path()), exist_ok=True)
            with open(_key_path(), "w") as f:
                f.write(key)
            global API_KEY
            API_KEY = key
            GLib.idle_add(update_ui)
            snack("API key saved", "dialog-information")
    dialog.destroy()

def set_prompt(_widget):
    dialog = Gtk.Dialog(title="Set Prompt", buttons=(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_OK, Gtk.ResponseType.OK))
    dialog.set_default_size(420, 160)
    box = dialog.get_content_area()
    box.set_spacing(6)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.add(Gtk.Label(label="Prompt text (words/names/punctuation to guide transcription):"))
    scroll = Gtk.ScrolledWindow()
    scroll.set_min_content_height(80)
    tv = Gtk.TextView()
    tv.set_wrap_mode(Gtk.WrapMode.WORD)
    tv.get_buffer().set_text(load_prompt())
    scroll.add(tv)
    box.add(scroll)
    box.show_all()
    if dialog.run() == Gtk.ResponseType.OK:
        buf = tv.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()
        os.makedirs(os.path.dirname(PROMPT_FILE), exist_ok=True)
        with open(PROMPT_FILE, "w") as f:
            f.write(text)
        global PROMPT
        PROMPT = text
        snack("Prompt saved" if text else "Prompt cleared", "dialog-information")
    dialog.destroy()

def set_dictionary(_widget):
    dialog = Gtk.Dialog(title="Set Dictionary", buttons=(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_OK, Gtk.ResponseType.OK))
    dialog.set_default_size(420, 200)
    box = dialog.get_content_area()
    box.set_spacing(6)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.add(Gtk.Label(label="Custom vocabulary — words the AI might miss (one per line):"))
    scroll = Gtk.ScrolledWindow()
    scroll.set_min_content_height(80)
    tv = Gtk.TextView()
    tv.set_wrap_mode(Gtk.WrapMode.WORD)
    tv.get_buffer().set_text(load_dictionary())
    scroll.add(tv)
    box.add(scroll)
    warn = Gtk.Label(label="Note: Groq limits prompts to 224 tokens (~160 words). Dictionary + prompt share this limit.")
    warn.set_line_wrap(True)
    box.add(warn)
    box.show_all()
    if dialog.run() == Gtk.ResponseType.OK:
        buf = tv.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()
        os.makedirs(os.path.dirname(DICT_FILE), exist_ok=True)
        with open(DICT_FILE, "w") as f:
            f.write(text)
        global DICTIONARY
        DICTIONARY = text
        snack("Dictionary saved" if text else "Dictionary cleared", "dialog-information")
    dialog.destroy()

def toggle_translate(_widget):
    global TRANSLATE
    TRANSLATE = not TRANSLATE
    os.makedirs(os.path.dirname(TRANS_FILE), exist_ok=True)
    with open(TRANS_FILE, "w") as f:
        f.write("1" if TRANSLATE else "0")
    snack(f"Translate to English: {'ON' if TRANSLATE else 'OFF'}", "dialog-information")

def toggle_notifications(_widget):
    global NOTIFICATIONS
    NOTIFICATIONS = not NOTIFICATIONS
    os.makedirs(os.path.dirname(NOTIF_FILE), exist_ok=True)
    with open(NOTIF_FILE, "w") as f:
        f.write("1" if NOTIFICATIONS else "0")

# ponytail: local whisper models — only size label matters, faster-whisper handles the rest
LOCAL_MODELS = [
    ("tiny",   "tiny (~75MB, fastest)"),
    ("base",   "base (~145MB, good)"),
    ("small",  "small (~480MB, better)"),
    ("medium", "medium (~1.5GB, best)"),
]

def setup_local_whisper(_widget=None):
    dialog = Gtk.Dialog(title="Setup Local Whisper")
    dialog.add_button("Install", Gtk.ResponseType.OK)
    dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
    dialog.set_default_size(400, -1)
    box = dialog.get_content_area()
    box.set_spacing(6)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.add(Gtk.Label(label="Install faster-whisper for private, offline transcription."))
    box.add(Gtk.Label(label="Model size:"))
    combo = Gtk.ComboBoxText()
    for code, name in LOCAL_MODELS:
        combo.append(code, name)
    combo.set_active(1)
    box.add(combo)
    note = Gtk.Label(label="Downloads model ~75MB-1.5GB. Requires internet only for setup.")
    note.set_line_wrap(True)
    box.add(note)
    box.show_all()
    if dialog.run() == Gtk.ResponseType.OK:
        model_size = combo.get_active_id()
        dialog.destroy()
        GLib.idle_add(lambda: snack("Installing faster-whisper... (may take a minute)", "emblem-synchronizing"))
        def _install():
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--user", "--break-system-packages",
                     "faster-whisper"],
                    capture_output=True, text=True, timeout=180)
                if r.returncode != 0:
                    err = r.stderr.strip().split("\n")[-1] if r.stderr.strip() else str(r.returncode)
                    GLib.idle_add(lambda e=err: snack(f"pip install failed: {e}", "dialog-error"))
                    return
                os.makedirs(os.path.dirname(LOCAL_MODEL_FILE), exist_ok=True)
                with open(LOCAL_MODEL_FILE, "w") as f:
                    f.write(model_size)
                global LOCAL_AVAILABLE
                try:
                    from faster_whisper import WhisperModel
                    LOCAL_AVAILABLE = True
                except ImportError:
                    GLib.idle_add(lambda: snack("Import failed after install. Restarting...", "dialog-information"))
                    time.sleep(1)
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                    return
                _ = WhisperModel(model_size, device="cpu", compute_type="int8")
                GLib.idle_add(refresh_provider_menu)
                GLib.idle_add(lambda: local_model_item.set_visible(True))
                GLib.idle_add(lambda: snack("Local Whisper ready!", "dialog-information"))
                GLib.idle_add(lambda: switch_provider("local"))
            except Exception as e:
                GLib.idle_add(lambda: snack(f"Install failed: {e}", "dialog-error"))
        threading.Thread(target=_install, daemon=True).start()
    else:
        dialog.destroy()

def set_local_model(_widget=None):
    dialog = Gtk.Dialog(title="Change Local Model")
    dialog.add_button("Switch", Gtk.ResponseType.OK)
    dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
    dialog.set_default_size(350, -1)
    box = dialog.get_content_area()
    box.set_spacing(6)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.add(Gtk.Label(label="Select model (downloads on first use):"))
    combo = Gtk.ComboBoxText()
    current = load_local_model_name()
    active_idx = 0
    for i, (code, name) in enumerate(LOCAL_MODELS):
        combo.append(code, name)
        if code == current:
            active_idx = i
    combo.set_active(active_idx)
    box.add(combo)
    box.show_all()
    if dialog.run() == Gtk.ResponseType.OK:
        model_size = combo.get_active_id()
        if model_size and model_size != current:
            os.makedirs(os.path.dirname(LOCAL_MODEL_FILE), exist_ok=True)
            with open(LOCAL_MODEL_FILE, "w") as f:
                f.write(model_size)
            global _local_whisper_model, _local_whisper_size
            _local_whisper_model = None
            _local_whisper_size = None
            snack(f"Switched to {model_size} model. Download on next transcription.", "dialog-information")
    dialog.destroy()

def provider_has_key(provider):
    if provider == "local":
        return LOCAL_AVAILABLE
    return os.path.exists(_key_path(provider))

def _custom_url_ready():
    try:
        return bool(open(CUSTOM_URL_FILE).read().strip())
    except FileNotFoundError:
        return False

def switch_provider(provider, custom_url=None):
    global PROVIDER, API_KEY, API_URL
    if provider == "custom" and not _custom_url_ready() and not custom_url:
        prompt_custom_url(provider)
        return
    PROVIDER = provider
    os.makedirs(os.path.dirname(PROVIDER_FILE), exist_ok=True)
    with open(PROVIDER_FILE, "w") as f:
        f.write(provider)
    if custom_url:
        os.makedirs(os.path.dirname(CUSTOM_URL_FILE), exist_ok=True)
        with open(CUSTOM_URL_FILE, "w") as f:
            f.write(custom_url)
    if provider != "local":
        API_KEY = load_key()
        API_URL = get_api_url()
    GLib.idle_add(update_ui)
    name = dict(PROVIDERS).get(provider, provider)
    snack(f"Switched to {name}", "dialog-information")

def prompt_custom_url(for_provider="custom"):
    dialog = Gtk.Dialog(title="Custom Provider URL", buttons=(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_OK, Gtk.ResponseType.OK))
    dialog.set_default_size(420, -1)
    box = dialog.get_content_area()
    box.set_spacing(6)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.add(Gtk.Label(label="API endpoint (OpenAI-compatible):"))
    entry = Gtk.Entry()
    entry.set_placeholder_text("https://api.example.com/v1/audio/transcriptions")
    if _custom_url_ready():
        entry.set_text(open(CUSTOM_URL_FILE).read().strip())
    box.add(entry)
    box.show_all()
    if dialog.run() == Gtk.ResponseType.OK:
        url = entry.get_text().strip()
        if url:
            switch_provider(for_provider, custom_url=url)
    else:
        # cancelled — reset radio to previous provider
        GLib.idle_add(refresh_provider_menu)
    dialog.destroy()

_refreshing = False

def refresh_provider_menu():
    global _refreshing
    _refreshing = True
    for code, item in provider_items.items():
        name = dict(PROVIDERS).get(code, code)
        label = name
        if code == "local" and not LOCAL_AVAILABLE:
            label = "Setup Local Whisper..."
        elif provider_has_key(code):
            label += " ✓"
        item.set_label(label)
        item.set_active(code == PROVIDER)
    local_model_item.set_visible(LOCAL_AVAILABLE)
    _refreshing = False

def on_provider_activate(item, provider):
    if _refreshing or not item.get_active():
        return
    if provider == PROVIDER:
        return
    if provider == "local" and not LOCAL_AVAILABLE:
        GLib.idle_add(setup_local_whisper)
        GLib.idle_add(refresh_provider_menu)
        return
    switch_provider(provider)

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
    ("catalan", "Catalan"),
    ("indonesian", "Indonesian"),
    ("finnish", "Finnish"),
    ("ukrainian", "Ukrainian"),
    ("malay", "Malay"),
    ("czech", "Czech"),
    ("romanian", "Romanian"),
    ("danish", "Danish"),
    ("hungarian", "Hungarian"),
    ("tamil", "Tamil"),
    ("norwegian", "Norwegian"),
    ("urdu", "Urdu"),
    ("croatian", "Croatian"),
    ("bulgarian", "Bulgarian"),
    ("lithuanian", "Lithuanian"),
    ("latin", "Latin"),
    ("maori", "Maori"),
    ("malayalam", "Malayalam"),
    ("welsh", "Welsh"),
    ("slovak", "Slovak"),
    ("telugu", "Telugu"),
    ("persian", "Persian"),
    ("latvian", "Latvian"),
    ("bengali", "Bengali"),
    ("serbian", "Serbian"),
    ("azerbaijani", "Azerbaijani"),
    ("slovenian", "Slovenian"),
    ("kannada", "Kannada"),
    ("estonian", "Estonian"),
    ("macedonian", "Macedonian"),
    ("breton", "Breton"),
    ("basque", "Basque"),
    ("icelandic", "Icelandic"),
    ("armenian", "Armenian"),
    ("nepali", "Nepali"),
    ("mongolian", "Mongolian"),
    ("bosnian", "Bosnian"),
    ("kazakh", "Kazakh"),
    ("albanian", "Albanian"),
    ("swahili", "Swahili"),
    ("galician", "Galician"),
    ("marathi", "Marathi"),
    ("punjabi", "Punjabi"),
    ("sinhala", "Sinhala"),
    ("khmer", "Khmer"),
    ("shona", "Shona"),
    ("yoruba", "Yoruba"),
    ("somali", "Somali"),
    ("afrikaans", "Afrikaans"),
    ("occitan", "Occitan"),
    ("georgian", "Georgian"),
    ("belarusian", "Belarusian"),
    ("tajik", "Tajik"),
    ("sindhi", "Sindhi"),
    ("gujarati", "Gujarati"),
    ("amharic", "Amharic"),
    ("yiddish", "Yiddish"),
    ("lao", "Lao"),
    ("uzbek", "Uzbek"),
    ("faroese", "Faroese"),
    ("haitian creole", "Haitian Creole"),
    ("pashto", "Pashto"),
    ("turkmen", "Turkmen"),
    ("nynorsk", "Nynorsk"),
    ("maltese", "Maltese"),
    ("sanskrit", "Sanskrit"),
    ("luxembourgish", "Luxembourgish"),
    ("myanmar", "Myanmar"),
    ("tibetan", "Tibetan"),
    ("tagalog", "Tagalog"),
    ("malagasy", "Malagasy"),
    ("assamese", "Assamese"),
    ("tatar", "Tatar"),
    ("hawaiian", "Hawaiian"),
    ("lingala", "Lingala"),
    ("hausa", "Hausa"),
    ("bashkir", "Bashkir"),
    ("javanese", "Javanese"),
    ("sundanese", "Sundanese"),
    ("cantonese", "Cantonese"),
    ("burmese", "Burmese"),
    ("valencian", "Valencian"),
    ("flemish", "Flemish"),
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

provider_items = {}
providers_menu = Gtk.Menu()
group = None
for code, name in PROVIDERS:
    label = name
    if provider_has_key(code):
        label += " ✓"
    item = Gtk.RadioMenuItem.new_with_label(group, label)
    group = item.get_group()
    item.set_active(code == PROVIDER)
    item.connect("toggled", on_provider_activate, code)
    providers_menu.append(item)
    provider_items[code] = item
providers_menu.show_all()
provider_menu_item = Gtk.MenuItem.new_with_label("Provider")
provider_menu_item.set_submenu(providers_menu)
menu.append(provider_menu_item)

mi_key = Gtk.MenuItem.new_with_label("Set API Key...")
mi_key.connect("activate", set_api_key)
menu.append(mi_key)
ml = Gtk.MenuItem.new_with_label("Set Language...")
ml.connect("activate", set_language)
menu.append(ml)
mp = Gtk.MenuItem.new_with_label("Set Prompt...")
mp.connect("activate", set_prompt)
menu.append(mp)
md = Gtk.MenuItem.new_with_label("Set Dictionary...")
md.connect("activate", set_dictionary)
menu.append(md)
mt = Gtk.CheckMenuItem.new_with_label("Translate to English")
mt.set_active(TRANSLATE)
mt.connect("toggled", toggle_translate)
menu.append(mt)
mn = Gtk.CheckMenuItem.new_with_label("Show Notifications")
mn.set_active(NOTIFICATIONS)
mn.connect("toggled", toggle_notifications)
menu.append(mn)
local_model_item = Gtk.MenuItem.new_with_label("Change Local Model...")
local_model_item.connect("activate", set_local_model)
local_model_item.set_visible(LOCAL_AVAILABLE)
menu.append(local_model_item)
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
