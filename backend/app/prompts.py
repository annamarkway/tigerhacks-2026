"""Prompt text lives in backend/prompts/*.md so it can be edited without touching code."""

from __future__ import annotations

from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


@cache
def load(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text()


SYSTEM_PROMPT = load("vision")
USER_PROMPT = "Analyze this photo. It is {width}x{height} pixels."
