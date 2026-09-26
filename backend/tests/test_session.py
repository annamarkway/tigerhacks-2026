"""Triage validation, session state machine, and orchestrator flow with every LLM stubbed."""

import pytest
from PIL import Image

from app import orchestrator, triage
from app.schemas import (
    AnalysisResult, Assessment, Category, CoachReply, Complexity, Confidence, Density, FocusTask, Instance,
    Intent, ItemResult, SessionStatus, StepAction, StepStatus, TriagePlan, TriageStep, ZoneResult, ZoomSuggestion,
)


def _item(id, zone, cat, box, n=1):
    return ItemResult(id=id, zone_id=zone, label=id, category=cat,
                      instances=[Instance(bbox_px=box, score=1, source="detector") for _ in range(n)])


def _result(too_complex=False):
    # z1 desk (reachable), z2 shelf behind the z3 floor pile (blocked by z3), z3 floor pile (reachable)
    return AnalysisResult(
        image_size=(1000, 1000), scene_summary="s",
        complexity=Complexity(score=2, too_complex=too_complex, reason="r"),
        zones=[
            ZoneResult(id="z1", label="desk", bbox_px=(0, 0, 400, 400), density=Density.medium, suggested_first=True),
            ZoneResult(id="z2", label="shelf", bbox_px=(500, 0, 900, 300), density=Density.high, suggested_first=False,
                       accessible=False, blocked_by=["z3"]),
            ZoneResult(id="z3", label="floor pile", bbox_px=(500, 400, 900, 900), density=Density.high,
                       suggested_first=False, blocks_path=True),
            ZoneResult(id="z4", label="closet", bbox_px=(0, 600, 300, 900), density=Density.high,
                       suggested_first=False, accessible=False),
        ],
        items=[
            _item("cans", "z1", Category.trash_biohazard, (10, 10, 60, 90), n=5),
            _item("plate", "z1", Category.trash_biohazard, (80, 10, 200, 60)),
            _item("letters", "z1", Category.keep_sentimental, (300, 300, 380, 380)),
            _item("boxes", "z2", Category.recycling_paper, (520, 20, 700, 200)),
            _item("bags", "z3", Category.trash_biohazard, (520, 420, 880, 880)),
            _item("coats", "z4", Category.usable_belongings, (10, 610, 290, 890)),
            _item("shirts", "z1", Category.usable_belongings, (100, 200, 250, 300), n=6),
        ],
        exclude_regions_px=[], zoom_suggestion=ZoomSuggestion(zone_ids=["z3"], message="closer?") if too_complex else None,
        recommended_item_id="cans", first_step="Start with the cans.",
        focus=FocusTask(item_ids=["cans", "plate"], zone_id="z1", bbox_px=(0, 0, 220, 100), instruction="go"),
    )


def _step(id, items, zone, action=StepAction.bag, minutes=3):
    return TriageStep(id=id, item_ids=items, zone_id=zone, action=action, est_minutes=minutes, priority_reason="r")


def test_validate_orders_blocked_zone_after_its_blockers_and_filters_items():
    plan = TriagePlan(safety_notes=[], steps=[
        _step("s1", ["boxes"], "z2", StepAction.recycle),      # blocked by z3: must move after s3
        _step("s2", ["cans", "letters", "ghost"], "z1"),       # letters need a decision, ghost doesn't exist
        _step("s3", ["bags"], "z3"),
        _step("s4", ["coats"], "z4"),                             # z4 unreachable and nothing clears it
        _step("s5", ["cans"], "z1"),                           # cans already used -> empty -> dropped
        _step("s6", ["letters"], "z1", StepAction.set_aside),  # set_aside may include sentimental items
    ])
    steps = triage.validate_plan(plan, _result())
    assert [s.id for s in steps] == ["s2", "s3", "s1", "s6"]
    assert steps[0].item_ids == ["cans"]


def test_validate_falls_back_to_vision_focus_or_closer_photo():
    steps = triage.validate_plan(TriagePlan(steps=[], safety_notes=[]), _result())
    assert [(s.item_ids, s.action) for s in steps] == [(["cans", "plate"], StepAction.bag)]

    r = _result(too_complex=True)
    r.focus = None
    steps = triage.validate_plan(None, r)
    assert steps[0].action == StepAction.take_closer_photo and steps[0].zone_id == "z3"


ASSESSMENT = Assessment(
    assigned_level=2, color_code="Blue", severity="Guarded", primary_justifications=["food containers on desk"],
    required_ppe=["gloves"], intervention_requirements="x", confidence=Confidence.medium, unobservable=[],
)
PLAN = TriagePlan(safety_notes=["gloves for food containers"], steps=[
    _step("s1", ["cans", "plate"], "z1"),
    _step("s2", ["boxes"], "z2", StepAction.recycle),
    _step("s3", ["bags"], "z3"),
])


class FakeCoach:
    def __init__(self):
        self.replies: list[CoachReply] = []
        self.contexts: list[dict] = []

    def reply(self, context):
        self.contexts.append(context)
        return self.replies.pop(0) if self.replies else CoachReply(intent=Intent.support, message="hi")


@pytest.fixture
def coach(monkeypatch):
    fake = FakeCoach()
    monkeypatch.setattr(orchestrator.pipeline, "analyze", lambda image, options=None: _result())
    monkeypatch.setattr(orchestrator.classify_mod, "classify", lambda image: ASSESSMENT)
    monkeypatch.setattr(orchestrator.triage, "propose_plan", lambda result, assessment: PLAN)
    monkeypatch.setattr(orchestrator.coach_mod, "get_coach", lambda: fake)
    return fake


def _start(coach):
    view = orchestrator.start_session(Image.new("RGB", (1000, 1000)))
    return view, orchestrator.store.get(view.session_id)


def test_session_opening_and_done_skip_flow(coach):
    view, s = _start(coach)
    assert [p.step.id for p in s.steps] == ["p1-s1", "p1-s3", "p1-s2"]  # shelf after the floor pile
    assert view.current_step.step.id == "p1-s1"
    assert set(view.current_step.focus.item_ids) == {"cans", "plate"}
    assert view.assessment.required_ppe == ["gloves"] and view.assessment.level == 2
    assert not view.assessment.suggest_professional
    ctx = coach.contexts[0]
    assert ctx["turn"] == "opening" and ctx["assessment"]["level"] == 2
    assert ctx["next_step_if_done"]["zone"] == "floor pile"

    coach.replies = [CoachReply(intent=Intent.done, message="Nice.")]
    view = orchestrator.handle_message(s, "done!")
    assert view.intent == Intent.done and view.current_step.step.id == "p1-s3" and view.completed == 1
    ctx = s.coach_context("reply", "hmm")
    assert ctx["alternative_if_skip"] is None  # shelf is still blocked by the floor pile
    assert ctx["next_step_if_done"]["zone"] == "shelf"

    # Skipping the floor pile leaves the shelf blocked, so nothing is left.
    view = orchestrator.handle_message(s, None, Intent.skip)  # button: coach's intent is ignored
    assert s.get("p1-s3").status == StepStatus.skipped
    assert view.current_step is None and view.remaining == 1


def test_smaller_shrinks_current_step(coach):
    view, s = _start(coach)
    coach.replies = [CoachReply(intent=Intent.smaller, message="Just three cans.")]
    view = orchestrator.handle_message(s, "that's too much")
    assert [i.id for i in view.current_step.items] == ["cans"]
    assert len(view.current_step.items[0].instances) == 3
    assert view.current_step.focus.item_ids == ["cans"]


def test_crisis_overrides_reply_and_pauses(coach):
    _, s = _start(coach)
    coach.replies = [CoachReply(intent=Intent.support, message="I hear you.")]
    view = orchestrator.handle_message(s, "honestly I want to die")
    assert view.intent == Intent.crisis and view.status == SessionStatus.paused
    assert "988" in view.message and view.message.startswith("I hear you.")
    assert s.current.step.id == "p1-s1"  # nothing advanced


def test_coach_failure_falls_back_to_keywords(coach, monkeypatch):
    _, s = _start(coach)

    def boom(context):
        raise RuntimeError("down")

    monkeypatch.setattr(coach, "reply", boom)
    view = orchestrator.handle_message(s, "ok I'm done with those")
    assert view.intent == Intent.done and view.current_step.step.id == "p1-s3"
    assert "floor pile" not in view.message and "bags" in view.message


def test_wrap_up_after_budget(coach):
    _, s = _start(coach)
    s.started_at -= 13 * 60
    assert orchestrator.handle_message(s, "hmm") and coach.contexts[-1]["wrap_up"] is True


def test_add_photo_appends_steps_and_completes_photo_step(coach, monkeypatch):
    complex_result = _result(too_complex=True)
    complex_result.focus = None
    monkeypatch.setattr(orchestrator.pipeline, "analyze", lambda image, options=None: complex_result)
    monkeypatch.setattr(orchestrator.triage, "propose_plan", lambda result, assessment: None)
    view, s = _start(coach)
    assert view.current_step.step.action == StepAction.take_closer_photo
    assert view.current_step.focus.bbox_px == (500, 400, 900, 900)

    monkeypatch.setattr(orchestrator.pipeline, "analyze", lambda image, options=None: _result())
    monkeypatch.setattr(orchestrator.triage, "propose_plan", lambda result, assessment: PLAN)
    view = orchestrator.add_photo(s, Image.new("RGB", (1000, 1000)))
    assert s.get("p1-s1").status == StepStatus.done
    assert view.current_step.step.id == "p2-s1" and s.photos[1] is not None
    assert coach.contexts[-1]["turn"] == "new_photo"


def test_session_api_roundtrip(coach):
    import io

    from fastapi.testclient import TestClient

    from app.main import app

    buf = io.BytesIO()
    Image.new("RGB", (1000, 1000), "white").save(buf, format="JPEG")
    client = TestClient(app)
    r = client.post("/sessions", files={"image": ("room.jpg", buf.getvalue(), "image/jpeg")})
    assert r.status_code == 200, r.text
    view = r.json()
    sid, url = view["session_id"], view["current_step"]["image_url"]

    img = client.get(url)
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert client.get(url + "?style=box").status_code == 200

    r = client.post(f"/sessions/{sid}/messages", json={"action": "done"})
    assert r.status_code == 200 and r.json()["current_step"]["step"]["id"] == "p1-s3"
    assert client.post(f"/sessions/{sid}/messages", json={}).status_code == 400
    assert client.post("/sessions/nope/messages", json={"text": "hi"}).status_code == 404


def test_hazard_steps_cannot_be_skipped(coach, monkeypatch):
    hazard_plan = PLAN.model_copy(deep=True)
    hazard_plan.steps[0].hazard = True
    monkeypatch.setattr(orchestrator.triage, "propose_plan", lambda result, assessment: hazard_plan)
    _, s = _start(coach)
    assert coach.contexts[0]["current_step"]["hazard"] is True

    # Button skip -> smaller version, and the coach is told why.
    coach.replies = [CoachReply(intent=Intent.smaller, message="Let's just do three cans.")]
    view = orchestrator.handle_message(s, None, Intent.skip)
    ctx = coach.contexts[-1]
    assert ctx["forced_intent"] == "smaller" and ctx["skip_refused_for_safety"] is True
    assert view.intent == Intent.smaller and view.current_step.step.id == "p1-s1"

    # The model picks skip anyway -> held with fixed wording; already small, so support.
    coach.replies = [CoachReply(intent=Intent.skip, message="Sure, let's move on to the floor pile.")]
    view = orchestrator.handle_message(s, "I'd rather keep these, can we do something else?")
    assert view.intent == Intent.support and view.message == orchestrator.SAFETY_HOLD
    assert s.current.step.id == "p1-s1" and s.get("p1-s1").status == StepStatus.current


def test_usable_belongings_are_sorted_never_bagged():
    plan = TriagePlan(safety_notes=[], steps=[
        _step("s1", ["cans", "shirts"], "z1"),  # mixed: shirts are dropped from the bag step
        _step("s2", ["shirts"], "z1"),          # only usable belongings: bag becomes sort
    ])
    steps = triage.validate_plan(plan, _result())
    assert [(s.item_ids, s.action) for s in steps] == [(["cans"], StepAction.bag), (["shirts"], StepAction.sort)]

    r = _result()
    r.focus = FocusTask(item_ids=["shirts", "cans"], zone_id="z1", bbox_px=(0, 0, 250, 300), instruction="go")
    assert [(s.item_ids, s.action) for s in triage.fallback_steps(r)] == [(["shirts", "cans"], StepAction.sort)]
    r.focus.item_ids = ["cans", "shirts"]
    assert [(s.item_ids, s.action) for s in triage.fallback_steps(r)] == [(["cans"], StepAction.bag)]


def test_hazard_sort_step_hold_keeps_the_choice_theirs(coach, monkeypatch):
    plan = TriagePlan(safety_notes=[], steps=[
        TriageStep(id="s1", item_ids=["shirts"], zone_id="z1", action=StepAction.sort, est_minutes=3, hazard=True,
                   priority_reason="r"),
    ])
    monkeypatch.setattr(orchestrator.triage, "propose_plan", lambda result, assessment: plan)
    _, s = _start(coach)
    coach.replies = [CoachReply(intent=Intent.smaller, message="")]
    view = orchestrator.handle_message(s, None, Intent.skip)
    assert view.message == orchestrator.SAFETY_HOLD_SORT and "trash" not in view.message


def test_old_category_value_still_loads():
    assert Category("donate_textiles") is Category.usable_belongings
    assert Category("textiles") is Category.usable_belongings
