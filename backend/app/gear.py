"""Practical protective gear to suggest, derived from the assessment.

The classifier returns the ICD scale's full PPE list for a level (bouffant caps, shoe covers,
insect repellent, first aid kits...). Most of that is for professional crews; a person clearing
one small spot needs a short list of things people commonly have. Uncommon gear is only
suggested at the levels where the situation calls for it, and gloves only when something in the
photo calls for them: the classifier lists gloves at every level, and suggesting them for a pile
of books makes an easy job sound dangerous.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .schemas import Assessment

# Visible hazards (the vision pass's per-zone notes) that hands would touch.
HAND_HAZARD_RE = re.compile(
    r"\b(food|residue|rott\w*|spoil\w*|mold\w*|mould\w*|spill\w*|leak\w*|sticky|liquid|stain\w*|"
    r"broken|shatter\w*|shard\w*|glass|sharp|needle\w*|syringe\w*|razor\w*|blade\w*|nail\w*|rust\w*|"
    r"waste|droppings|feces|urine|pest\w*|insect\w*|bugs?|roach\w*|rodent\w*|mice|chemical\w*|bleach)\b",
    re.IGNORECASE,
)


def needs_gloves(hazards: Iterable[str]) -> bool:
    return any(HAND_HAZARD_RE.search(h) for h in hazards)


def practical_gear(assessment: Assessment | None, hazards: Iterable[str] = ()) -> list[str]:
    """`hazards` are the visible hazards in the session's photos."""
    if assessment is None:
        return []
    level = assessment.assigned_level
    listed = " ".join(assessment.required_ppe).lower()
    gear: list[str] = []
    if "glove" in listed and (level >= 4 or needs_gloves(hazards)):
        gear.append("gloves")
    if level >= 3 and ("mask" in listed or "respirator" in listed):
        gear.append("an N95 mask" if level >= 4 else "a dust mask")
    if level >= 3 and ("boot" in listed or "work shoe" in listed):
        gear.append("closed-toe shoes")
    if level >= 4 and ("goggle" in listed or "glasses" in listed):
        gear.append("safety glasses")
    # Only for heavy contamination (human or animal waste, pervasive mold).
    if level >= 5 and "coverall" in listed:
        gear.append("disposable coveralls")
    if level >= 5 and "shoe cover" in listed:
        gear.append("shoe covers")
    return gear
