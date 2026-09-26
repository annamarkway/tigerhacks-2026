"""Session state machine: which step is current, what 'done' / 'skip' / 'smaller' do.

Pure code with no LLM calls, so every transition is testable. The orchestrator asks the
coach for an intent, then applies it here.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field

from PIL import Image

from .gear import practical_gear
from .homes import home_for
from .pipeline import choose_focus
from .schemas import (
    AnalysisResult,
    Assessment,
    AssessmentSummary,
    FocusTask,
    ItemHomeView,
    Intent,
    ItemResult,
    SessionStatus,
    SessionView,
    StepAction,
    StepStatus,
    StepView,
    TriageStep,
)
from .triage import dependencies, estimate_minutes

BUDGET_MIN = 15
WRAP_UP_MIN = 12
SMALLER_MAX_INSTANCES = 3
HISTORY_TURNS = 10

CRISIS_RE = re.compile(
    r"\b(kill(ing)? myself|suicid\w*|end (it all|my life)|don'?t want to (live|be alive|be here)|"
    r"hurt(ing)? myself|self[- ]harm|want to die)\b",
    re.IGNORECASE,
)
CRISIS_RESOURCES = (
    "You don't have to handle this alone. If you're in the US, you can call or text 988 to reach the "
    "Suicide & Crisis Lifeline any time, day or night. Outside the US, findahelpline.com lists free, "
    "confidential lines. If you're in immediate danger, please call your local emergency number. "
    "The cleaning can wait; you matter more."
)


@dataclass
class Photo:
    image: Image.Image
    analysis: AnalysisResult


@dataclass
class PlannedStep:
    step: TriageStep
    photo_idx: int
    deps: set[str]
    status: StepStatus = StepStatus.pending
    smaller: bool = False


@dataclass
class Session:
    id: str
    photos: list[Photo]
    assessment: Assessment | None
    steps: list[PlannedStep]
    safety_notes: list[str] = field(default_factory=list)
    current_id: str | None = None
    status: SessionStatus = SessionStatus.active
    started_at: float = field(default_factory=time.time)
    history: list[dict] = field(default_factory=list)
    budget_min: int = BUDGET_MIN

    # --- plan -------------------------------------------------------------

    def add_plan(self, photo: Photo, steps: list[TriageStep], safety_notes: list[str]) -> None:
        """Append a photo's validated steps. Step ids are prefixed per photo so they stay unique."""
        self.photos.append(photo)
        idx = len(self.photos) - 1
        prefix = f"p{idx + 1}-"
        deps = dependencies(steps, photo.analysis)
        for s in steps:
            self.steps.append(
                PlannedStep(
                    step=s.model_copy(update={"id": prefix + s.id}),
                    photo_idx=idx,
                    deps={prefix + d for d in deps.get(s.id) or set()},
                )
            )
        self.safety_notes = list(dict.fromkeys(self.safety_notes + safety_notes))
        if self.current is None:
            self._advance()

    @property
    def current(self) -> PlannedStep | None:
        return self.get(self.current_id) if self.current_id else None

    def get(self, step_id: str) -> PlannedStep | None:
        return next((p for p in self.steps if p.step.id == step_id), None)

    def next_available(self, *, assume_done: str | None = None, exclude: str | None = None) -> PlannedStep | None:
        """First pending step whose blockers are done (optionally pretending `assume_done` is done)."""
        done = {p.step.id for p in self.steps if p.status == StepStatus.done}
        if assume_done:
            done.add(assume_done)
        for p in self.steps:
            if p.status == StepStatus.pending and p.step.id not in (exclude, assume_done) and p.deps <= done:
                return p
        return None

    def _advance(self) -> None:
        nxt = self.next_available()
        self.current_id = nxt.step.id if nxt else None
        if nxt:
            nxt.status = StepStatus.current

    # --- transitions ------------------------------------------------------

    def apply(self, intent: Intent) -> None:
        cur = self.current
        if intent == Intent.done and cur:
            cur.status = StepStatus.done
            self._advance()
        elif intent == Intent.skip and cur:
            cur.status = StepStatus.skipped
            self._advance()
        elif intent == Intent.smaller and cur:
            cur.smaller = True
        elif intent in (Intent.pause, Intent.crisis):
            self.status = SessionStatus.paused
        if intent not in (Intent.pause, Intent.crisis) and self.status == SessionStatus.paused:
            self.status = SessionStatus.active

    def complete_photo_step(self) -> None:
        """A new photo arrived: a pending take_closer_photo step is now done."""
        cur = self.current
        if cur and cur.step.action == StepAction.take_closer_photo:
            cur.status = StepStatus.done
            self.current_id = None

    # --- time -------------------------------------------------------------

    @property
    def hazards(self) -> list[str]:
        """Every visible hazard in the session's photos."""
        return [h for photo in self.photos for z in photo.analysis.zones for h in z.hazards]

    @property
    def gear(self) -> list[str]:
        return practical_gear(self.assessment, self.hazards)

    @property
    def elapsed_min(self) -> float:
        return (time.time() - self.started_at) / 60

    @property
    def wrap_up(self) -> bool:
        done_min = sum(p.step.est_minutes for p in self.steps if p.status == StepStatus.done)
        return self.elapsed_min >= WRAP_UP_MIN or done_min >= WRAP_UP_MIN

    # --- per-step geometry --------------------------------------------------

    def step_items(self, p: PlannedStep) -> list[ItemResult]:
        by_id = {i.id: i for i in self.photos[p.photo_idx].analysis.items}
        items = [by_id[i] for i in p.step.item_ids if i in by_id]
        if p.smaller and items:
            first = items[0]
            items = [first.model_copy(update={"instances": first.instances[:SMALLER_MAX_INSTANCES]})]
        return items

    def step_homes(self, p: PlannedStep) -> list[ItemHomeView]:
        if p.step.action != StepAction.group:
            return []
        room = self.photos[p.photo_idx].analysis.room
        return [
            ItemHomeView(item_id=i.id, label=i.label, **home_for(i.label, room).model_dump())
            for i in self.step_items(p)
        ]

    def homes_set_up(self) -> list[str]:
        """Homes finished earlier this session, so the coach can say 'into the cable box you started'."""
        homes = [h for p in self.steps if p.status == StepStatus.done for h in self.step_homes(p)]
        return list(dict.fromkeys(f"{h.box_label} box" if h.box_label else h.home for h in homes))

    def step_focus(self, p: PlannedStep) -> FocusTask | None:
        analysis = self.photos[p.photo_idx].analysis
        if p.step.action == StepAction.take_closer_photo:
            zone = next((z for z in analysis.zones if z.id == p.step.zone_id), None)
            return FocusTask(item_ids=[], zone_id=zone.id, bbox_px=zone.bbox_px, instruction="") if zone else None
        items = self.step_items(p)
        if not items:
            return None
        return choose_focus(items, [i.id for i in items], set(), "", analysis.image_size, allow_fallback=False)

    # --- what the coach and the frontend see --------------------------------

    def describe_step(self, p: PlannedStep | None, *, smaller: bool = False) -> dict | None:
        if p is None:
            return None
        analysis = self.photos[p.photo_idx].analysis
        zone = next((z for z in analysis.zones if z.id == p.step.zone_id), None)
        view = PlannedStep(p.step, p.photo_idx, p.deps, p.status, smaller or p.smaller)
        items = self.step_items(view)
        homes = {h.item_id: h for h in self.step_homes(view)}
        return {
            "action": p.step.action.value,
            "hazard": p.step.hazard,
            "room": analysis.room.value,
            "furniture": analysis.furniture,
            "zone": zone.label if zone else None,
            "zone_hazards": zone.hazards if zone else [],
            "items": [
                {"label": i.label, "category": i.category.value, "count": len(i.instances)}
                | (homes[i.id].model_dump(include={"home", "fallback", "box_label", "tip"}) if i.id in homes else {})
                for i in items
            ],
            "est_minutes": estimate_minutes(p.step.action, sum(max(1, len(i.instances)) for i in items))
            if (smaller or p.smaller)
            else p.step.est_minutes,
        }

    def coach_context(
        self,
        turn: str,
        latest_message: str | None = None,
        forced_intent: Intent | None = None,
        skip_refused_for_safety: bool = False,
    ) -> dict:
        cur = self.current
        a = self.assessment
        nxt = self.next_available(assume_done=cur.step.id) if cur else None
        return {
            "turn": turn,
            # No level or severity: the person never hears a classification.
            "assessment": (
                {"suggest_professional": a.assigned_level >= 4, "gear": self.gear,
                 "observations": a.primary_justifications}
                if a else None
            ),
            "safety_notes": self.safety_notes,
            "current_step": self.describe_step(cur),
            "next_step_if_done": self.describe_step(nxt),
            "alternative_if_skip": self.describe_step(self.next_available(exclude=cur.step.id) if cur else None),
            "smaller_version": self.describe_step(cur, smaller=True) if cur and not cur.smaller else None,
            "elapsed_min": round(self.elapsed_min, 1),
            "wrap_up": self.wrap_up,
            "homes_set_up": self.homes_set_up(),
            # A trash bag stays open across steps; tying it off only makes sense when the session ends.
            "session_ending": self.wrap_up or cur is None or nxt is None,
            "recent_conversation": self.history[-HISTORY_TURNS:],
            "latest_message": latest_message,
            "forced_intent": forced_intent.value if forced_intent else None,
            "skip_refused_for_safety": skip_refused_for_safety,
        }

    def view(self, message: str, intent: Intent | None) -> SessionView:
        cur = self.current
        a = self.assessment
        return SessionView(
            session_id=self.id,
            status=self.status,
            intent=intent,
            message=message,
            elapsed_min=round(self.elapsed_min, 1),
            budget_min=self.budget_min,
            completed=sum(p.status == StepStatus.done for p in self.steps),
            remaining=sum(p.status in (StepStatus.pending, StepStatus.current) for p in self.steps),
            assessment=(
                AssessmentSummary(level=a.assigned_level, severity=a.severity, required_ppe=self.gear,
                                  suggest_professional=a.assigned_level >= 4)
                if a else None
            ),
            current_step=(
                StepView(
                    step=cur.step,
                    focus=self.step_focus(cur),
                    items=self.step_items(cur),
                    image_url=f"/sessions/{self.id}/steps/{cur.step.id}/focus.jpg",
                    photo_index=cur.photo_idx,
                    image_size=self.photos[cur.photo_idx].analysis.image_size,
                    zone_label=next(
                        (z.label for z in self.photos[cur.photo_idx].analysis.zones if z.id == cur.step.zone_id), None
                    ),
                    smaller=cur.smaller,
                    homes=self.step_homes(cur),
                )
                if cur else None
            ),
        )


def is_crisis(text: str | None) -> bool:
    return bool(text and CRISIS_RE.search(text))


class SessionStore:
    """In-memory sessions with a TTL. Images live only here, never on disk."""

    def __init__(self, ttl_s: float = 3600) -> None:
        self._ttl = ttl_s
        self._sessions: dict[str, tuple[float, Session]] = {}
        self._lock = threading.Lock()

    def new_id(self) -> str:
        return uuid.uuid4().hex

    def put(self, s: Session) -> None:
        with self._lock:
            self._evict()
            self._sessions[s.id] = (time.time(), s)

    def get(self, sid: str) -> Session | None:
        with self._lock:
            self._evict()
            entry = self._sessions.get(sid)
            if entry is None:
                return None
            self._sessions[sid] = (time.time(), entry[1])
            return entry[1]

    def delete(self, sid: str) -> bool:
        with self._lock:
            return self._sessions.pop(sid, None) is not None

    def _evict(self) -> None:
        cutoff = time.time() - self._ttl
        for sid in [k for k, (t, _) in self._sessions.items() if t < cutoff]:
            del self._sessions[sid]
