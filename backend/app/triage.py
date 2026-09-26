"""Triage agent: turns one analyzed photo + assessment into an ordered list of small steps.

Claude proposes the plan; code validates it (known ids, no decisions on sentimental items,
accessibility order) so a bad reply can't send the person into a zone they can't reach.
"""

from __future__ import annotations

import json
import logging
import os

from .llm import SceneAnalysisError, VLMUnavailableError, claude_parse
from .prompts import load
from .schemas import (
    AnalysisResult,
    Assessment,
    Category,
    ItemResult,
    StepAction,
    TriagePlan,
    TriageStep,
)

log = logging.getLogger(__name__)

DECISION_CATEGORIES = {Category.keep_sentimental, Category.unsure}
ACTION_FOR_CATEGORY = {
    Category.trash_biohazard: StepAction.bag,
    Category.recycling_paper: StepAction.recycle,
    Category.usable_belongings: StepAction.sort,
}
# Usable belongings are the person's decision: never planned straight into a trash bag or recycling.
USABLE_ACTIONS = {StepAction.sort, StepAction.set_aside}


def describe_scene(result: AnalysisResult, assessment: Assessment | None) -> str:
    """Compact JSON the triage model reads; no pixel data beyond what it needs."""
    doc = {
        "scene_summary": result.scene_summary,
        "too_complex": result.complexity.too_complex,
        "zoom_suggestion": result.zoom_suggestion.model_dump() if result.zoom_suggestion else None,
        "zones": [
            z.model_dump(include={"id", "label", "density", "suggested_first", "accessible", "blocked_by", "blocks_path", "hazards"})
            for z in result.zones
        ],
        "items": [
            {"id": i.id, "zone_id": i.zone_id, "label": i.label, "category": i.category.value, "count": len(i.instances)}
            for i in result.items
        ],
        "assessment": assessment.model_dump(include={"assigned_level", "severity", "primary_justifications", "required_ppe"})
        if assessment
        else None,
    }
    return json.dumps(doc, indent=1, default=str)


def propose_plan(result: AnalysisResult, assessment: Assessment | None) -> TriagePlan:
    model = os.environ.get("HOARD_TRIAGE_MODEL", "claude-sonnet-5")
    content = [{"type": "text", "text": f"Plan the session for this photo:\n\n{describe_scene(result, assessment)}"}]
    return claude_parse(model, load("triage"), content, TriagePlan, max_tokens=8000, what="Triage plan")


def dependencies(steps: list[TriageStep], result: AnalysisResult) -> dict[str, set[str]] | None:
    """Step id -> ids of steps that must be done first. None for a step whose zone can't be reached."""
    zones = {z.id: z for z in result.zones}
    deps: dict[str, set[str]] = {}
    for s in steps:
        zone = zones.get(s.zone_id)
        if s.action == StepAction.take_closer_photo or zone is None or zone.accessible:
            deps[s.id] = set()
            continue
        blockers = {b.id for b in steps if b.zone_id in zone.blocked_by and b.id != s.id}
        deps[s.id] = blockers if blockers else None  # blocked, and nothing in the plan clears the way
    return deps


def validate_plan(plan: TriagePlan | None, result: AnalysisResult) -> list[TriageStep]:
    """Filter the model's plan to steps the person can actually do, in an order that respects access."""
    items = {i.id: i for i in result.items if i.instances}
    zone_ids = {z.id for z in result.zones}
    used: set[str] = set()
    steps: list[TriageStep] = []
    for s in plan.steps if plan else []:
        if s.action == StepAction.take_closer_photo:
            if s.zone_id in zone_ids:
                steps.append(s.model_copy(update={"item_ids": []}))
            continue
        ids = [
            i for i in dict.fromkeys(s.item_ids)
            if i in items and i not in used
            and (items[i].category not in DECISION_CATEGORIES or s.action == StepAction.set_aside)
        ]
        action, ids = fit_action(s.action, ids, items)
        ids = ids[:4]
        if not ids:
            continue
        used.update(ids)
        zone_id = s.zone_id if s.zone_id in zone_ids else items[ids[0]].zone_id
        steps.append(s.model_copy(update={
            "item_ids": ids, "action": action, "zone_id": zone_id, "est_minutes": max(1, min(10, s.est_minutes)),
        }))

    # Unique ids (the model sometimes repeats "s1").
    seen: set[str] = set()
    for n, s in enumerate(steps):
        if s.id in seen:
            s.id = f"s{n + 1}"
        seen.add(s.id)

    if not steps:
        steps = fallback_steps(result)
    return order_by_access(steps, result)


def fit_action(action: StepAction, ids: list[str], items: dict[str, ItemResult]) -> tuple[StepAction, list[str]]:
    """Keep usable belongings out of bag/recycle steps: all-usable becomes sort, mixed drops the usable ones."""
    if action in USABLE_ACTIONS:
        return action, ids
    usable = [i for i in ids if items[i].category == Category.usable_belongings]
    if usable and len(usable) == len(ids):
        return StepAction.sort, ids
    return action, [i for i in ids if i not in usable]


def order_by_access(steps: list[TriageStep], result: AnalysisResult) -> list[TriageStep]:
    """Stable topological sort: keep the model's order, but never before a blocking zone's steps."""
    deps = dependencies(steps, result)
    remaining = [s for s in steps if deps[s.id] is not None]
    for s in steps:
        if deps[s.id] is None:
            log.info("Dropping step %s: zone %s is blocked and nothing in the plan clears it", s.id, s.zone_id)
    ordered: list[TriageStep] = []
    done: set[str] = set()
    while remaining:
        ready = next((s for s in remaining if deps[s.id] <= done), None)
        if ready is None:  # cycle; drop what's left rather than guess
            log.info("Dropping steps in a blocking cycle: %s", [s.id for s in remaining])
            break
        ordered.append(ready)
        done.add(ready.id)
        remaining.remove(ready)
    return ordered


def fallback_steps(result: AnalysisResult) -> list[TriageStep]:
    """One step from the vision pass's own focus, or a closer-photo step for a too-complex scene."""
    if result.focus and result.focus.item_ids:
        items = {i.id: i for i in result.items}
        first = items[result.focus.item_ids[0]]
        action, ids = fit_action(
            ACTION_FOR_CATEGORY.get(first.category, StepAction.bag), [i for i in result.focus.item_ids if i in items], items
        )
        return [
            TriageStep(
                id="s1",
                item_ids=ids,
                zone_id=result.focus.zone_id or first.zone_id,
                action=action,
                est_minutes=5,
                priority_reason="fallback: vision first step",
            )
        ]
    if result.zoom_suggestion and result.zoom_suggestion.zone_ids:
        return [
            TriageStep(
                id="s1",
                item_ids=[],
                zone_id=result.zoom_suggestion.zone_ids[0],
                action=StepAction.take_closer_photo,
                est_minutes=1,
                priority_reason="fallback: scene too complex",
            )
        ]
    return []


def plan_steps(result: AnalysisResult, assessment: Assessment | None) -> tuple[list[TriageStep], list[str]]:
    """Propose + validate. Falls back to the vision pass's focus if the triage call fails."""
    try:
        plan = propose_plan(result, assessment)
    except (SceneAnalysisError, VLMUnavailableError):
        log.exception("Triage call failed; using the vision pass's first step")
        plan = None
    return validate_plan(plan, result), (plan.safety_notes if plan else [])
