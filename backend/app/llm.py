"""Shared Claude structured-output call used by the vision, classify, triage and coach roles."""

from __future__ import annotations

import base64
import io
from typing import TypeVar

import anthropic
from PIL import Image
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


class SceneAnalysisError(RuntimeError):
    """The model answered but the answer is unusable (refusal, truncation)."""


class VLMUnavailableError(RuntimeError):
    """Claude couldn't be reached: missing credentials, network, rate limit, or server error."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def image_block(img: Image.Image) -> dict:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=90)
    data = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def _create(model: str, system: str, content: list[dict], output_format: type[T], max_tokens: int, thinking: bool):
    kwargs = {"thinking": {"type": "adaptive"}} if thinking else {}
    return _get_client().beta.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=system,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
        output_format=output_format,
        **kwargs,
    )


def claude_parse(
    model: str,
    system: str,
    content: list[dict],
    output_format: type[T],
    *,
    max_tokens: int = 16000,
    thinking: bool = True,
    what: str = "Analysis",
) -> T:
    """One Claude call returning a validated `output_format`, with errors mapped to our two error types."""
    try:
        response = _create(model, system, content, output_format, max_tokens, thinking)
    except anthropic.AuthenticationError as e:
        raise VLMUnavailableError("Claude rejected the API key.") from e
    except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
        raise VLMUnavailableError(f"Claude is temporarily unavailable: {e}") from e
    except TypeError as e:
        if "authentication" in str(e):
            raise VLMUnavailableError("No Anthropic credentials configured; set ANTHROPIC_API_KEY in backend/.env.") from e
        raise

    if response.stop_reason == "refusal":
        raise SceneAnalysisError(f"{what}: the model declined.")
    if response.stop_reason == "max_tokens":
        raise SceneAnalysisError(f"{what} was cut off (max_tokens).")
    if response.parsed_output is None:
        raise SceneAnalysisError(f"{what} returned no parseable output.")
    return response.parsed_output
