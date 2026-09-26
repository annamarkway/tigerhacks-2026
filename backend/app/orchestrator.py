"""Session orchestration: vision + classify (parallel) -> triage -> coach, then one coach call per turn.

Sync functions so the CLI can call them directly; FastAPI runs them in a threadpool.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from . import classify as classify_mod
from . import coach as coach_mod
from . import pipeline, triage
from .schemas import AnalysisResult, Assessment, CoachReply, Intent, SessionView, StepAction
from .session import CRISIS_RESOURCES, Photo, Session, SessionStore, is_crisis

log = logging.getLogger(__name__)

store = SessionStore()

_DONE_RE = re.compile(r"\b(done|finished|did it|got it|complete[d]?)\b", re.IGNORECASE)
_SKIP_RE = re.compile(r"\b(something else|skip|another|different|not this)\b", re.IGNORECASE)


def _analyze_photo(
    image: Image.Image,
    options: pipeline.Options | None,
    analysis: AnalysisResult | None = None,
    assess: bool = True,
) -> tuple[Photo, Assessment | None]:
    """Vision pipeline and classifier run in parallel; a classifier failure isn't fatal.

    Pass a saved `analysis` to skip the vision call, and `assess=False` to skip the classifier.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        vision = pool.submit(pipeline.analyze, image, options) if analysis is None else None
        assess_job = pool.submit(classify_mod.classify, image) if assess else None
        if vision is not None:
            analysis = vision.result()  # vision errors propagate (422 / 503 at the API)
        if assess_job is None:
            return Photo(image=image, analysis=analysis), None
        try:
            assessment = assess_job.result()
        except Exception:
            log.exception("Assessment failed; continuing without it")
            assessment = None
    return Photo(image=image, analysis=analysis), assessment


def _fallback_reply(session: Session, text: str | None, forced: Intent | None) -> CoachReply:
    """Used when the coach model is unreachable: keyword intent + plain wording."""
    intent = forced or (Intent.done if text and _DONE_RE.search(text) else Intent.skip if text and _SKIP_RE.search(text) else Intent.support)
    return CoachReply(intent=intent, message="")


def _template_message(session: Session, intent: Intent | None) -> str:
    cur = session.current
    if cur is None:
        return "That's everything I can see in this photo. Nice work. You can rest, or send a new photo when you're ready."
    if cur.step.action == StepAction.take_closer_photo:
        return "When you're ready, take a closer photo of the highlighted area and send it here."
    names = ", ".join(i.label for i in session.step_items(cur))
    lead = {Intent.done: "Nice work. ", Intent.skip: "No problem. "}.get(intent, "")
    return f"{lead}Next, just the highlighted {names}. Tell me when you're done, or ask for something else."


SAFETY_HOLD = (
    "I hear you, and I know this part is hard. This piece is a safety step, so I'd like us to finish it before "
    "moving on. Let's make it as small as possible: just the highlighted items, straight into a trash bag."
)
SAFETY_HOLD_SORT = (
    "I hear you, and I know this part is hard. These items need to come out of the path for your safety, so I'd "
    "like us to finish this before moving on. Let's make it as small as possible: just the highlighted items. "
    "You decide what to keep and what goes in the let-go bag."
)


def _safety_hold(session: Session) -> str:
    cur = session.current
    return SAFETY_HOLD_SORT if cur and cur.step.action == StepAction.sort else SAFETY_HOLD


def _ask_coach(
    session: Session, turn: str, text: str | None, forced: Intent | None, skip_refused: bool = False
) -> CoachReply:
    try:
        return coach_mod.get_coach().reply(session.coach_context(turn, text, forced, skip_refused))
    except Exception as e:
        log.warning("Coach call failed (%s); using fallback wording", str(e)[:200])
        return _fallback_reply(session, text, forced)


def start_session(
    image: Image.Image,
    options: pipeline.Options | None = None,
    analysis: AnalysisResult | None = None,
    assess: bool = True,
) -> SessionView:
    photo, assessment = _analyze_photo(image, options, analysis, assess)
    steps, notes = triage.plan_steps(photo.analysis, assessment)
    session = Session(id=store.new_id(), photos=[], assessment=assessment, steps=[])
    session.add_plan(photo, steps, notes)
    store.put(session)

    reply = _ask_coach(session, "opening", None, None)
    message = reply.message or _template_message(session, None)
    session.history.append({"role": "coach", "text": message})
    return session.view(message, None)


def handle_message(session: Session, text: str | None, action: Intent | None = None) -> SessionView:
    if text:
        session.history.append({"role": "user", "text": text})

    # Hazardous steps can't be skipped: a skip becomes the smaller version (or support if already small).
    cur = session.current
    hazard = bool(cur and cur.step.hazard)
    hold = Intent.support if cur and cur.smaller else Intent.smaller
    skip_refused = hazard and action == Intent.skip
    forced = hold if skip_refused else action

    reply = _ask_coach(session, "reply", text, forced, skip_refused)
    intent = forced or reply.intent
    message = reply.message
    if hazard and intent == Intent.skip:  # the model ignored the rule; hold firm with fixed wording
        intent, message = hold, _safety_hold(session)
    if skip_refused and not message:
        message = _safety_hold(session)
    if is_crisis(text):
        intent = Intent.crisis

    session.apply(intent)
    if intent == Intent.crisis:
        message = f"{message}\n\n{CRISIS_RESOURCES}".strip()
    else:
        message = message or _template_message(session, intent)
    session.history.append({"role": "coach", "text": message})
    return session.view(message, intent)


def add_photo(session: Session, image: Image.Image, options: pipeline.Options | None = None) -> SessionView:
    """A closer photo, or a new area once the plan runs out: plan it and continue the same session."""
    photo, assessment = _analyze_photo(image, options)
    if assessment and (session.assessment is None or assessment.assigned_level > session.assessment.assigned_level):
        session.assessment = assessment  # keep the most cautious assessment
    session.complete_photo_step()
    steps, notes = triage.plan_steps(photo.analysis, session.assessment)
    session.add_plan(photo, steps, notes)

    session.history.append({"role": "user", "text": "(sent a new photo)"})
    reply = _ask_coach(session, "new_photo", None, None)
    message = reply.message or _template_message(session, None)
    session.history.append({"role": "coach", "text": message})
    return session.view(message, None)
