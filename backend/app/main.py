"""HTTP API. Images are processed in memory and never written to disk; a session keeps its
photos in memory until it expires (1 hour idle)."""

from __future__ import annotations

import io
import json

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from pydantic import BaseModel

from . import orchestrator
from .pipeline import Options, analyze, focus_from_result, load_image
from .render import blur_excluded, render_focus, render_focus_tight
from .schemas import AnalysisResult, Intent, SessionView, StepAction
from .session import Session
from .vlm import SceneAnalysisError, VLMUnavailableError

load_dotenv()

app = FastAPI(title="Declutter vision API")


async def _read_image(upload: UploadFile):
    try:
        return load_image(await upload.read())
    except Exception as e:
        raise HTTPException(400, f"Could not read image: {e}") from e


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/analyze", response_model=AnalysisResult)
async def analyze_endpoint(
    image: UploadFile = File(...),
    use_detector: bool = Form(True),
    use_segmenter: bool = Form(True),
):
    img = await _read_image(image)
    try:
        return await run_in_threadpool(analyze, img, Options(use_detector=use_detector, use_segmenter=use_segmenter))
    except SceneAnalysisError as e:
        raise HTTPException(422, str(e)) from e
    except VLMUnavailableError as e:
        raise HTTPException(503, str(e)) from e


@app.post("/render")
async def render_endpoint(
    image: UploadFile = File(...),
    result: str = Form(..., description="AnalysisResult JSON from /analyze"),
):
    img = await _read_image(image)
    try:
        parsed = AnalysisResult.model_validate(json.loads(result))
    except Exception as e:
        raise HTTPException(400, f"Invalid result JSON: {e}") from e
    buf = io.BytesIO()
    render_focus(img, parsed, parsed.focus or focus_from_result(parsed)).save(buf, format="JPEG", quality=88)
    return Response(buf.getvalue(), media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Guided sessions
# ---------------------------------------------------------------------------


class MessageIn(BaseModel):
    text: str | None = None
    action: Intent | None = None  # set by frontend buttons, e.g. "done" or "skip"


def _session(session_id: str) -> Session:
    s = orchestrator.store.get(session_id)
    if s is None:
        raise HTTPException(404, "Session not found or expired.")
    return s


async def _run(fn, *args):
    try:
        return await run_in_threadpool(fn, *args)
    except SceneAnalysisError as e:
        raise HTTPException(422, str(e)) from e
    except VLMUnavailableError as e:
        raise HTTPException(503, str(e)) from e


@app.post("/sessions", response_model=SessionView)
async def create_session(image: UploadFile = File(...)):
    return await _run(orchestrator.start_session, await _read_image(image))


@app.post("/sessions/{session_id}/messages", response_model=SessionView)
async def post_message(session_id: str, body: MessageIn):
    if not body.text and body.action is None:
        raise HTTPException(400, "Send text, an action, or both.")
    return await _run(orchestrator.handle_message, _session(session_id), body.text, body.action)


@app.post("/sessions/{session_id}/photo", response_model=SessionView)
async def post_photo(session_id: str, image: UploadFile = File(...)):
    session = _session(session_id)
    return await _run(orchestrator.add_photo, session, await _read_image(image))


@app.get("/sessions/{session_id}/steps/{step_id}/focus.jpg")
def step_focus_image(session_id: str, step_id: str, style: str = "tight"):
    session = _session(session_id)
    step = session.get(step_id)
    if step is None:
        raise HTTPException(404, "Unknown step.")
    photo = session.photos[step.photo_idx]
    focus = session.step_focus(step)
    view = photo.analysis.model_copy(update={"items": session.step_items(step)})
    # A closer-photo step has no items to outline, so it always frames the zone.
    tight = style != "box" and step.step.action != StepAction.take_closer_photo
    img = (render_focus_tight if tight else render_focus)(photo.image, view, focus) if focus else blur_excluded(photo.image, view)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg")
