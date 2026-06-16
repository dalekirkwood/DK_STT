# STT Type — 🎤 → 💬

Hit a hotkey, speak, and your words get typed wherever your cursor is.

One tap of **Alt+S**. That's it. Works in any app — your editor, terminal,
browser, Slack, anywhere you can type.

---

## Quick Install (Ubuntu / Mint)

```bash
curl -sSL https://raw.githubusercontent.com/dalekirkwood/DK_STT/main/install.sh | bash
```

Or clone and run:

```bash
git clone https://github.com/dalekirkwood/DK_STT.git
cd DK_STT && ./install.sh
```

The installer:
- installs apt deps (GTK3, AppIndicator, xdotool/wtype, curl)
- copies the tray app to `~/.local/share/stt/`
- creates an app menu entry + autostart on login
- binds **Alt+S** as the toggle hotkey (Cinnamon/GNOME)
- prompts you for an API key

A microphone icon appears in your tray. You're ready.

## Get an API Key

STT Type talks to a Whisper API to transcribe your speech. You need a key from
**one** of these providers:

| Provider | Free tier | Get a key |
|----------|-----------|-----------|
| **Lemon Fox** | No card needed, generous limits | [lemonfox.ai/keys](https://lemonfox.ai/keys) |
| **Groq** | No card needed, 2h audio/day | [console.groq.com/keys](https://console.groq.com/keys) |
| **OpenAI** | Requires credit card | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| **Local Whisper** | Free, no account, works offline | In-app: tray → Provider → Setup Local Whisper... |
| **Custom URL** | Your own endpoint | Any OpenAI-compatible API |

The default is Lemon Fox. For **zero-cost, zero-network** transcription, set up
Local Whisper — it runs the model right on your machine. No API key, no
internet needed after initial download.

Keys for API providers live in `~/.config/stt/key.<provider>`. Local Whisper
needs no key.

## Usage

```
Alt+S         — start/stop recording (toggle)
```

Right-click the tray icon for:

| Menu item | What it does |
|-----------|-------------|
| Start/Stop Recording | Same as Alt+S |
| Provider | Switch between Lemon Fox, OpenAI, Groq, Local Whisper, Custom URL |
| Language | 100+ languages, auto-converts format per provider |
| Translate to English | After transcription, translate the result |
| Set Prompt | Words/phrases to bias the transcription |
| Set Dictionary | Custom vocabulary the AI might miss (jargon, names) |
| Show Notifications | Toggle desktop notifications on/off (errors always show) |
| Change Local Model | Pick model size (tiny/base/small/medium) for local Whisper |
| Set API Key | Add or change your key |

When you record:
1. A short beep plays — recording started
2. The tray icon turns **red**
3. Press Alt+S again to stop — icon turns **orange** (spinning) while
   transcribing
4. Text gets typed at your cursor. If typing fails, it copies to clipboard
   and notifies you.

## Features

- **Local Whisper** — run the model on your machine. Zero cost, zero network,
  fully private. Choose from tiny (~75MB), base (~145MB, default), small
  (~480MB), or medium (~1.5GB). One-click setup from the tray menu.
- **4 cloud providers** — Lemon Fox (cheapest), OpenAI (best accuracy), Groq
  (fastest), or any custom OpenAI-compatible endpoint
- **100+ languages** — auto-formats to full names or ISO codes depending on
  the provider
- **Translate mode** — transcribe in any language, get English output
- **Custom prompts** — bias recognition toward specific words or phrases
- **Custom dictionary** — persistent vocabulary list (jargon, names) prepended
  to every prompt automatically
- **Notification control** — toggle desktop notifications on/off; errors and
  warnings always show
- **Clipboard fallback** — if `xdotool`/`wtype` can't type (some apps block
  it), the text goes to your clipboard
- **X11 + Wayland** — detects your display server, uses the right typing tool
- **Dev mode** — `python3 stt-app.py --dev` runs a separate instance
  alongside production (different tray label, different PID file)

## How It Works

```
 ┌─────────┐     ┌────────┐     ┌────────────────┐     ┌───────────┐
 │ Alt+S   │ ──→ │ arecord│ ──→ │ Whisper API /  │ ──→ │ xdotool / │
 │ hotkey  │     │ 16kHz  │     │ Local Whisper   │     │ wtype     │
 └─────────┘     │ mono   │     └────────────────┘     └───────────┘
                 └────────┘           │
                  .wav file     text at cursor
```

- Audio: 16kHz mono WAV recorded directly by `arecord`
- Cloud transcription: `POST` to the Whisper-compatible endpoint, retried up to 4
  times with exponential backoff
- Local transcription: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  with CTranslate2 backend — 4x faster than openai-whisper on CPU, int8 quantized
- Typing: `xdotool type` on X11, `wtype` on Wayland, clipboard fallback if
  both fail
- Tray icon: colored mic — blue idle, red recording, orange spinner during
  API call

### Local Whisper Setup

1. Right-click tray → **Provider** → **Setup Local Whisper...**
2. Pick a model size (base is recommended for most users)
3. Click **Install** — pip installs [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
   and downloads the model (~145MB for base)
4. Provider auto-switches to Local Whisper. You're ready.

| Model | Size | Speed | Best for |
|-------|------|-------|----------|
| tiny | ~75MB | Instant | Quick notes in quiet rooms |
| base | ~145MB | Very fast | Daily use — good accuracy |
| small | ~480MB | Moderate | Noisy environments, accents |
| medium | ~1.5GB | Slow (GPU recommended) | Near-API quality |

Models stay cached in `~/.cache/huggingface/` — downloaded once, work offline forever.

## Config Files

Everything lives in `~/.config/stt/`. Nothing outside that directory.

| File | Purpose |
|------|---------|
| `provider` | Active provider name: `lemonfox`, `openai`, `groq`, `local`, or `custom` |
| `key.<provider>` | API key for that provider (e.g. `key.lemonfox`) |
| `language` | Transcription language, lowercase full name (e.g. `english`, `japanese`) |
| `translate` | `1` to translate output to English after transcription |
| `prompt` | Optional text to bias recognition (names, jargon, etc.) |
| `dictionary` | Custom vocabulary list, one word/term per line, prepended to every prompt |
| `notifications` | `1` show desktop notifications, `0` errors/warnings only |
| `local-model` | Model size for local Whisper: `tiny`, `base`, `small`, or `medium` |
| `custom-url` | Custom API endpoint URL (only used when provider is `custom`) |

## Development

```bash
# Run dev instance alongside production (separate PID, tray label, temp files)
python3 stt-app.py --dev

# Prod and dev can run at the same time
```

## License

**PolyForm Noncommercial License 1.0.0**

You can use, modify, and share this software for personal, educational, or
research purposes. **Commercial use is not permitted** without a separate
license. Contact the author if you'd like to use STT Type in a commercial
product.

See [LICENSE](LICENSE) for the full terms.
