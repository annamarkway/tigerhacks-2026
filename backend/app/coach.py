"""Coach agent: reads the person's message, picks an intent, and writes the reply.

Claude Haiku by default (runs every turn); set COACH_PROVIDER=gemini to use Gemini with a
Claude fallback. Both use prompts/coach.md and return the same CoachReply, so switching doesn't
change the voice.
"""

from __future__ import annotations

import json
import logging
import os
from functools import cache
from typing import Protocol

from .llm import claude_parse
from .prompts import load
from .schemas import CoachReply

log = logging.getLogger(__name__)


class CoachProvider(Protocol):
    def reply(self, context: dict) -> CoachReply: ...


def _user_text(context: dict) -> str:
    return "Session context (JSON):\n" + json.dumps(context, indent=1, default=str)


class ClaudeCoach:
    def reply(self, context: dict) -> CoachReply:
        model = os.environ.get("HOARD_COACH_MODEL", "claude-haiku-4-5")
        content = [{"type": "text", "text": _user_text(context)}]
        return claude_parse(model, load("coach"), content, CoachReply, max_tokens=2000, thinking=False, what="Coach reply")


class GeminiCoach:
    def __init__(self) -> None:
        from google import genai
        from google.genai import types

        # One attempt with a short timeout: on a 503 we'd rather fall back to Claude than wait.
        self._client = genai.Client(  # reads GEMINI_API_KEY
            http_options=types.HttpOptions(timeout=20_000, retry_options=types.HttpRetryOptions(attempts=1))
        )

    def reply(self, context: dict) -> CoachReply:
        from google.genai import types

        resp = self._client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
            contents=_user_text(context),
            config=types.GenerateContentConfig(
                system_instruction=load("coach"),
                response_mime_type="application/json",
                response_schema=CoachReply,
                temperature=0.6,
            ),
        )
        if isinstance(resp.parsed, CoachReply):
            return resp.parsed
        return CoachReply.model_validate_json(resp.text or "")


class FallbackCoach:
    """Try each provider in turn (Gemini's free tier returns 503s under load)."""

    def __init__(self, *providers: CoachProvider) -> None:
        self.providers = providers

    def reply(self, context: dict) -> CoachReply:
        for i, provider in enumerate(self.providers):
            try:
                return provider.reply(context)
            except Exception as e:
                if i == len(self.providers) - 1:
                    raise
                log.warning("%s failed (%s); trying the next coach", type(provider).__name__, str(e)[:120])
        raise RuntimeError("no coach providers")


@cache
def get_coach(provider: str | None = None) -> CoachProvider:
    provider = (provider or os.environ.get("COACH_PROVIDER", "claude")).lower()
    return ClaudeCoach() if provider == "claude" else FallbackCoach(GeminiCoach(), ClaudeCoach())
