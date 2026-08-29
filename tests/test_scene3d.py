"""Tests for the 3D view: derived dimensions, payload shape and wiring.

The renderer itself needs a browser, but the things most likely to break
silently do not: a tyre code parsed wrongly, a pose channel missing from the
response, or a script reaching for an element id that no template contains.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from web.machine_geometry import machine_geometry, parse_tyre
from web.schemas import SimulationRequest
from web.simulation import run_simulation

REPO = Path(__file__).resolve().parent.parent


# --- tyre codes are real data ---------------------------------------------

@pytest.mark.parametrize("code,diameter", [
    ("480/80R50", 2.038),   # 50 in rim + 2 x 480 mm x 0.80
    ("800/70R38", 2.085),
    ("420/85R34", 1.578),
    ("650/65R42", 1.912),
    ("200/70R16", 0.686),
])
def test_metric_tyre_diameter(code, diameter):
    tyre = parse_tyre(code)
    assert tyre.diameter == pytest.approx(diameter, abs=0.002)
    assert tyre.assumed_aspect is False


@pytest.mark.parametrize("code", ["18.4R34", "16.9-28", "11.00-20", "7.5-18"])
def test_imperial_tyres_flag_their_assumed_aspect(code):
    """Imperial codes carry no aspect ratio, so one is assumed and marked."""
    tyre = parse_tyre(code)
    assert tyre is not None
    assert tyre.assumed_aspect is True
    assert 0.6 < tyre.diameter < 2.2


@pytest.mark.parametrize("code", [None, "", "not-a-tyre", "480/80", "R50"])
def test_unparseable_codes_return_none_rather_than_guessing(code):
    assert parse_tyre(code) is None


def test_larger_tractors_get_larger_wheels():
    from aggsim.catalog import load_catalog
    catalog = load_catalog()
    small = machine_geometry(catalog.tractor("jd_5075e"), None, None)
    large = machine_geometry(catalog.tractor("jd_8r_410"), None, None)
    assert large["rear_wheel"]["diameter"] > small["rear_wheel"]["diameter"]
    assert large["wheelbase"]["value"] > small["wheelbase"]["value"]


# --- payload ---------------------------------------------------------------

def test_scene_payload_carries_the_poses_the_renderer_needs():
    out = run_simulation(SimulationRequest(
        tractor="jd_6145r", implement="jd_1775nt_16row30",
        slope_deg=10.0, duration=20.0), 40000)
    series = out["series"]
    for channel in ("x", "y", "theta", "delta_rad", "theta_implement"):
        assert channel in series, channel
        assert len(series[channel]) == len(series["t"])

    scene = out["scene"]
    assert scene["slope_deg"] == 10.0
    machine = scene["machine"]
    assert machine["implement"]["type"] == "trailed"
    assert machine["implement"]["working_width"]["sourced"] is True


def test_scene_payload_without_an_implement():
    out = run_simulation(SimulationRequest(tractor="jd_6145r", duration=20.0), 40000)
    assert out["scene"]["machine"]["implement"] is None
    assert "theta_implement" not in out["series"]


def test_drawing_only_dimensions_are_marked_as_such():
    """A dimension invented for the picture must not read as a specification."""
    from aggsim.catalog import load_catalog
    catalog = load_catalog()
    machine = machine_geometry(catalog.tractor("jd_8r_410"), None, None)

    assert machine["wheelbase"]["sourced"] is True
    assert machine["rear_wheel"]["sourced"] is True
    assert machine["track_width"]["sourced"] is False
    assert machine["body"]["sourced"] is False
    for name in ("track_width", "body", "hitch_distance", "implement_wheelbase"):
        assert name in machine["drawing_only"]


# --- wiring ----------------------------------------------------------------

def _template_text() -> str:
    return "\n".join(p.read_text() for p in (REPO / "web" / "templates").glob("*.html"))


def test_every_element_id_the_scripts_reach_for_exists():
    """Catches a typo in an id, which would otherwise fail only in a browser."""
    templates = _template_text()
    for script in ["app.js", "scene3d.js"]:
        source = (REPO / "web" / "static" / "js" / script).read_text()
        for element_id in set(re.findall(r'getElementById\("([^"]+)"\)', source)):
            assert f'id="{element_id}"' in templates, f"{script} wants #{element_id}"


def test_scene_script_declares_the_global_the_app_uses():
    scene = (REPO / "web" / "static" / "js" / "scene3d.js").read_text()
    app = (REPO / "web" / "static" / "js" / "app.js").read_text()
    assert "window.GuidanceScene" in scene
    assert "window.GuidanceScene" in app


def test_scene_script_is_served_before_the_app_script():
    base = (REPO / "web" / "templates" / "base.html").read_text()
    assert base.index("scene3d.js") < base.index("js/app.js")


def test_no_third_party_library_is_loaded():
    """The content security policy forbids it, and nothing here needs one."""
    for script in (REPO / "web" / "static" / "js").glob("*.js"):
        text = script.read_text()
        assert "http://" not in text and "https://" not in text
        for lib in ("three.min", "THREE.", "babylon", "import(", "importScripts"):
            assert lib not in text, f"{script.name} pulls in {lib}"


def test_playback_respects_reduced_motion():
    app = (REPO / "web" / "static" / "js" / "app.js").read_text()
    assert "prefers-reduced-motion" in app
    assert "setPlaying(!reduceMotion)" in app


def test_canvas_has_a_text_alternative_that_updates():
    templates = _template_text()
    assert 'id="scene"' in templates and 'role="img"' in templates
    app = (REPO / "web" / "static" / "js" / "app.js").read_text()
    assert 'setAttribute("aria-label"' in app


# --- regression guards for the camera and clipping defects -----------------

def _scene_source() -> str:
    return (REPO / "web" / "static" / "js" / "scene3d.js").read_text()


def test_camera_builds_an_orthonormal_basis_rather_than_rotating_by_hand():
    """The first version rotated points by yaw then pitch directly, which made
    the top view nearly horizontal. A forward, right and up basis fixes it."""
    src = _scene_source()
    assert "Scene.prototype.basis" in src
    assert "cross(f, [0, 0, 1])" in src
    assert "cross(r, f)" in src


def test_pitch_is_clamped_below_a_right_angle():
    """At exactly 90 degrees the right vector degenerates."""
    src = _scene_source()
    assert "Math.min(1.48" in src


def test_near_plane_clips_polygons_instead_of_dropping_faces():
    """Dropping a whole face let survivors project at a thousand pixels per
    metre, which is what filled the screen with a dark tyre."""
    src = _scene_source()
    assert "function clipNear" in src
    assert "var NEAR" in src


def test_backface_culling_is_applied():
    src = _scene_source()
    assert "Backface culling" in src


def test_three_camera_presets_are_defined():
    src = _scene_source()
    assert "applyPreset" in src
    for mode in ("chase", "side", "top"):
        assert '"' + mode + '"' in src

    app = (REPO / "web" / "static" / "js" / "app.js").read_text()
    assert "scene.applyPreset(btn.getAttribute(\"data-view\"))" in app


def test_implement_draft_class_reaches_the_renderer():
    """Tools drawn along the bar depend on it."""
    from aggsim.catalog import load_catalog
    from aggsim.model import implement_from_catalog

    catalog = load_catalog()
    imp = catalog.implement("jd_1775nt_16row30")
    machine = machine_geometry(catalog.tractor("jd_6145r"), imp,
                               implement_from_catalog(imp))
    assert "draft_class" in machine["implement"]
    assert machine["implement"]["draft_class"]


# --- appearance ------------------------------------------------------------

def test_verified_liveries_carry_a_source():
    from web.appearance import LIVERY, IMPLEMENT_LIVERY

    for table in (LIVERY, IMPLEMENT_LIVERY):
        for name, livery in table.items():
            if livery["verified"]:
                assert livery["source"], f"{name} claims verified with no source"
            else:
                assert livery["source"] is None, f"{name} has a source but is not verified"


def test_known_brand_colours_are_the_published_ones():
    """Getting John Deere green wrong would be visible instantly."""
    from web.appearance import livery_for

    assert livery_for("John Deere")["body"].upper() == "#367C2B"
    assert livery_for("John Deere")["wheel"].upper() == "#FFDE00"
    assert livery_for("Case IH")["body"].upper() == "#D0002D"
    assert livery_for("New Holland")["body"].upper() == "#003F7D"
    assert livery_for("Massey Ferguson")["body"].upper() == "#C71121"


def test_every_catalog_manufacturer_has_a_livery():
    from aggsim.catalog import load_catalog
    from web.appearance import DEFAULT_LIVERY, livery_for

    catalog = load_catalog()
    for tractor in catalog.tractors.values():
        assert livery_for(tractor.manufacturer) is not DEFAULT_LIVERY, tractor.manufacturer
    for implement in catalog.implements.values():
        assert livery_for(implement.manufacturer, implement=True) is not DEFAULT_LIVERY, \
            implement.manufacturer


def test_liveries_are_valid_hex_colours():
    from web.appearance import IMPLEMENT_LIVERY, LIVERY

    for table in (LIVERY, IMPLEMENT_LIVERY):
        for name, livery in table.items():
            for key in ("body", "trim", "wheel", "roof"):
                value = livery[key]
                assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), f"{name}.{key} = {value}"


def test_machines_of_different_size_get_different_shapes():
    from aggsim.catalog import load_catalog
    from web.appearance import profile_for

    catalog = load_catalog()
    assert profile_for(catalog.tractor("jd_5075e"))[0] == "utility"
    assert profile_for(catalog.tractor("jd_8r_410"))[0] == "rowcrop"
    assert profile_for(catalog.tractor("monarch_mk_v"))[0] == "electric"


def test_the_electric_machine_has_no_exhaust_stack():
    from aggsim.catalog import load_catalog
    from web.appearance import profile_for

    _, profile = profile_for(load_catalog().tractor("monarch_mk_v"))
    assert profile["exhaust"] == "none"


def test_livery_reaches_the_payload_with_its_provenance():
    out = run_simulation(SimulationRequest(
        tractor="fendt_724_vario", implement="kuhn_excelerator_8005_50",
        duration=10.0), 40000)
    machine = out["scene"]["machine"]
    assert machine["livery"]["verified"] is True
    assert machine["livery"]["source"]
    assert machine["implement"]["livery"]["body"]


def test_appearance_cannot_change_a_result():
    """Two runs differing only in livery must be numerically identical."""
    from web import appearance

    a = run_simulation(SimulationRequest(tractor="jd_6145r", duration=20.0), 40000)
    original = appearance.LIVERY["John Deere"]
    appearance.LIVERY["John Deere"] = appearance.DEFAULT_LIVERY
    try:
        b = run_simulation(SimulationRequest(tractor="jd_6145r", duration=20.0), 40000)
    finally:
        appearance.LIVERY["John Deere"] = original
    assert a["summary"] == b["summary"]
    assert a["series"]["cross_track"] == b["series"]["cross_track"]


def test_the_base_plane_is_not_drawn_over_the_photograph():
    """A regression guard for a bug that made the imagery look as though it
    had never loaded.

    The aerial photograph is painted as a background pass before the
    depth-sorted faces. An opaque 800 m base plane was being pushed into that
    sorted list, so it drew straight over the photograph. The base plane must
    only enter the sorted list when there is no imagery; with imagery it is
    drawn inside the background pass, underneath.
    """
    src = _scene_source()
    build = src[src.index("function buildGround"):src.index("function edgePair")]
    assert "if (!textured) {" in build, "the base plane is unconditional again"

    ground = src[src.index("Scene.prototype.drawGround"):src.index("Scene.prototype.draw =")]
    assert "under the photograph rather than over it" in ground
    assert "screen(cx - 400, -400)" in ground, "no far field beneath the imagery"


def test_the_renderer_samples_an_image_not_a_canvas():
    """The client now loads one NAIP photograph rather than compositing tiles."""
    src = _scene_source()
    assert "terrain.patch.image" in src
    assert "terrain.patch.canvas" not in src
