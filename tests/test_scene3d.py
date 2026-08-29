"""Tests for the 3D view: derived dimensions, payload shape and wiring.

The renderer itself needs a browser, but the things most likely to break
silently do not: a tyre code parsed wrongly, a pose channel missing from the
response, or a script reaching for an element id that no template contains.
"""

from __future__ import annotations

import re
import sys
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


# The SVG namespace is an identifier that createElementNS requires, not an
# address anything is fetched from. It is the one permitted URL-shaped string.
SVG_NS = "http://www.w3.org/2000/svg"


def _external_urls(text: str) -> list[str]:
    return [
        m for m in re.findall(r'https?://[^\s"\')]+', text)
        if not m.startswith(SVG_NS)
    ]


def test_no_third_party_library_is_loaded():
    """The content security policy forbids it, and nothing here needs one."""
    for script in (REPO / "web" / "static" / "js").glob("*.js"):
        text = script.read_text()
        assert _external_urls(text) == [], script.name
        for lib in ("three.min", "THREE.", "babylon", "importScripts"):
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




# --- realism pass ----------------------------------------------------------









# --- the WebGL renderer ----------------------------------------------------
#
# The canvas 2D renderer it replaced had three standing limits: faces sorted by
# centroid so intersecting geometry could sort wrongly, flat shading, and an
# affine texture map over small quads because canvas has no projective
# transform. These check that the replacement actually removes them rather than
# reproducing them in a different API.


def test_depth_testing_replaces_sorting_by_centroid():
    """A depth buffer is the whole reason for the rewrite."""
    src = _scene_source()
    assert "gl.enable(gl.DEPTH_TEST)" in src
    assert "list.sort" not in src, "faces are being sorted again"


def test_culling_is_off_and_lighting_is_two_sided():
    """Culling would demand every quad in the file be wound consistently, and
    one mistake silently deletes a face. Off, the shader must light both
    sides or a back face renders black."""
    src = _scene_source()
    assert "gl.disable(gl.CULL_FACE)" in src
    assert "gl.cullFace" not in src
    assert "gl_FrontFacing" in src


def test_the_ground_is_textured_by_uv_not_by_subdivision():
    """Texture coordinates are perspective correct in a shader, so the affine
    triangle mapping the canvas version needed is gone."""
    src = _scene_source()
    assert "attribute vec2 aUV" in src
    assert "texture2D(uTex" in src
    assert "texTriangle" not in src, "the affine workaround is back"


def test_lighting_is_per_pixel_with_a_specular_term():
    src = _scene_source()
    assert "precision mediump float" in src
    assert "pow(lambert" in src
    assert "max(dot(n, uLight), 0.0)" in src


def test_the_shadow_darkens_the_ground_once():
    """Overlapping shadow geometry blended repeatedly turns into a black blob.
    The stencil buffer is what keeps it to a single darkening."""
    src = _scene_source()
    assert "gl.STENCIL_TEST" in src
    assert "gl.stencilOp" in src
    assert "colorMask(false" in src, "the stencil pass must not write colour"


def test_the_shadow_comes_from_the_machine_geometry():
    src = _scene_source()
    assert "function shadowVertices" in src
    assert "shadowVertices(machine.data" in src


def test_the_bonnet_still_curves():
    src = _scene_source()
    assert "Math.sqrt(Math.max(0.04, 1 - tm * tm * 0.55))" in src


def test_the_camera_preset_names_survive_the_rewrite():
    src = _scene_source()
    assert "applyPreset" in src
    for mode in ("chase", "side", "top"):
        assert '"' + mode + '"' in src
    app = (REPO / "web" / "static" / "js" / "app.js").read_text()
    assert 'scene.applyPreset(btn.getAttribute("data-view"))' in app


def test_pitch_is_still_clamped_below_a_right_angle():
    assert "Math.min(1.48" in _scene_source()


def test_no_rendering_library_is_vendored():
    """Written by hand, so nothing large and external lands in the repository."""
    js = REPO / "web" / "static" / "js"
    for script in js.glob("*.js"):
        text = script.read_text()
        assert _external_urls(text) == [], script.name
        for lib in ("THREE.", "three.min", "babylon", "regl", "twgl"):
            assert lib not in text, f"{script.name} vendors {lib}"
    total = sum(f.stat().st_size for f in js.glob("*.js"))
    assert total < 120_000, f"client bundle grew to {total} bytes"


def test_the_matrix_helper_is_small_and_self_contained():
    glmath = (REPO / "web" / "static" / "js" / "glmath.js").read_text()
    assert len(glmath.splitlines()) < 120
    for name in ("perspective", "lookAt", "multiply"):
        assert name in glmath


def test_glmath_loads_before_the_renderer_that_uses_it():
    base = (REPO / "web" / "templates" / "base.html").read_text()
    assert base.index("glmath.js") < base.index("scene3d.js")


def test_missing_webgl_degrades_rather_than_breaking():
    """The chart, the metrics and the table carry every number, so losing the
    3D view must not lose the result."""
    app = (REPO / "web" / "static" / "js" / "app.js").read_text()
    assert "GuidanceScene.create(canvas)" in app
    assert "catch (err)" in app
    assert "needs WebGL" in app


# --- headless geometry check ----------------------------------------------

def test_scene_geometry_passes_the_headless_check(tmp_path):
    """Run the geometry builders for every implement and assert nothing is
    broken in a way only a screenshot would show.

    This exists because a Python test cannot reach the renderer, and the bug
    it was written for was invisible to the rest of the suite: mounted
    implements were drawn at zero offset, so they landed inside the tractor
    body and simply did not appear.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the browser-side check needs it")

    scenes = tmp_path / "scenes.json"
    dump = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "dump_scenes.py")],
        cwd=REPO, capture_output=True, text=True,
    )
    assert dump.returncode == 0, dump.stderr[-2000:]
    scenes.write_text(dump.stdout)

    result = subprocess.run(
        [node, str(REPO / "scripts" / "check_scene_geometry.js"), str(scenes)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
    assert "all checks passed" in result.stdout


def test_wheels_turn_with_travel_and_slip():
    """The one place travel reduction is visible rather than tabulated: with
    slip the wheels turn faster than the ground goes by."""
    src = _scene_source()
    assert "pose.travel" in src
    assert "1 - (pose.slip || 0)" in src


def test_mounted_implements_hang_off_a_linkage():
    src = _scene_source()
    assert "MOUNTED_LINKAGE_M" in src
    assert 'im.type === "trailed" ? b : MOUNTED_LINKAGE_M' in src


def test_the_cab_is_glazed_rather_than_a_solid_box():
    src = _scene_source()
    assert "Glazing as four thin panels" in src


def test_fenders_follow_the_arc():
    src = _scene_source()
    assert "A continuous curved strip over the wheel" in src


# --- showing scale ---------------------------------------------------------

def test_the_ground_carries_a_metre_grid():
    """A grid computed from world position is a real measure of the ground,
    unlike a texture that happens to have lines on it."""
    src = _scene_source()
    assert "float gridLine(vec2 p, float spacing)" in src
    assert "gridLine(vWorld, 5.0)" in src


def test_the_renderer_can_project_a_point_for_labelling():
    src = _scene_source()
    assert "Scene.prototype.project" in src
    assert "Scene.prototype.pixelsPerMetre" in src


def test_annotations_quote_the_catalog_rather_than_estimating():
    app = (REPO / "web" / "static" / "js" / "app.js").read_text()
    assert "a.wheelbase.toFixed(2)" in app
    assert "a.workingWidth.toFixed(2)" in app
    assert "1.75 m" in app


def test_labels_are_real_text_not_baked_into_a_texture():
    """Text in a WebGL texture is blurry when zoomed and invisible to a screen
    reader."""
    app = (REPO / "web" / "static" / "js" / "app.js").read_text()
    assert 'createElementNS(SVG_NS' in app or 'createElementNS("http://www.w3.org/2000/svg"' in app
    assert 'svg("text"' in app


def test_the_scale_bar_rounds_to_a_usable_figure():
    """A bar reading 13.7 m is arithmetic, not a scale."""
    app = (REPO / "web" / "static" / "js" / "app.js").read_text()
    assert "[1, 2, 5, 10, 20, 50, 100]" in app


def test_the_headless_scene_comes_from_the_renderer():
    """A hand-maintained stub drifted out of step twice, and each time the
    geometry check failed for reasons unrelated to the geometry."""
    src = _scene_source()
    assert "headless: function" in src
    check = (REPO / "scripts" / "check_scene_geometry.js").read_text()
    assert "GuidanceScene.headless()" in check
    assert "stubScene" not in check
