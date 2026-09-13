"""Cloud AI integration for WEDNESDAY.

Tries Gemini first (if GEMINI_API_KEY is set), and falls back to
OpenAI (if OPENAI_API_KEY  when Gemini isn't available or
fails. Provides is_configured() and ask() for main.py to use.
"""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("[ai.py] WARNING: python-dotenv not installed, .env will not be loaded.")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

SYSTEM_PROMPT = (
    "You are WEDNESDAY, a concise, helpful voice assistant running on "
    "Kali Linux. Keep answers short and conversational since they will "
    "be read aloud by text-to-speech."
)

# --- Gemini setup ------------------------------------------------------
_gemini_model = None
_gemini_error = None
if GEMINI_API_KEY:
    try:
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        _gemini_model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=SYSTEM_PROMPT,
        )
    except ImportError:
        _gemini_error = "google-generativeai package not installed (pip install google-generativeai)"
    except Exception as exc:  # noqa: BLE001
        _gemini_error = str(exc)

# --- OpenAI setup --------------------------------------------------------
_openai_client = None
_openai_error = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI

        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        _openai_error = "openai package not installed (pip install openai)"
    except Exception as exc:  # noqa: BLE001
        _openai_error = str(exc)

OPENAI_MODEL = "gpt-4o-mini"


def _print_status() -> None:
    """Print a clear, visible summary of what ai.py detected at startup."""
    print("[ai.py] --- AI provider status ---")

    if GEMINI_API_KEY:
        if _gemini_model:
            print("[ai.py] Gemini: KEY FOUND, model ready (gemini-1.5-flash)")
        else:
            print(f"[ai.py] Gemini: KEY FOUND but setup FAILED -> {_gemini_error}")
    else:
        print("[ai.py] Gemini: no GEMINI_API_KEY found in .env")

    if OPENAI_API_KEY:
        if _openai_client:
            print(f"[ai.py] OpenAI: KEY FOUND, client ready ({OPENAI_MODEL})")
        else:
            print(f"[ai.py] OpenAI: KEY FOUND but setup FAILED -> {_openai_error}")
    else:
        print("[ai.py] OpenAI: no OPENAI_API_KEY found in .env")

    print("[ai.py] ----------------------------")


_print_status()


def is_configured() -> bool:
    """Return True if at least one AI provider (Gemini or OpenAI) is usable."""
    return bool(_gemini_model or _openai_client)


def _history_to_gemini(history: list[dict]) -> list[dict]:
    """Convert OpenAI-style {role, content} history into Gemini's format."""
    converted = []
    for msg in history:
        role = "model" if msg["role"] == "assistant" else "user"
        converted.append({"role": role, "parts": [msg["content"]]})
    return converted


def _ask_gemini(history: list[dict], new_message: str) -> str | None:
    if not _gemini_model:
        return None
    try:
        chat = _gemini_model.start_chat(history=_history_to_gemini(history))
        response = chat.send_message(new_message)
        return response.text.strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[ai.py] Gemini request failed: {exc}")
        return None


def _ask_openai(history: list[dict], new_message: str) -> str | None:
    if not _openai_client:
        return None
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": new_message})
    try:
        response = _openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=300,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[ai.py] OpenAI request failed: {exc}")
        return None


def ask(history: list[dict], new_message: str) -> str:
    """Send conversation history + new_message to an available AI provider.

    Tries Gemini first, then falls back to OpenAI. Returns a spoken
    fallback message if neither is configured or both fail.
    """
    if not is_configured():
        return (
            "I can't reach a cloud AI right now because no valid "
            "GEMINI_API_KEY or OPENAI_API_KEY is set in your .env file."
        )

    reply = _ask_gemini(history, new_message)
    if reply:
        return reply

    reply = _ask_openai(history, new_message)
    if reply:
        return reply

    return "Sorry, I ran into an error talking to the AI. Please try again."