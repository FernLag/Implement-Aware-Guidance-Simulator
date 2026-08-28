"""Stage 5 tests: Stanley, and both controllers against both error metrics."""

import numpy as np
import pytest

from aggsim.catalog import load_catalog
from aggsim.config.terrain import Terrain
from aggsim.control import (
    PurePursuitGains,
    StanleyGains,
    front_axle_position,
    make_pure_pursuit,
    make_stanley,
    stanley,
)
from aggsim.geometry import ABLine
from aggsim.model import State, from_tractor, implement_from_catalog
from aggsim.sim import SimConfig, simulate

LINE = ABLine((0.0, 0.0), (1.0, 0.0))
SPEED = 3.0


@pytest.fixture(scope="module")
def params():
    return from_tractor(load_catalog().tractor("jd_6145r"))


@pytest.fixture(scope="module")
def geometry():
    return implement_from_catalog(load_catalog().implement("jd_1775nt_16row30"))


def _run(params, controller, *, e0=0.0, terrain=None, geometry=None, duration=200.0):
    cfg = SimConfig(speed=SPEED, dt=0.01, duration=duration)
    return simulate(State(0.0, e0, 0.0), LINE, controller, params, cfg,
                    terrain=terrain, geometry=geometry)


def _stanley(params, k_e=2.0):
    return make_stanley(LINE, SPEED, StanleyGains(k_e=k_e), params)


def _pursuit(params, k=0.5):
    return make_pure_pursuit(LINE, SPEED, PurePursuitGains(k=k, l_min=3.0), params)


# --- the required geometry test, now for the second controller ------------

def test_stanley_on_line_with_zero_heading_error_commands_zero_steering(params):
    """The CLAUDE.md required geometry test must hold for every controller."""
    delta = stanley(State(10.0, 0.0, 0.0), LINE, SPEED, StanleyGains(k_e=2.0), params)
    assert delta == pytest.approx(0.0, abs=1e-12)


def test_zero_steering_holds_across_speeds_and_gains(params):
    for v in (0.0, 1.0, 5.0, 12.0):
        for k_e in (0.5, 2.0, 10.0):
            d = stanley(State(-4.0, 0.0, 0.0), LINE, v, StanleyGains(k_e=k_e), params)
            assert d == pytest.approx(0.0, abs=1e-12)


# --- law and conventions ---------------------------------------------------

def test_front_axle_is_one_wheelbase_ahead(params):
    fx, fy = front_axle_position(State(0.0, 0.0, 0.0), params)
    assert (fx, fy) == pytest.approx((params.wheelbase, 0.0))
    fx, fy = front_axle_position(State(0.0, 0.0, np.pi / 2), params)
    assert (fx, fy) == pytest.approx((0.0, params.wheelbase), abs=1e-12)


def test_cross_track_term_steers_towards_the_line(params):
    """Left of the line, heading aligned -> steer right."""
    gains = StanleyGains(k_e=2.0)
    assert stanley(State(0.0, 2.0, 0.0), LINE, SPEED, gains, params) < 0
    assert stanley(State(0.0, -2.0, 0.0), LINE, SPEED, gains, params) > 0


def test_heading_term_aligns_with_the_path(params):
    """On the line but pointing left -> steer right."""
    gains = StanleyGains(k_e=2.0)
    assert stanley(State(0.0, 0.0, np.radians(15.0)), LINE, SPEED, gains, params) < 0
    assert stanley(State(0.0, 0.0, np.radians(-15.0)), LINE, SPEED, gains, params) > 0


def test_response_is_symmetric(params):
    gains = StanleyGains(k_e=2.0)
    left = stanley(State(0.0, 1.5, 0.1), LINE, SPEED, gains, params)
    right = stanley(State(0.0, -1.5, -0.1), LINE, SPEED, gains, params)
    assert left == pytest.approx(-right)


def test_cross_track_authority_falls_with_speed(params):
    """The (v + k_s) denominator is the point of the law."""
    gains = StanleyGains(k_e=2.0)
    slow = abs(stanley(State(0.0, 1.0, 0.0), LINE, 1.0, gains, params))
    fast = abs(stanley(State(0.0, 1.0, 0.0), LINE, 12.0, gains, params))
    assert slow > fast


def test_steering_is_clamped(params):
    d = stanley(State(0.0, 80.0, 0.0), LINE, SPEED, StanleyGains(k_e=50.0), params)
    assert abs(d) <= params.max_steer_angle + 1e-12


def test_is_a_pure_function_of_state(params):
    gains = StanleyGains(k_e=2.0)
    s = State(3.0, 1.7, 0.2)
    first = stanley(s, LINE, SPEED, gains, params)
    for _ in range(5):
        stanley(State(99.0, -40.0, 1.0), LINE, 9.0, gains, params)
    assert stanley(s, LINE, SPEED, gains, params) == first


def test_gains_reject_degenerate_values():
    with pytest.raises(ValueError, match="k_e"):
        StanleyGains(k_e=0.0)
    with pytest.raises(ValueError, match="k_s"):
        StanleyGains(k_e=1.0, k_s=0.0)


# --- flat-ground behaviour -------------------------------------------------

def test_converges_from_an_offset_on_flat_ground(params):
    log = _run(params, _stanley(params), e0=3.0)
    assert abs(log.final_cross_track()) < 1e-3


def test_converges_from_pure_heading_error(params):
    cfg = SimConfig(speed=SPEED, dt=0.01, duration=120.0)
    log = simulate(State(0.0, 0.0, np.radians(20.0)), LINE, _stanley(params), params, cfg)
    assert abs(log.final_cross_track()) < 1e-3


# --- the Stage 5 comparison ------------------------------------------------

def _slope():
    return Terrain(slope_angle=np.radians(10.0))


def test_stanley_front_axle_offset_matches_closed_form(params):
    """e_f = (v + k_s) (v_d / v_eff) / k_e at steady state."""
    terrain = _slope()
    k_e, k_s = 2.0, 1.0
    log = _run(params, _stanley(params, k_e), terrain=terrain)
    e_f = log.cross_track[-1] + params.wheelbase * np.sin(log.theta[-1])
    predicted = (SPEED + k_s) * (terrain.lateral_drift / SPEED) / k_e
    assert e_f == pytest.approx(predicted, rel=0.02)


def test_stanley_does_not_eliminate_the_rear_axle_offset(params):
    """The honest finding: raising k_e drives the FRONT axle to zero, but the
    rear axle floors at L v_d / sqrt(v^2 + v_d^2) from crabbing alone."""
    terrain = _slope()
    floor = params.wheelbase * terrain.lateral_drift / np.hypot(SPEED, terrain.lateral_drift)

    rears = []
    for k_e in (1.0, 2.0, 5.0, 20.0):
        log = _run(params, _stanley(params, k_e), terrain=terrain)
        front = log.cross_track[-1] + params.wheelbase * np.sin(log.theta[-1])
        rears.append(log.cross_track[-1])
        assert front > 0  # never actually reaches zero
    assert all(a > b for a, b in zip(rears, rears[1:]))  # monotone improvement
    assert rears[-1] > floor  # but never below the floor
    assert rears[-1] == pytest.approx(floor, rel=0.10)


def test_stanley_at_moderate_gain_is_no_better_than_pure_pursuit(params):
    """A result worth stating: the advantage is not automatic."""
    terrain = _slope()
    pp = _run(params, _pursuit(params), terrain=terrain)
    st = _run(params, _stanley(params, k_e=2.0), terrain=terrain)
    assert abs(st.final_cross_track()) > abs(pp.final_cross_track()) * 0.9


def test_stanley_at_high_gain_beats_pure_pursuit_on_tractor_error(params):
    terrain = _slope()
    pp = _run(params, _pursuit(params), terrain=terrain)
    st = _run(params, _stanley(params, k_e=20.0), terrain=terrain)
    assert abs(st.final_cross_track()) < abs(pp.final_cross_track())


def test_both_controllers_produce_the_same_crab_angle(params):
    """The crab angle is set by the drift/speed balance, not by the
    controller, which is why the implement offset resists improvement."""
    terrain = _slope()
    pp = _run(params, _pursuit(params), terrain=terrain)
    st = _run(params, _stanley(params, k_e=20.0), terrain=terrain)
    assert pp.theta[-1] == pytest.approx(st.theta[-1], rel=0.05)


def test_stanley_flatters_the_tractor_metric_more_than_the_implement_metric(
    params, geometry
):
    """The Stage 6 hypothesis in miniature: improving tractor error by a given
    fraction does not improve implement edge error by the same fraction."""
    terrain = _slope()
    pp = _run(params, _pursuit(params), terrain=terrain, geometry=geometry)
    st = _run(params, _stanley(params, k_e=20.0), terrain=terrain, geometry=geometry)

    tractor_gain = 1.0 - abs(st.cross_track[-1]) / abs(pp.cross_track[-1])
    edge_gain = 1.0 - abs(st.worst_edge[-1]) / abs(pp.worst_edge[-1])
    assert tractor_gain > edge_gain > 0

    # And the two objectives disagree more under Stanley than under pursuit.
    assert (abs(st.worst_edge[-1]) / abs(st.cross_track[-1])
            > abs(pp.worst_edge[-1]) / abs(pp.cross_track[-1]))


def test_both_controllers_evaluated_against_both_metrics(params, geometry):
    """Every combination must produce a finite, ordered result."""
    terrain = _slope()
    for controller in (_pursuit(params), _stanley(params, k_e=2.0)):
        log = _run(params, controller, terrain=terrain, geometry=geometry)
        assert np.isfinite(log.cross_track[-1])
        assert np.isfinite(log.worst_edge[-1])
        # The implement is always worse off than the tractor on a slope.
        assert abs(log.worst_edge[-1]) > abs(log.cross_track[-1])
