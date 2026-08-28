"""Stage 0 tests.

CLAUDE.md lists three required tests. Only the catalog-integrity one belongs
to this stage; the geometry test (zero error commands zero steering) arrives
with Stage 1, and the degenerate-case test (zero width and zero hitch reduces
implement edge error exactly to tractor cross-track error) with Stage 4.
They are deliberately not stubbed here -- a passing placeholder for an
unimplemented check is worse than an absent one.
"""

import pytest

from aggsim.catalog import Implement, Param, Tractor, check_pairing, load_catalog


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


# --- provenance enforcement ------------------------------------------------

def test_param_requires_source_or_assumed():
    with pytest.raises(ValueError, match="source or assumed"):
        Param(value=1.0, unit="m")


def test_param_assumed_requires_rationale():
    with pytest.raises(ValueError, match="rationale"):
        Param(value=1.0, unit="m", assumed=True)


def test_param_cannot_be_both_sourced_and_assumed():
    with pytest.raises(ValueError, match="not both"):
        Param(value=1.0, unit="m", source="http://x", assumed=True, rationale="r")


def test_catalog_integrity_every_parameter_sourced_or_flagged(catalog):
    """CLAUDE.md required test: every entry has a source or an assumed flag."""
    entries = list(catalog.tractors.values()) + list(catalog.implements.values())
    assert entries, "catalog is empty"
    for entry in entries:
        for field, param in entry.params().items():
            if param.assumed:
                assert param.rationale, f"{entry.id}.{field}: assumed without rationale"
                assert param.source is None
            else:
                assert param.source, f"{entry.id}.{field}: no source and not flagged"


def test_sourced_parameters_cite_a_resolvable_url(catalog):
    entries = list(catalog.tractors.values()) + list(catalog.implements.values())
    for entry in entries:
        for field, param in entry.params().items():
            if not param.assumed:
                assert param.source.startswith("http"), (
                    f"{entry.id}.{field}: source is not a URL"
                )


def test_bare_number_in_yaml_is_rejected(tmp_path):
    """A parameter written as a plain float must not load."""
    (tmp_path / "tractors.yaml").write_text(
        "tractors:\n"
        "  - id: t\n    manufacturer: M\n    model: X\n"
        "    wheelbase: 2.5\n"
    )
    (tmp_path / "implements.yaml").write_text("implements: []\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_catalog(tmp_path)


# --- schema invariants -----------------------------------------------------

def _p(v, u="m"):
    return Param(value=v, unit=u, source="http://example.test")


def test_trailed_implement_requires_hitch_geometry():
    with pytest.raises(ValueError, match="hitch_distance"):
        Implement(
            id="i", manufacturer="M", model="X", type="trailed",
            working_width=_p(6.0), mass=_p(1000, "kg"),
        )


def test_mounted_implement_rejects_hitch_geometry():
    with pytest.raises(ValueError, match="must not define hitch"):
        Implement(
            id="i", manufacturer="M", model="X", type="mounted",
            working_width=_p(2.0), mass=_p(500, "kg"),
            hitch_distance=_p(4.0), implement_wheelbase=_p(2.0),
        )


def test_half_width_is_centreline_to_edge():
    imp = Implement(
        id="i", manufacturer="M", model="X", type="mounted",
        working_width=_p(12.192), mass=_p(500, "kg"),
    )
    assert imp.half_width == pytest.approx(6.096)


def test_every_trailed_entry_has_stage4_geometry(catalog):
    for imp in catalog.implements.values():
        if imp.type == "trailed":
            assert imp.hitch_distance is not None
            assert imp.implement_wheelbase is not None


# --- catalog content -------------------------------------------------------

def test_ids_are_unique(catalog):
    assert len(catalog.tractors) == len({t.id for t in catalog.tractors.values()})
    assert len(catalog.implements) == len({i.id for i in catalog.implements.values()})


def test_catalog_spans_a_useful_width_range(catalog):
    """Width is the primary independent variable of Stage 6."""
    widths = [i.working_width.value for i in catalog.implements.values()]
    assert min(widths) < 2.0
    assert max(widths) > 18.0
    assert max(widths) / min(widths) > 10


def test_catalog_spans_a_useful_wheelbase_range(catalog):
    """Wheelbase is L in the Stage 1 bicycle model."""
    wheelbases = [t.wheelbase.value for t in catalog.tractors.values()]
    assert max(wheelbases) - min(wheelbases) > 0.9


def test_both_implement_types_present(catalog):
    types = {i.type for i in catalog.implements.values()}
    assert types == {"mounted", "trailed"}


def test_unknown_key_gives_helpful_error(catalog):
    with pytest.raises(KeyError, match="available"):
        catalog.tractor("no_such_tractor")


# --- pairing validity ------------------------------------------------------

def test_pairing_rejects_implement_beyond_tractor_power(catalog):
    check = check_pairing(
        catalog.tractor("jd_5075e"), catalog.implement("jd_2230fh_69ft")
    )
    assert not check.ok
    assert "drawbar" in check.reasons[0]


def test_pairing_accepts_feasible_combination(catalog):
    check = check_pairing(
        catalog.tractor("jd_5075e"), catalog.implement("landpride_rcr1860")
    )
    assert check.ok
    assert 0 < check.utilisation < 1


def test_utilisation_scales_with_width(catalog):
    """Same tractor, same draft class, wider implement -> higher demand."""
    tractor = catalog.tractor("jd_8r_410")
    narrow = check_pairing(tractor, catalog.implement("caseih_tt345_22ft"))
    wide = check_pairing(tractor, catalog.implement("caseih_tt345_34ft"))
    assert wide.utilisation > narrow.utilisation


# --- assumption reporting --------------------------------------------------

def test_assumption_report_names_every_assumed_parameter(catalog):
    report = catalog.assumption_report()
    assumed = catalog.assumed_params()
    assert assumed, "expected the catalog to contain assumptions"
    assert str(len(assumed)) in report
    for name, field, _ in assumed:
        assert field in report


def test_steering_angle_is_flagged_assumed_everywhere(catalog):
    """No manufacturer in this catalog publishes steering geometry."""
    for tractor in catalog.tractors.values():
        assert tractor.max_steer_angle.assumed


# --- expanded catalog (added after the Stage 6 sweep) ---------------------

def test_catalog_covers_the_major_manufacturers(catalog):
    makers = {t.manufacturer for t in catalog.tractors.values()}
    assert {"John Deere", "Case IH", "New Holland", "Kubota", "Fendt",
            "Massey Ferguson", "CLAAS", "Valtra", "Mahindra",
            "Deutz-Fahr"} <= makers


def test_catalog_includes_autonomous_and_robotic_machines(catalog):
    assert catalog.tractor("monarch_mk_v").steering_type == "wheel_steer"
    makers = {i.manufacturer for i in catalog.implements.values()}
    assert {"Carbon Robotics", "Verdant Robotics"} <= makers


def test_articulated_tractors_are_flagged(catalog):
    articulated = [t for t in catalog.tractors.values()
                   if t.steering_type == "articulated"]
    assert len(articulated) >= 2
    for t in articulated:
        assert t.notes and "articulat" in t.notes.lower()


def test_articulated_tractors_are_refused_by_the_vehicle_model(catalog):
    """Better an error than plausible numbers from the wrong model."""
    from aggsim.model import from_tractor

    for t in catalog.tractors.values():
        if t.steering_type == "articulated":
            with pytest.raises(ValueError, match="articulation"):
                from_tractor(t)
        else:
            from_tractor(t)


def test_unknown_steering_type_is_rejected():
    with pytest.raises(ValueError, match="steering_type"):
        Tractor(
            id="t", manufacturer="M", model="X", years="2020",
            wheelbase=Param(2.5, "m", source="http://x"),
            mass=Param(5000, "kg", source="http://x"),
            engine_power=Param(1e5, "W", source="http://x"),
            drawbar_power=Param(7e4, "W", source="http://x"),
            max_steer_angle=Param(0.7, "rad", assumed=True, rationale="r"),
            steering_type="crab",
        )


def test_typo_in_a_field_name_is_rejected_not_dropped(tmp_path):
    """A misspelt key would otherwise silently discard a parameter."""
    (tmp_path / "tractors.yaml").write_text(
        "tractors:\n  - id: t\n    manufacturer: M\n    model: X\n"
        "    wheelbse: {value: 2.5, unit: m, source: 'http://x'}\n"
    )
    (tmp_path / "implements.yaml").write_text("implements: []\n")
    with pytest.raises(ValueError, match="unknown tractor field"):
        load_catalog(tmp_path)


def test_mounted_and_trailed_are_both_well_represented(catalog):
    mounted = [i for i in catalog.implements.values() if i.type == "mounted"]
    trailed = [i for i in catalog.implements.values() if i.type == "trailed"]
    assert len(mounted) >= 4
    assert len(trailed) >= 12


def test_catalog_size(catalog):
    assert len(catalog.tractors) >= 18
    assert len(catalog.implements) >= 21
