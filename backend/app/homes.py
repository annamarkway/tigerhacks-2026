"""Homes for usable belongings: which box, drawer, pile, or room each kind of item goes to.

Group steps give like items one home (cables in a labeled cable box, clothes in the laundry
basket, dishes to the kitchen) instead of asking the person to decide about each item. An entry
can override its home per room (a pillow goes on the couch in the living room, on the bed in the
bedroom). The lookup table lives in prompts/homes.json so it can be edited without touching code.
"""

from __future__ import annotations

import json
import re
from functools import cache

from .prompts import PROMPT_DIR
from .schemas import ItemHome, Room


@cache
def _table() -> tuple[list[tuple[re.Pattern, dict]], dict]:
    doc = json.loads((PROMPT_DIR / "homes.json").read_text())
    entries = []
    for e in doc["homes"]:
        words = "|".join(re.escape(k) for k in e["keywords"])
        entries.append((re.compile(rf"\b(?:{words})(?:e?s)?\b", re.IGNORECASE), e))
    return entries, doc["default"]


def home_for(label: str, room: Room | None = None) -> ItemHome:
    """First matching entry wins; anything unmatched gets a box labeled with what's inside."""
    entries, default = _table()
    entry = next((e for pattern, e in entries if pattern.search(label)), default)
    if room is not None:
        entry = entry | entry.get("rooms", {}).get(room.value, {})
    return ItemHome(
        kind=entry["kind"], home=entry["home"], fallback=entry["fallback"], box_label=entry.get("box_label"),
        tip=entry.get("tip"),
    )
