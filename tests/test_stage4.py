"""Stage 4 tests: implement kinematics and the second error metric.

The degenerate-case test below is the one CLAUDE.md calls the sanity check on
the whole metric: if implement edge error does not collapse onto tractor
cross-track error when the implement has no width and no hitch geometry, the
implement kinematics are wrong and every Stage 6 result would be built on it.
"""

import numpy as np
import pytest

from aggsim.catalog import load_catalog
from aggsim.catalog.param import Param
from aggsim.config import load_steering
from aggsim.config.terrain import Terrain
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry import ABLine
from aggsim.model import (
    ImplementGeometry,
    State,
    edge_errors,
    from_tractor,
    implement_from_catalog,
    implement_position,
)
from aggsim.sim import SimConfig, simulate

LINE = ABLine((0.0, 0.0), (1.0, 0.0))
GAINS = PurePursuitGains(k=0.5, l_min=3.0)


@pytest.fixture(scope="module")
def params():
    return from_tractor(load_catalog().tractor("jd_6145r"))


def _run(params, geometry, *, e0=0.0, terrain=None, v=3.0, duration=120.0, steering=None):
    cfg = SimConfig(speed=v, dt=0.01, duration=duration)
    ctrl = make_pure_pursuit(LINE, cfg.speed, GAINS, params)
    return simulate(State(0.0, e0, 0.0), LINE, ctrl, params, cfg,
                    steering=steering, terrain=terrain, geometry=geometry)


# --- CLAUDE.md required degenerate test ------------------------------------

@pytest.mark.parametrize("kind", ["mounted", "trailed"])
def test_degenerate_implement_reduces_exactly_to_tractor_error(params, kind):
    """REQUIRED. Zero width and zero hitch geometry must collapse the two
    metrics onto each other EXACTLY, not approximately."""
    geometry = ImplementGeometry(
        type=kind, working_width=0.0, hitch_distance=0.0, implement_wheelbase=0.0
    )
    log = _run(params, geometry, e0=2.5, terrain=Terrain(slope_angle=np.radians(8.0)))

    assert np.array_equal(log.edge_left, log.cross_track)
    assert np.array_equal(log.edge_right, log.cross_track)
    assert np.array_equal(log.implement_cross_track, log.cross_track)
    assert np.array_equal(log.worst_edge, log.cross_track)


def test_degenerate_case_is_a_meaningful_test(params):
    """Guard the guard: non-degenerate geometry must NOT collapse, or the
    test above would pass for the wrong reason."""
    log = _run(params, ImplementGeometry("trailed", 6.0, 0.9, 4.5), e0=2.5)
    assert not np.allclose(log.worst_edge, log.cross_track)


@pytest.mark.parametrize("w,a,b", [(0.0, 0.0, 0.5), (0.0, 0.5, 0.0), (1.0, 0.0, 0.0)])
def test_partial_degeneracy_does_not_collapse(params, w, a, b):
    """Each of the three degenerate conditions is individually necessary."""
    log = _run(params, ImplementGeometry("trailed", w, a, b), e0=2.0)
    assert not np.allclose(log.worst_edge, log.cross_track, atol=1e-9)


# --- geometry --------------------------------------------------------------

def test_mounted_implement_is_rigid():
    assert ImplementGeometry("mounted", 3.0).is_rigid
    assert ImplementGeometry("mounted", 3.0, hitch_distance=1.0).is_rigid


def test_trailed_with_zero_wheelbase_is_rigid_in_the_limit():
    """b -> 0 forces theta_i to theta; routed to the rigid path, not a
    division by zero."""
    g = ImplementGeometry("trailed", 3.0, 0.9, 0.0)
    assert g.is_rigid


def test_geometry_rejects_invalid_values():
    with pytest.raises(ValueError, match="unknown implement type"):
        ImplementGeometry("dragged", 3.0)
    with pytest.raises(ValueError, match="working width"):
        ImplementGeometry("mounted", -1.0)
    with pytest.raises(ValueError, match="hitch geometry"):
        ImplementGeometry("trailed", 3.0, -1.0, 4.0)


def test_implement_position_sits_behind_the_tractor():
    g = ImplementGeometry("trailed", 6.0, 1.0, 4.0)
    p = implement_position(0.0, 0.0, 0.0, 0.0, g)
    assert p == pytest.approx([-5.0, 0.0])  # a + b behind, heading +x


def test_edge_error_is_measured_against_plus_minus_half_width():
    """A perfectly placed wide implement must report zero, not w/2."""
    g = ImplementGeometry("mounted", 12.192)
    left, right = edge_errors(LINE, 0.0, 0.0, 0.0, 0.0, g)
    assert left == pytest.approx(0.0)
    assert right == pytest.approx(0.0)


@pytest.mark.parametrize("width", [1.524, 12.192, 21.2])
@pytest.mark.parametrize("deg", [5.0, 10.0, 20.0])
def test_mechanism_three_is_linear_in_half_width(width, deg):
    """Heading error contributes (w/2)(1 - cos theta_i) at the edge:
    second order in angle, exactly linear in half width."""
    g = ImplementGeometry("mounted", width)
    theta = np.radians(deg)
    left, right = edge_errors(LINE, 0.0, 0.0, theta, theta, g)
    expected = (width / 2.0) * (1.0 - np.cos(theta))
    assert left == pytest.approx(-expected)
    assert right == pytest.approx(+expected)


def test_from_catalog_round_trips_every_implement():
    catalog = load_catalog()
    for imp in catalog.implements.values():
        g = implement_from_catalog(imp)
        assert g.type == imp.type
        assert g.working_width == pytest.approx(imp.working_width.value)
        if imp.type == "mounted":
            assert g.is_rigid


# --- mechanism 1: trailed implements lag ----------------------------------

def test_mounted_implement_heading_equals_tractor_heading(params):
    log = _run(params, ImplementGeometry("mounted", 3.0), e0=2.0)
    assert np.allclose(log.theta_implement, log.theta)


def test_trailed_implement_lags_during_a_correction(params):
    log = _run(params, ImplementGeometry("trailed", 6.0, 0.9, 4.5), e0=3.0, duration=40.0)
    early = log.t < 10.0
    lag = np.abs(log.theta_implement[early] - log.theta[early])
    assert lag.max() > np.radians(1.0)


def test_trailed_implement_realigns_once_settled(params):
    log = _run(params, ImplementGeometry("trailed", 6.0, 0.9, 4.5), e0=3.0)
    assert abs(log.theta_implement[-1] - log.theta[-1]) < 1e-6
    assert abs(log.worst_edge[-1]) < 1e-6


def test_shorter_implement_wheelbase_responds_faster(params):
    """b sets how quickly hitch angle follows the tractor."""
    short = _run(params, ImplementGeometry("trailed", 6.0, 0.9, 2.0), e0=3.0, duration=40.0)
    long_ = _run(params, ImplementGeometry("trailed", 6.0, 0.9, 8.0), e0=3.0, duration=40.0)
    assert short.rms_worst_edge() < long_.rms_worst_edge()


# --- mechanism 2: side slope drives the two metrics apart ------------------

def test_side_slope_makes_implement_error_differ_from_tractor_error(params):
    slope = Terrain(slope_angle=np.radians(10.0))
    log = _run(params, ImplementGeometry("trailed", 12.192, 0.9, 5.5), terrain=slope)
    assert abs(log.worst_edge[-1] - log.cross_track[-1]) > 1e-3


def test_equal_drift_gives_exactly_zero_steady_hitch_angle(params):
    """A real property of the model, not an accident: at ratio 1.0,
    v_d cos(0) - v_d = 0, so zero hitch angle is an exact equilibrium and
    side-draft contributes NO steady-state divergence."""
    slope = Terrain(slope_angle=np.radians(10.0))
    log = _run(params, ImplementGeometry("trailed", 12.192, 0.9, 5.5), terrain=slope)
    assert abs(log.theta_implement[-1] - log.theta[-1]) < 1e-12


@pytest.mark.parametrize("ratio", [0.2, 0.5, 0.8, 1.3])
def test_mismatched_drift_produces_the_predicted_hitch_angle(params, ratio):
    """theta_hitch ~= v_d (1 - r) / v_eff from linearising the hitch equation."""
    slope = Terrain(
        slope_angle=np.radians(10.0),
        implement_drift_ratio=Param(value=ratio, unit="dimensionless",
                                    assumed=True, rationale="swept"),
    )
    log = _run(params, ImplementGeometry("trailed", 12.192, 0.9, 5.5), terrain=slope)
    hitch = log.theta_implement[-1] - log.theta[-1]
    predicted = slope.lateral_drift * (1.0 - ratio) / 3.0
    assert hitch == pytest.approx(predicted, rel=0.01)

    tail = (log.theta_implement - log.theta)[log.t > log.t[-1] - 10.0]
    assert np.ptp(tail) < 1e-6  # genuinely steady


def test_flat_ground_leaves_no_steady_divergence(params):
    """Divergence must come from the mechanisms, not from a modelling bias."""
    log = _run(params, ImplementGeometry("trailed", 12.192, 0.9, 5.5), e0=2.0)
    assert abs(log.worst_edge[-1]) < 1e-6
    assert abs(log.cross_track[-1]) < 1e-6


# --- mechanism 3: width amplification in a full run -----------------------

def test_wider_implement_gives_larger_worst_edge_error(params):
    slope = Terrain(slope_angle=np.radians(10.0))
    errors = []
    for width in (3.048, 10.4, 21.2):
        log = _run(params, ImplementGeometry("trailed", width, 0.9, 5.5), terrain=slope)
        errors.append(abs(log.worst_edge[-1]))
    assert all(a < b for a, b in zip(errors, errors[1:])), errors


def test_worst_edge_selects_the_larger_magnitude(params):
    log = _run(params, ImplementGeometry("trailed", 12.192, 0.9, 5.5),
               terrain=Terrain(slope_angle=np.radians(10.0)))
    worst = log.worst_edge
    assert np.all(np.abs(worst) >= np.minimum(np.abs(log.edge_left), np.abs(log.edge_right)))
    assert np.all(np.abs(worst) == np.maximum(np.abs(log.edge_left), np.abs(log.edge_right)))


def test_worst_edge_requires_an_implement(params):
    log = _run(params, None, e0=1.0, duration=10.0)
    with pytest.raises(ValueError, match="no implement"):
        _ = log.worst_edge


def test_divergence_survives_actuator_dynamics(params):
    log = _run(params, ImplementGeometry("trailed", 21.2, 0.9, 6.2),
               terrain=Terrain(slope_angle=np.radians(10.0)),
               steering=load_steering(), duration=200.0)
    assert abs(log.worst_edge[-1]) > abs(log.cross_track[-1])
