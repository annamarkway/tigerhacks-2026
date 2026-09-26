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
    donate_textiles = "donate_textiles"
    keep_sentimental = "keep_sentimental"
    unsure = "unsure"


CATEGORY_PRIORITY = {
    Category.trash_biohazard: 0,
    Category.recycling_paper: 1,
    Category.donate_textiles: 2,
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
