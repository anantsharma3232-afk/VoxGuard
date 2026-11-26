# VoxGuard

**Voice-first query console — ask by speaking, get an answer you can hear back.**

VoxGuard records a spoken question in the browser, sends the audio straight to Gemini
(`gemini-2.5-flash`), renders the answer as text, and speaks it back with in-memory
text-to-speech. A typed input mode with response-style control covers quiet
environments. Every metric on screen — queries answered, response latency, input
mode — is measured at runtime, and nothing is written to disk.

Built by **Anant Sharma** for **Team VoxGuard**.

---

## Overview

| | |
|---|---|
| **Product** | VoxGuard |
| **Stack** | Python · Streamlit · Google GenAI SDK · gTTS |
| **Model** | `gemini-2.5-flash` |
| **Inputs** | Live microphone audio · typed text |
| **Outputs** | Text answer · spoken MP3 (in-memory) · Markdown transcript |
| **Hosting** | Streamlit Community Cloud (or any Python host) |
| **Team** | Team VoxGuard |

## Features

- **Two real input modes.** `st.audio_input` captures microphone audio in mobile and
  desktop browsers and passes the raw bytes to the model. The text tab adds a
  **Response Style** selector: *Concise Direct Answer*, *Technical Deep-Dive*, or
  *Hindi / Hinglish Explanation*.
- **In-memory speech output.** The answer is synthesised with `gTTS` into an
  `io.BytesIO` buffer and played with `st.audio`. No `.mp3` ever lands on disk.
- **Honest session telemetry.** Queries answered, mean and last response latency
  (measured with `time.perf_counter()` around the model call), and the voice/text
  split, all sourced from `st.session_state`.
- **Transcript export and session reset.** One click downloads the whole session as
  Markdown; another clears the session and its metrics.
- **Zero-crash error handling.** API, audio, and TTS failures are caught and turned
  into short, human-readable alerts. No tracebacks reach the interface.
- **Palette-faithful UI.** Matte slate surfaces (`#0D1117` / `#161B22`), crisp `1px`
  borders (`#30363D`), engineering emerald (`#238636`) and technical blue (`#2F81F7`),
  a 900 px content column, and touch-friendly controls that stack on narrow screens.

## Repository structure

```
VoxGuard/
├── app.py                          # Full application: UI, engine calls, telemetry
├── requirements.txt                # Pinned dependency ranges
├── README.md
├── .gitignore
└── .streamlit/
    ├── config.toml                 # Dark theme + headless server config
    └── secrets.toml.example        # TOML template (real secrets.toml is ignored)
```

## Local setup

**Requirements:** Python 3.10+ and a Gemini API key from
[Google AI Studio](https://aistudio.google.com/app/apikey).

```bash
git clone https://github.com/<your-username>/VoxGuard.git
cd VoxGuard

python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Provide the key **one** of three ways (in order of precedence):

1. **Streamlit secrets** — copy the template and edit it:

   ```bash
   # Windows
   copy .streamlit\secrets.toml.example .streamlit\secrets.toml
   # macOS / Linux
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```

   ```toml
   GEMINI_API_KEY = "your-real-key"
   ```

2. **Environment variable** — create a `.env` file in the project root:

   ```dotenv
   GEMINI_API_KEY=your-real-key
   ```

   `python-dotenv` loads it automatically at startup.

3. **Sidebar input** — if neither is configured, the app shows a password-masked
   field. The value lives only in that browser session.

Start the app:

```bash
streamlit run app.py
```

It opens at `http://localhost:8501`. The microphone prompt appears on first record;
grant permission in the browser. Browsers only allow microphone access on
`localhost` or HTTPS, so voice input on a phone requires the deployed HTTPS URL.

## Deploy to Streamlit Community Cloud

1. Push this repository to GitHub. `.env`, `.streamlit/secrets.toml`, virtualenvs,
   and Python caches are already excluded by `.gitignore`.
2. Sign in to [share.streamlit.io](https://share.streamlit.io) with GitHub.
3. **Create app → Deploy a public app from GitHub** and select:
   - **Repository:** your `VoxGuard` repo
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Open **Advanced settings → Secrets** and paste:

   ```toml
   GEMINI_API_KEY = "your-real-key"
   ```

   Secrets are the recommended path on Cloud: they are injected at runtime and never
   committed.
5. Click **Deploy**. The first build installs `requirements.txt`, then Streamlit
   serves the app at a public `*.streamlit.app` URL that works on phones and laptops.
6. Verify the header badge reads **Engine Online** and run one voice and one text
   query before sharing the link.

On later pushes, Community Cloud rebuilds automatically. To rotate the key, update
the secret value and reboot the app from the dashboard.

## Configuration reference

| Variable | Where it goes | Required |
|---|---|---|
| `GEMINI_API_KEY` | Streamlit secrets, `.env`, or the sidebar field | Yes |

Nothing else is configurable by secret. The model (`gemini-2.5-flash`), audio size
limits, and response styles are constants at the top of `app.py`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Awaiting Key Configuration` | No key found. Add it to secrets, `.env`, or the sidebar. |
| `The Gemini API key was rejected` | Key is invalid or lacks the Generative Language API. Create a fresh key in AI Studio. |
| Microphone button does nothing | Browser blocked mic access, or the page is not on `localhost`/HTTPS. Allow the microphone and reload. |
| `gemini-2.5-flash` unavailable | The key's project has no access to that model. Check model availability in AI Studio. |
| Spoken playback unavailable | The gTTS request failed (usually transient network). The text answer is still valid; retry or restart the app. |
| Rate-limit message | Gemini quota reached. Wait and retry. |

## Privacy

- Audio is held in memory for the request, forwarded to the Gemini API, and dropped.
- Gemini's own data handling applies to API calls; see Google's API terms.
- The transcript exists only in the browser session until you download it.
- No analytics, no database, no disk writes.

---

**VoxGuard** · Built by **Anant Sharma** (Team VoxGuard)
