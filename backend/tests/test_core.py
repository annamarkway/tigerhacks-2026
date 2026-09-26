import numpy as np
from PIL import Image

from app.geometry import containment, iou, nms, scale_box
from app.pipeline import choose_focus, focus_from_result
from app.render import FOCUS_RED, render_focus, render_focus_tight, render_overview
from app.schemas import (
    AnalysisResult, Category, Complexity, Density, Instance, ItemGroup, ItemResult,
    SceneAnalysis, VlmBox, Zone, ZoneResult,
)
from app.segment import masks_to_polygon


def test_scale_box_maps_sent_pixels_to_original_and_clamps():
    # our_room.jpeg: Claude sees 1176x1568, original is 4284x5712
    assert scale_box(VlmBox(x1=137, y1=440, x2=391, y2=530), (1176, 1568), (4284, 5712)) == (499, 1603, 1424, 1931)
    assert scale_box(VlmBox(x1=60, y1=-5, x2=40, y2=120), (100, 100), (1000, 1000)) == (400, 0, 600, 1000)


def test_iou_containment_nms():
    a, b = (0, 0, 10, 10), (5, 0, 15, 10)
    assert abs(iou(a, b) - 1 / 3) < 1e-9
    assert containment((2, 2, 4, 4), a) == 1.0
    assert nms([a, (0, 0, 10, 9), b], [0.9, 0.8, 0.7], 0.5) == [0, 2]


def test_mask_to_polygon():
    m = np.zeros((50, 50), bool)
    m[10:30, 5:40] = True
    poly = masks_to_polygon(m)
    xs, ys = zip(*poly)
    assert min(xs) == 5 and max(xs) == 39 and min(ys) == 10 and max(ys) == 29
    assert masks_to_polygon(np.zeros((5, 5), bool)) is None


def _scene():
    box = VlmBox(x1=0, y1=0, x2=100, y2=100)
    return SceneAnalysis(
        scene_summary="s", room="living_room", furniture=["couch"],
        complexity=Complexity(score=2, too_complex=False, reason="r"),
        zones=[Zone(id="z1", label="table", box=box, density=Density.medium, suggested_first=True,
                    accessible=True, blocked_by=[], blocks_path=False, hazards=[]),
               Zone(id="z2", label="floor", box=box, density=Density.high, suggested_first=False,
                    accessible=False, blocked_by=["z1"], blocks_path=True, hazards=["cords under items"])],
        items=[ItemGroup(id="i1", zone_id="z1", label="cans", detector_phrase="soda can",
                         category=Category.trash_biohazard, count_estimate=2, boxes=[box])],
        exclude_regions=[], zoom_suggestion=None, focus_item_ids=["i1"], first_step="go",
    )


def _item(id, zone, cat, box):
    return ItemResult(id=id, zone_id=zone, label=id, category=cat,
                      instances=[Instance(bbox_px=box, score=1, source="detector")])


# Mirrors our_room.jpeg: snack corner in z1, papers and mail elsewhere.
ROOM = [
    _item("can", "z1", Category.trash_biohazard, (1700, 1690, 2015, 2247)),
    _item("plate", "z1", Category.trash_biohazard, (498, 1604, 1425, 1930)),
    _item("napkins", "z1", Category.trash_biohazard, (1909, 1877, 2678, 2528)),
    _item("bottle", "z1", Category.unsure, (2476, 1068, 2817, 2300)),
    _item("mail", "z1", Category.keep_sentimental, (100, 100, 400, 400)),
    _item("notepaper", "z2", Category.recycling_paper, (600, 3000, 1600, 3800)),
]


def test_focus_fallback_groups_lowest_tier_in_first_zone():
    f = choose_focus(ROOM, [], {"z1"}, "go", (4284, 5712))
    assert set(f.item_ids) == {"can", "plate", "napkins"}
    assert f.zone_id == "z1"
    assert all(containment(i.instances[0].bbox_px, f.bbox_px) == 1.0 for i in ROOM[:3])


def test_focus_honors_claude_ids_and_filters_bad_ones():
    f = choose_focus(ROOM, ["notepaper", "mail", "nope", "notepaper"], {"z1"}, "go", (4284, 5712))
    assert f.item_ids == ["notepaper"]
    assert choose_focus(ROOM, [], {"z1"}, "go", (4284, 5712), allow_fallback=False) is None


def test_focus_drops_far_outlier():
    far = _item("far_can", "z1", Category.trash_biohazard, (4000, 5400, 4200, 5700))
    f = choose_focus(ROOM + [far], [], {"z1"}, "go", (4284, 5712))
    assert "far_can" not in f.item_ids


def test_scene_schema_roundtrip():
    s = _scene()
    assert SceneAnalysis.model_validate_json(s.model_dump_json()) == s


def test_render_overview_runs():
    img = Image.new("RGB", (100, 80), (200, 50, 50))
    res = AnalysisResult(
        image_size=(100, 80), scene_summary="", complexity=Complexity(score=1, too_complex=False, reason=""),
        zones=[ZoneResult(id="z1", label="t", bbox_px=(0, 0, 50, 50), density=Density.low, suggested_first=True)],
        items=[ItemResult(id="i1", zone_id="z1", label="can", category=Category.trash_biohazard,
                          instances=[Instance(bbox_px=(10, 10, 40, 40), polygon=[(10, 10), (40, 10), (40, 40), (10, 40)], score=1, source="detector")])],
        exclude_regions_px=[(60, 0, 100, 40)], zoom_suggestion=None, recommended_item_id="i1", first_step="",
    )
    assert render_overview(img, res).size == (100, 80)


def test_render_focus_blurs_outside_and_frames_in_red():
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 255, (400, 600, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    res = AnalysisResult(
        image_size=(600, 400), scene_summary="", complexity=Complexity(score=1, too_complex=False, reason=""),
        zones=[], items=[_item("can", "z1", Category.trash_biohazard, (200, 150, 260, 230))],
        exclude_regions_px=[], zoom_suggestion=None, recommended_item_id=None, first_step="",
    )
    res.focus = focus_from_result(res)
    x1, y1, x2, y2 = res.focus.bbox_px
    out = np.asarray(render_focus(img, res))
    assert out[y1 + 20, x1 + 20].tolist() == arr[y1 + 20, x1 + 20].tolist()  # inside: untouched
    assert np.abs(out[:40, :40].astype(int) - arr[:40, :40]).mean() > 20     # outside: blurred/dimmed
    assert out[y1, (x1 + x2) // 2].tolist() == list(FOCUS_RED)               # frame is red


def test_render_focus_tight_keeps_only_the_object_sharp():
    rng = np.random.default_rng(1)
    arr = rng.integers(0, 255, (400, 600, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    tri = [(200, 150), (300, 150), (250, 300)]
    item = ItemResult(id="can", zone_id="z1", label="can", category=Category.trash_biohazard,
                      instances=[Instance(bbox_px=(200, 150, 300, 300), polygon=tri, score=1, source="detector")])
    res = AnalysisResult(
        image_size=(600, 400), scene_summary="", complexity=Complexity(score=1, too_complex=False, reason=""),
        zones=[], items=[item], exclude_regions_px=[], zoom_suggestion=None, recommended_item_id=None, first_step="",
    )
    res.focus = focus_from_result(res)
    out = np.asarray(render_focus_tight(img, res)).astype(int)
    assert out[180, 250].tolist() == arr[180, 250].tolist()        # inside the triangle: untouched
    assert np.abs(out[280, 205] - arr[280, 205]).sum() > 0          # inside the bbox but outside the shape: blurred
    assert (np.abs(out - FOCUS_RED).sum(axis=2) < 30).any()         # red outline drawn
