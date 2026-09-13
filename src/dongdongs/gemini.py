"""Gemini read-assist. Opt-in only.

Only cropped PNGs and short prompts are sent, never whole pages. The key is read
from ``GEMINI_API_KEY`` and is never logged or written anywhere. Every answer is
a candidate that still goes through human review; nothing here edits images.
"""

from __future__ import annotations

import json
import os

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiUnavailable(RuntimeError):
    pass


def model_name() -> str:
    return os.environ.get("DONGDONGS_GEMINI_MODEL") or DEFAULT_MODEL


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise GeminiUnavailable("GEMINI_API_KEY is not set")
    from google import genai

    return genai.Client(api_key=key)


def _ask_json(png: bytes, prompt: str) -> dict:
    from google.genai import types

    response = _client().models.generate_content(
        model=model_name(),
        contents=[types.Part.from_bytes(data=png, mime_type="image/png"), prompt],
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
    )
    try:
        answer = json.loads(response.text)
    except (TypeError, ValueError):
        answer = {"raw": response.text}
    answer["model"] = model_name()
    return answer


def read_watermark_text(png: bytes) -> dict:
    return _ask_json(
        png,
        'Read the text shown in this image exactly as printed. Return JSON {"text": "...", "confidence": "high|medium|low"}. '
        'Use an empty string if nothing is readable. Do not guess.',
    )


def read_label(png: bytes) -> dict:
    return _ask_json(
        png,
        "This image is one cell of an electrical test report table. Transcribe its text exactly. "
        "Mark subscripts as <sub>..</sub> and superscripts as <sup>..</sup>. Do not translate, correct or complete anything. "
        'Return JSON {"text": "plain text", "markup": "text with sub/sup tags", "confidence": "high|medium|low"}.',
    )


def connectivity_test() -> str:
    if not available():
        return "no-key"
    try:
        _client().models.get(model=model_name())
        return "ok"
    except Exception as exc:  # report the class only; messages may echo request details
        return f"error:{type(exc).__name__}"
