"""Data contracts for the image analysis pipeline.

`SceneAnalysis` is what Claude returns (structured output). `AnalysisResult` is what
the API returns to clients after grounding + segmentation.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Category(str, Enum):
    """Triage hierarchy, ordered from easiest/least-anxious to hardest."""

    trash_biohazard = "trash_biohazard"
    recycling_paper = "recycling_paper"
    usable_belongings = "usable_belongings"
    keep_sentimental = "keep_sentimental"
    unsure = "unsure"

    @classmethod
    def _missing_(cls, value):
        # Saved results from before the renames.
        return cls.usable_belongings if value in ("textiles", "donate_textiles") else None


CATEGORY_PRIORITY = {
    Category.trash_biohazard: 0,
    Category.recycling_paper: 1,
    Category.usable_belongings: 2,
    Category.unsure: 3,
    Category.keep_sentimental: 4,
}


class Density(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# ---------------------------------------------------------------------------
# VLM output (Claude). Boxes are pixel coords on the downscaled image Claude was sent.
# ---------------------------------------------------------------------------


class VlmBox(BaseModel):
    """Axis-aligned box in pixels of the image as sent to Claude (x right, y down)."""

    x1: int
    y1: int
    x2: int
    y2: int


class Complexity(BaseModel):
    score: int = Field(description="1 (one clear surface) to 5 (whole cluttered room)")
    too_complex: bool = Field(
        description="True when no single area could be cleared in ~10 minutes, so the user should zoom in"
    )
    reason: str


class Zone(BaseModel):
    id: str = Field(description="Short slug, e.g. 'z1'")
    label: str = Field(description="Plain description, e.g. 'table surface', 'floor in front of the sink'")
    box: VlmBox
    density: Density
    suggested_first: bool = Field(description="True for the single best zone to start with")
    accessible: bool = Field(description="Reachable right now without moving other things first")
    blocked_by: list[str] = Field(description="ids of zones whose items stand in the way; empty when accessible")
    blocks_path: bool = Field(description="Items narrow or block a walkway, doorway, exit, stairs, or appliance")
    hazards: list[str] = Field(description="Short factual observations of visible hazards; empty if none")


class ItemGroup(BaseModel):
    id: str = Field(description="Short slug, e.g. 'i1'")
    zone_id: str = Field(description="id of the zone this group sits in")
    label: str = Field(description="Specific name, e.g. 'aluminum soda cans'")
    detector_phrase: str = Field(
        description="2-4 word lowercase noun phrase for an open-vocabulary detector, e.g. 'soda can'"
    )
    category: Category
    count_estimate: int
    boxes: list[VlmBox] = Field(description="Approximate box per visible instance (or one box around a tight cluster)")


class ExcludeRegion(BaseModel):
    kind: str = Field(description="'person', 'pet', 'photo_of_person', or 'screen'")
    box: VlmBox


class ZoomSuggestion(BaseModel):
    zone_ids: list[str]
    message: str = Field(description="Warm, one or two sentence request to take a closer photo")


class SceneAnalysis(BaseModel):
    scene_summary: str
    complexity: Complexity
    zones: list[Zone]
    items: list[ItemGroup]
    exclude_regions: list[ExcludeRegion]
    zoom_suggestion: ZoomSuggestion | None
    focus_item_ids: list[str] = Field(
        description="ids of the 1-4 item groups that make up first_step; physically close together, usually one zone"
    )
    first_step: str = Field(description="One short, encouraging instruction for the easiest first action")


# ---------------------------------------------------------------------------
# Pipeline output. Pixel coords on the ORIGINAL image.
# ---------------------------------------------------------------------------


class Instance(BaseModel):
    bbox_px: tuple[int, int, int, int]
    polygon: list[tuple[int, int]] | None = None
    score: float
    source: str = Field(description="'detector' or 'vlm' (fallback)")


class ItemResult(BaseModel):
    id: str
    zone_id: str
    label: str
    category: Category
    instances: list[Instance]


class ZoneResult(BaseModel):
    id: str
    label: str
    bbox_px: tuple[int, int, int, int]
    density: Density
    suggested_first: bool
    accessible: bool = True
    blocked_by: list[str] = []
    blocks_path: bool = False
    hazards: list[str] = []


class FocusTask(BaseModel):
    """The single small task to show the user: a few nearby item groups inside one box."""

    item_ids: list[str]
    zone_id: str | None
    bbox_px: tuple[int, int, int, int] = Field(description="Padded union of the target instances")
    instruction: str


class AnalysisResult(BaseModel):
    image_size: tuple[int, int]
    scene_summary: str
    complexity: Complexity
    zones: list[ZoneResult]
    items: list[ItemResult]
    exclude_regions_px: list[tuple[int, int, int, int]]
    zoom_suggestion: ZoomSuggestion | None
    recommended_item_id: str | None
    first_step: str
    focus: FocusTask | None = None


# ---------------------------------------------------------------------------
# Session agents: classify (assessment), triage (plan), coach (conversation).
# ---------------------------------------------------------------------------


class Confidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Assessment(BaseModel):
    assigned_level: int = Field(description="ICD Clutter-Hoarding Scale level, 1-5")
    color_code: str
    severity: str
    primary_justifications: list[str] = Field(description="Visible observations that set this level")
    required_ppe: list[str]
    intervention_requirements: str
    confidence: Confidence
    unobservable: list[str] = Field(description="Relevant criteria that can't be judged from this photo")


class StepAction(str, Enum):
    bag = "bag"
    recycle = "recycle"
    sort = "sort"  # usable belongings: keep, or let go into the let-go bag; the person decides
    set_aside = "set_aside"
    take_closer_photo = "take_closer_photo"


class TriageStep(BaseModel):
    id: str = Field(description="Short slug, e.g. 's1'")
    item_ids: list[str] = Field(description="1-4 nearby item group ids; empty for take_closer_photo")
    zone_id: str
    action: StepAction
    est_minutes: int = Field(description="2-5")
    hazard: bool = Field(
        default=False,
        description=(
            "True when this step removes a safety hazard (food waste, sharps, spills, items blocking an exit or near heat); "
            "for a sort step, the items must leave the path but the person still decides keep or let go"
        ),
    )
    priority_reason: str


class TriagePlan(BaseModel):
    steps: list[TriageStep] = Field(description="In the order the person should do them")
    safety_notes: list[str]


class Intent(str, Enum):
    done = "done"
    skip = "skip"
    smaller = "smaller"
    support = "support"
    pause = "pause"
    question = "question"
    crisis = "crisis"


class CoachReply(BaseModel):
    intent: Intent
    message: str


class StepStatus(str, Enum):
    pending = "pending"
    current = "current"
    done = "done"
    skipped = "skipped"


class SessionStatus(str, Enum):
    active = "active"
    paused = "paused"
    finished = "finished"


class StepView(BaseModel):
    step: TriageStep
    focus: FocusTask | None = Field(description="None for take_closer_photo")
    items: list[ItemResult]
    image_url: str | None


class AssessmentSummary(BaseModel):
    """What the frontend may show alongside the coach's message."""

    level: int
    severity: str
    required_ppe: list[str]
    suggest_professional: bool


class SessionView(BaseModel):
    session_id: str
    status: SessionStatus
    intent: Intent | None
    message: str
    elapsed_min: float
    budget_min: int
    completed: int
    remaining: int
    assessment: AssessmentSummary | None
    current_step: StepView | None
