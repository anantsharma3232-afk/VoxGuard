"""VoxGuard — voice-first query console.

A single-file Streamlit application that accepts spoken or typed questions,
answers them with Google's Gemini models, speaks the answer back through
in-memory text-to-speech, and keeps honest, runtime-only session telemetry.

Design constraints honoured here:
  * No secrets or machine-specific paths in code (Streamlit secrets -> .env -> UI).
  * No files written to disk: audio in, audio out, exports all use memory buffers.
  * Every network, SDK and codec call is guarded so the UI never shows a traceback.
"""

from __future__ import annotations

import html
import io
import os
import time
from datetime import datetime
from typing import Any, Optional

import streamlit as st

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

APP_NAME = "VoxGuard"
FOOTER_TEXT = "VoxGuard • Built by Anant Sharma (Team VoxGuard)"
GEMINI_MODEL = "gemini-2.5-flash"

# Gemini inline audio limit is 20 MB for the whole request; stay well below it.
MAX_AUDIO_BYTES = 18 * 1024 * 1024
MIN_AUDIO_BYTES = 512

MAX_QUESTION_CHARS = 2000
MAX_TTS_CHARS = 4500

RESPONSE_STYLES = (
    "Concise Direct Answer",
    "Technical Deep-Dive",
    "Hindi / Hinglish Explanation",
)

DEFAULT_STYLE = RESPONSE_STYLES[0]

SYSTEM_INSTRUCTION = (
    "You are VoxGuard, a precise, voice-first assistant. Answer the user's "
    "question directly and factually. Never claim to be an AI model, never use "
    "emojis, and keep the answer easy to read out loud. If the request is "
    "genuinely ambiguous, ask one short clarifying question instead of guessing."
)

STYLE_INSTRUCTIONS = {
    "Concise Direct Answer": (
        "Answer in at most 90 words. Lead with the answer, then at most one "
        "supporting sentence."
    ),
    "Technical Deep-Dive": (
        "Give a structured technical explanation in short paragraphs. Cover how "
        "it works, the key trade-offs, and the main failure modes. Use bullets "
        "only where they genuinely help."
    ),
    "Hindi / Hinglish Explanation": (
        "Reply in natural Hinglish: Hindi written in Roman script with everyday "
        "English technical terms where they are clearer. Keep sentences short "
        "and spoken-friendly."
    ),
}

SESSION_KEYS = (
    "vg_entries",
    "vg_last_result",
    "vg_pending_audio",
    "vg_consumed_sig",
    "manual_key",
)

# UI styling. Kept as a module constant so the markup stays readable.
_STYLE = """
<style>
:root {
  --vg-bg: #0D1117;
  --vg-surface: #161B22;
  --vg-border: #30363D;
  --vg-text: #F0F6FC;
  --vg-muted: #8B949E;
  --vg-green: #238636;
  --vg-green-soft: #3FB950;
  --vg-blue: #2F81F7;
  --vg-amber: #D29922;
}

/* Hide Streamlit chrome, keep touch-friendly controls. */
#MainMenu, footer { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"] { display: none; }
.stAppDeployButton, .stDeployButton { display: none !important; }

html, body, .stApp {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto,
    Helvetica, Arial, sans-serif;
}
.stApp { background-color: var(--vg-bg); color: var(--vg-text); }

.block-container {
  max-width: 900px;
  padding: 2rem 1rem 3rem;
}

section[data-testid="stSidebar"] {
  background-color: var(--vg-bg);
  border-right: 1px solid var(--vg-border);
}
section[data-testid="stSidebar"] .block-container {
  max-width: 100%;
  padding: 2rem 1.1rem 2rem;
}

/* Header */
.vg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--vg-border);
  margin-bottom: 20px;
}
.vg-brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
.vg-mark {
  width: 38px; height: 38px; flex: 0 0 auto;
  border-radius: 8px;
  background: var(--vg-surface);
  border: 1px solid var(--vg-border);
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 17px; color: var(--vg-text);
}
.vg-title {
  font-size: 1.35rem; font-weight: 700; letter-spacing: -0.01em;
  line-height: 1.1; color: var(--vg-text);
}
.vg-subtitle { font-size: 0.8rem; color: var(--vg-muted); margin-top: 4px; }

.vg-pill {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 0.78rem; font-weight: 600;
  padding: 7px 12px; border-radius: 999px;
  border: 1px solid var(--vg-border);
  background: var(--vg-surface);
  white-space: nowrap;
}
.vg-pill-online { color: var(--vg-green-soft); border-color: rgba(35, 134, 54, 0.55); }
.vg-pill-waiting { color: var(--vg-amber); border-color: rgba(210, 153, 34, 0.45); }
.vg-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: currentColor; display: inline-block;
}

/* Small typographic helpers */
.vg-eyebrow {
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--vg-muted); font-weight: 600;
}
.vg-meta { font-size: 0.78rem; color: var(--vg-muted); }
.vg-note {
  border: 1px solid var(--vg-border);
  border-left: 3px solid var(--vg-amber);
  background: var(--vg-surface);
  color: #E3B341;
  padding: 12px 14px;
  border-radius: 6px;
  font-size: 0.88rem;
  line-height: 1.5;
  margin-bottom: 10px;
}
.vg-footer {
  margin-top: 28px; padding-top: 16px;
  border-top: 1px solid var(--vg-border);
  text-align: center; color: var(--vg-muted); font-size: 0.75rem;
}

/* Controls */
.stTabs [data-baseweb="tab-list"] {
  gap: 6px;
  border-bottom: 1px solid var(--vg-border);
}
.stTabs [data-baseweb="tab"] {
  height: 44px; padding: 0 12px;
  color: var(--vg-muted); font-weight: 600; font-size: 0.9rem;
}
.stTabs [aria-selected="true"] { color: var(--vg-text) !important; }
.stTabs [data-baseweb="tab-highlight"] {
  background-color: var(--vg-blue); height: 2px;
}

.stButton > button,
.stDownloadButton > button,
.stFormSubmitButton > button {
  border-radius: 6px;
  border: 1px solid var(--vg-border);
  background-color: var(--vg-surface);
  color: var(--vg-text);
  font-weight: 600;
  min-height: 44px;
  width: 100%;
  transition: border-color 120ms ease, background-color 120ms ease;
}
.stButton > button:hover,
.stDownloadButton > button:hover,
.stFormSubmitButton > button:hover {
  border-color: #8B949E;
  color: var(--vg-text);
  background-color: #1C2430;
}
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
  background-color: var(--vg-green);
  border-color: #2EA043;
  color: #FFFFFF;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {
  background-color: #2EA043;
  border-color: #3FB950;
}

[data-testid="stTextArea"] textarea,
[data-testid="stTextInput"] input {
  background-color: var(--vg-bg);
  color: var(--vg-text);
  border: 1px solid var(--vg-border);
  border-radius: 6px;
}
[data-testid="stSelectbox"] > div > div {
  background-color: var(--vg-bg);
  border: 1px solid var(--vg-border);
  border-radius: 6px;
}
[data-testid="stMetricValue"] { font-size: 1.4rem; color: var(--vg-text); }
[data-testid="stMetricLabel"] { color: var(--vg-muted); }
[data-testid="stExpander"] details {
  border: 1px solid var(--vg-border);
  border-radius: 6px;
  background: var(--vg-surface);
}
.stAudio audio { width: 100%; }
hr { border-color: var(--vg-border); }

@media (max-width: 640px) {
  .block-container { padding: 1.1rem 0.85rem 2.2rem; }
  .vg-title { font-size: 1.15rem; }
  .vg-subtitle { font-size: 0.74rem; }
  .vg-header { align-items: flex-start; }
  .vg-pill { font-size: 0.72rem; }
}
</style>
"""


class QueryError(RuntimeError):
    """User-facing error raised for any failed query path."""


# --------------------------------------------------------------------------- #
# Page setup
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🛡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(_STYLE, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #

def init_state() -> None:
    st.session_state.setdefault("vg_entries", [])
    st.session_state.setdefault("vg_last_result", None)
    st.session_state.setdefault("vg_pending_audio", None)
    st.session_state.setdefault("vg_consumed_sig", None)
    st.session_state.setdefault("manual_key", "")


def reset_session() -> None:
    for key in SESSION_KEYS:
        st.session_state.pop(key, None)
    st.session_state.vg_entries = []
    st.session_state.vg_last_result = None
    st.session_state.vg_pending_audio = None
    st.session_state.vg_consumed_sig = None


def sanitize_text(value: Optional[str], limit: int = MAX_QUESTION_CHARS) -> str:
    """Strip control characters, trim whitespace, and cap the length."""
    if not value:
        return ""
    cleaned = "".join(ch for ch in value if ch == "\n" or ch >= " ")
    return cleaned.strip()[:limit]


def module_available(module: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #

def secret_api_key() -> Optional[str]:
    try:
        value = st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def env_api_key() -> Optional[str]:
    value = os.getenv("GEMINI_API_KEY")
    if value and value.strip():
        return value.strip()
    return None


init_state()

managed_key: Optional[str] = None
managed_source: Optional[str] = None

_secret = secret_api_key()
if _secret:
    managed_key, managed_source = _secret, "Streamlit secrets"
else:
    _env = env_api_key()
    if _env:
        managed_key, managed_source = _env, "environment variable (.env)"


# --------------------------------------------------------------------------- #
# Sidebar: key management + real runtime checks
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.markdown(
        "<div class='vg-eyebrow' style='letter-spacing:0.16em;'>VOXGUARD</div>",
        unsafe_allow_html=True,
    )
    st.caption("Console settings")
    st.divider()

    if managed_key is None:
        st.text_input(
            "Gemini API key",
            type="password",
            key="manual_key",
            placeholder="Paste your key",
            help=(
                "Used for this browser session only. It is never written to disk "
                "or included in the session transcript."
            ),
        )
        st.caption(
            "No key found in secrets or the environment. Paste one above to "
            "activate the engine."
        )
    else:
        st.caption(f"Engine key loaded from {managed_source}.")

    manual_key = sanitize_text(st.session_state.get("manual_key", ""), limit=256)
    api_key = managed_key or manual_key or None

    st.divider()
    st.markdown("**Runtime status**")

    sdk_ready = module_available("google.genai")
    tts_ready = module_available("gtts")
    entries_now = st.session_state.get("vg_entries", [])

    def _status_row(label: str, ok: bool, ok_text: str, bad_text: str) -> None:
        colour = "#3FB950" if ok else "#D29922"
        text = ok_text if ok else bad_text
        st.markdown(
            f"<div class='vg-meta' style='margin-bottom:6px;'>"
            f"<span style='color:{colour};'>●</span> {html.escape(label)}: "
            f"{html.escape(text)}</div>",
            unsafe_allow_html=True,
        )

    _status_row("API credential", bool(api_key), "Configured", "Missing")
    _status_row("GenAI SDK", sdk_ready, "Installed", "Not installed")
    _status_row("Speech output", tts_ready, "gTTS ready", "gTTS missing")
    st.markdown(
        f"<div class='vg-meta' style='margin-bottom:6px;'>"
        f"<span style='color:#3FB950;'>●</span> Model: {GEMINI_MODEL}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div class='vg-meta'><span style='color:#58A6FF;'>●</span> "
        f"Session queries: {len(entries_now)}</div>",
        unsafe_allow_html=True,
    )

    st.divider()
    st.caption(
        "Audio never touches disk. Requests are processed in-memory and only the "
        "text answer is kept in this session."
    )


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

engine_online = bool(api_key)
pill_class = "vg-pill-online" if engine_online else "vg-pill-waiting"
pill_text = "Engine Online" if engine_online else "Awaiting Key Configuration"

st.markdown(
    f"""
    <div class="vg-header">
      <div class="vg-brand">
        <div class="vg-mark">V</div>
        <div>
          <div class="vg-title">{APP_NAME}</div>
          <div class="vg-subtitle">
            Voice-first query console &middot; Team VoxGuard
          </div>
        </div>
      </div>
      <span class="vg-pill {pill_class}">
        <span class="vg-dot"></span>{pill_text}
      </span>
    </div>
    """,
    unsafe_allow_html=True,
)

if engine_online:
    st.markdown(
        "<div class='vg-eyebrow' style='margin-bottom:14px;'>"
        f"Speech in &rarr; {GEMINI_MODEL} &rarr; speech out &middot; session "
        "telemetry is live</div>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        "<div class='vg-note'><strong>Engine key required.</strong> Add "
        "<code>GEMINI_API_KEY</code> to <code>.streamlit/secrets.toml</code> or "
        "your local <code>.env</code>, or paste it in the sidebar. The interface "
        "below stays fully browsable while the engine is offline.</div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Processing helpers
# --------------------------------------------------------------------------- #

def _friendly_api_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "api key" in message or "api_key_invalid" in message or "401" in message:
        return (
            "The Gemini API key was rejected. Check that the key is active and "
            "has access to the Generative Language API."
        )
    if "429" in message or "quota" in message or "resource_exhausted" in message:
        return (
            "The Gemini API rate limit was reached. Wait a few seconds and try "
            "again."
        )
    if "deadline" in message or "timeout" in message or "timed out" in message:
        return "The request to Gemini timed out. Check your connection and retry."
    if "location" in message or "region" in message:
        return "Gemini is not available from this network region."
    if "safety" in message or "blocked" in message:
        return "The request was blocked by the model's safety filters. Rephrase it."
    return "The Gemini request failed. Check your connection and try again."


def generate_answer(
    *,
    api_key: str,
    question: str,
    style: str,
    audio: Optional[dict[str, Any]] = None,
) -> str:
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # ImportError or broken installation
        raise QueryError(
            "The google-genai SDK is not available. Install dependencies with "
            "pip install -r requirements.txt."
        ) from exc

    if audio is None and not question:
        raise QueryError(
            "Nothing to answer yet: record a voice query or type a question."
        )

    style_rule = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS[DEFAULT_STYLE])

    contents: list[Any] = []
    if audio is not None:
        try:
            contents.append(
                types.Part.from_bytes(data=audio["data"], mime_type=audio["mime"])
            )
        except Exception as exc:
            raise QueryError(
                "That recording could not be decoded. Try recording again."
            ) from exc

    prompt_lines = []
    if audio is not None:
        prompt_lines.append(
            "The attached audio is the user's spoken question. Answer what they asked."
        )
    if question:
        prompt_lines.append(f"User question:\n{question}")
    prompt_lines.append(f"Response style: {style_rule}")
    contents.append("\n\n".join(prompt_lines))

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.4,
                system_instruction=SYSTEM_INSTRUCTION,
            ),
        )
    except Exception as exc:
        raise QueryError(_friendly_api_error(exc)) from exc

    text = getattr(response, "text", None)
    answer = text.strip() if isinstance(text, str) else ""
    if not answer:
        raise QueryError(
            "Gemini returned an empty response. Try rephrasing your query."
        )
    return answer


def synthesize_speech(answer: str) -> tuple[Optional[bytes], Optional[str]]:
    """Render the answer to MP3 entirely in memory. Never raises."""
    if not answer.strip():
        return None, None
    try:
        from gtts import gTTS
    except Exception:
        return None, "Spoken playback is unavailable: the gTTS package is not installed."

    language = "hi" if any("\u0900" <= ch <= "\u097F" for ch in answer) else "en"
    try:
        buffer = io.BytesIO()
        gTTS(text=answer[:MAX_TTS_CHARS], lang=language, slow=False).write_to_fp(buffer)
        audio_bytes = buffer.getvalue()
        if not audio_bytes:
            raise ValueError("empty audio buffer")
        return audio_bytes, None
    except Exception:
        return None, (
            "Spoken playback is unavailable right now (speech service unreachable)."
        )


def handle_query(
    *,
    api_key: Optional[str],
    mode: str,
    style: str,
    question: str = "",
    audio: Optional[dict[str, Any]] = None,
) -> None:
    if not api_key:
        st.error(
            "No Gemini API key is configured. Add one in the sidebar, or set "
            "GEMINI_API_KEY in secrets or the environment."
        )
        return

    if mode == "voice":
        if not audio:
            st.warning("Record a voice query first, then run the analysis.")
            return
        if len(audio["data"]) < MIN_AUDIO_BYTES:
            st.warning("That recording is too short. Hold record and speak clearly.")
            return
        if len(audio["data"]) > MAX_AUDIO_BYTES:
            st.error("That recording is too large. Keep voice queries under 18 MB.")
            return
        question_text = f"(voice recording · {len(audio['data']) / 1024:.1f} KB)"
        question_for_model = ""
    else:
        question_for_model = sanitize_text(question)
        if not question_for_model:
            st.warning("Type a question before submitting.")
            return
        question_text = question_for_model
        audio = None

    started = time.perf_counter()
    with st.spinner("VoxGuard is processing your query…"):
        try:
            answer = generate_answer(
                api_key=api_key,
                question=question_for_model,
                style=style,
                audio=audio,
            )
        except QueryError as exc:
            st.error(str(exc))
            return
        latency = time.perf_counter() - started
        tts_bytes, tts_error = synthesize_speech(answer)

    now = datetime.now()
    entry = {
        "time_label": now.strftime("%H:%M:%S"),
        "timestamp": now.isoformat(timespec="seconds"),
        "mode": mode,
        "mode_label": "Voice input" if mode == "voice" else "Text input",
        "style": style,
        "question": question_text,
        "answer": answer,
        "latency": latency,
        "tts": tts_bytes,
        "tts_error": tts_error,
    }
    st.session_state.vg_entries.append(entry)
    st.session_state.vg_last_result = entry

    if mode == "voice" and audio is not None:
        st.session_state.vg_consumed_sig = audio.get("sig")
        st.session_state.vg_pending_audio = None


def render_result(entry: dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown("<div class='vg-eyebrow'>Response</div>", unsafe_allow_html=True)
        st.caption(
            f"{entry['mode_label']} · {entry['style']} · {entry['time_label']} · "
            f"{entry['latency']:.2f} s"
        )
        st.markdown(entry["answer"])
        if entry.get("tts"):
            st.audio(entry["tts"], format="audio/mpeg")
        elif entry.get("tts_error"):
            st.caption(entry["tts_error"])


def build_transcript(entries: list[dict[str, Any]]) -> str:
    total = len(entries)
    mean = sum(item["latency"] for item in entries) / total if total else 0.0
    voice_count = sum(1 for item in entries if item["mode"] == "voice")
    text_count = total - voice_count

    lines: list[str] = [
        "# VoxGuard — Session Transcript",
        "",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Queries answered: {total}",
        f"- Mean response latency: {mean:.2f} s",
        f"- Input modes: voice {voice_count} · text {text_count}",
        "",
        "---",
        "",
    ]
    for index, item in enumerate(entries, start=1):
        lines.extend(
            [
                f"## {index}. {item['time_label']} · {item['mode_label']} · "
                f"{item['style']}",
                "",
                "**Query**",
                "",
                item["question"].strip() or "_(voice input)_",
                "",
                "**Answer**",
                "",
                item["answer"].strip(),
                "",
                f"_Response latency: {item['latency']:.2f} s_",
                "",
                "---",
                "",
            ]
        )
    lines.extend([FOOTER_TEXT, ""])
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Input tabs
# --------------------------------------------------------------------------- #

voice_tab, text_tab = st.tabs(["Voice input", "Text input"])

voice_submit = False
text_submit = False
text_question = ""

with voice_tab:
    st.caption(
        "Record with your microphone. The audio bytes go straight to the model — "
        "nothing is written to disk."
    )
    recorded = st.audio_input("Record your voice query", key="vg_recorder")

    if recorded is not None:
        try:
            raw = (
                recorded.getvalue()
                if hasattr(recorded, "getvalue")
                else recorded.read()
            )
        except Exception:
            raw = b""
        if raw:
            signature = (len(raw), hash(raw))
            if signature != st.session_state.get("vg_consumed_sig"):
                st.session_state.vg_pending_audio = {
                    "data": raw,
                    "mime": getattr(recorded, "type", None) or "audio/wav",
                    "sig": signature,
                }

    pending_audio = st.session_state.get("vg_pending_audio")
    if pending_audio:
        st.markdown(
            f"<div class='vg-meta' style='margin:6px 0 10px;'>"
            f"Recording captured · {len(pending_audio['data']) / 1024:.1f} KB · "
            f"{html.escape(str(pending_audio['mime']))}</div>",
            unsafe_allow_html=True,
        )

    voice_submit = st.button(
        "Analyze voice query",
        type="primary",
        key="vg_voice_submit",
        disabled=pending_audio is None,
    )

with text_tab:
    text_question = st.text_area(
        "Your question",
        key="vg_text_query",
        height=140,
        max_chars=MAX_QUESTION_CHARS,
        placeholder="Ask anything. Shift + Enter for a new line.",
    )
    st.selectbox(
        "Response style",
        RESPONSE_STYLES,
        index=0,
        key="vg_style",
        help="Controls tone, length, and language of the answer.",
    )
    text_submit = st.button("Ask VoxGuard", type="primary", key="vg_text_submit")

style_choice = st.session_state.get("vg_style", DEFAULT_STYLE)


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #

if voice_submit:
    handle_query(
        api_key=api_key,
        mode="voice",
        style=DEFAULT_STYLE,
        audio=st.session_state.get("vg_pending_audio"),
    )
elif text_submit:
    handle_query(
        api_key=api_key,
        mode="text",
        style=style_choice,
        question=text_question,
    )

last_result = st.session_state.get("vg_last_result")
if last_result:
    render_result(last_result)


# --------------------------------------------------------------------------- #
# Session telemetry + export
# --------------------------------------------------------------------------- #

entries: list[dict[str, Any]] = st.session_state.get("vg_entries", [])
st.divider()
st.markdown("<div class='vg-eyebrow'>Session telemetry</div>", unsafe_allow_html=True)

if entries:
    mean_latency = sum(item["latency"] for item in entries) / len(entries)
    voice_total = sum(1 for item in entries if item["mode"] == "voice")
    last_entry = entries[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Queries answered", len(entries))
    c2.metric("Mean latency", f"{mean_latency:.2f} s")
    c3.metric("Last latency", f"{last_entry['latency']:.2f} s")
    c4.metric("Voice / text", f"{voice_total} / {len(entries) - voice_total}")
else:
    st.caption(
        "No queries yet. Metrics appear here after the first answered query — "
        "they are measured at runtime, never simulated."
    )

export_col, clear_col = st.columns(2)
with export_col:
    st.download_button(
        "Download Session Transcript (.md)",
        data=build_transcript(entries) if entries else "",
        file_name=f"voxguard-transcript-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md",
        mime="text/markdown",
        key="vg_download",
        disabled=not entries,
    )
with clear_col:
    if st.button("Clear Session", key="vg_clear"):
        reset_session()
        st.rerun()


st.markdown(f"<div class='vg-footer'>{FOOTER_TEXT}</div>", unsafe_allow_html=True)
