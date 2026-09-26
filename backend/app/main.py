"""HTTP API. Images are processed in memory and never written to disk."""

from __future__ import annotations

import io
import json

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from .pipeline import Options, analyze, focus_from_result, load_image
from .render import render_focus
from .schemas import AnalysisResult
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
