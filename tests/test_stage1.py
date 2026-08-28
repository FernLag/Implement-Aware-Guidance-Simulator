"""Stage 1 tests: vehicle model, AB-line geometry, pure pursuit."""

import numpy as np
import pytest

from aggsim.catalog import load_catalog
from aggsim.control import PurePursuitGains, make_pure_pursuit, pure_pursuit
from aggsim.geometry import ABLine, wrap_angle
from aggsim.model import State, VehicleParams, from_tractor, rk4_step
from aggsim.sim import SimConfig, simulate


@pytest.fixture(scope="module")
def params():
    return from_tractor(load_catalog().tractor("jd_6145r"))


@pytest.fixture
def east_line():
    return ABLine((0.0, 0.0), (1.0, 0.0))


# --- CLAUDE.md required test ----------------------------------------------

def test_on_line_with_zero_heading_error_commands_zero_steering(params, east_line):
    """Required geometry test.

    A vehicle already on the line, pointing along it, must command exactly
    zero steering -- otherwise the controller injects error into a state that
    has none, and every downstream result is contaminated.
    """
    state = State(x=10.0, y=0.0, theta=0.0)
    gains = PurePursuitGains(k=0.5, l_min=3.0)
    delta = pure_pursuit(state, east_line, v=3.0, gains=gains, params=params)
    assert delta == pytest.approx(0.0, abs=1e-12)


def test_zero_steering_holds_for_any_speed_and_gain(params, east_line):
    state = State(x=-25.0, y=0.0, theta=0.0)
    for v in (0.0, 1.0, 5.0, 12.0):
        for k in (0.0, 0.3, 1.5):
            gains = PurePursuitGains(k=k, l_min=2.0)
            delta = pure_pursuit(state, east_line, v, gains, params)
            assert delta == pytest.approx(0.0, abs=1e-12)


# --- geometry --------------------------------------------------------------

def test_cross_track_is_positive_to_the_left(east_line):
    assert east_line.cross_track(0.0, 3.0) == pytest.approx(3.0)
    assert east_line.cross_track(0.0, -3.0) == pytest.approx(-3.0)


def test_cross_track_convention_holds_for_a_rotated_line():
    line = ABLine((0.0, 0.0), (0.0, 1.0))  # pointing north
    assert line.cross_track(-2.0, 5.0) == pytest.approx(2.0)  # west is left
    assert line.cross_track(2.0, 5.0) == pytest.approx(-2.0)


def test_lookahead_point_solves_the_circle_intersection(east_line):
    goal = east_line.lookahead_point(0.0, 3.0, 5.0)
    assert goal[0] == pytest.approx(4.0)  # 3-4-5 triangle
    assert goal[1] == pytest.approx(0.0)


def test_lookahead_point_is_exactly_l_d_away(east_line):
    for e, l_d in [(0.0, 4.0), (1.0, 4.0), (-2.5, 6.0), (3.9, 4.0)]:
        goal = east_line.lookahead_point(0.0, e, l_d)
        assert np.hypot(goal[0] - 0.0, goal[1] - e) == pytest.approx(l_d)


def test_lookahead_falls_back_to_closest_point_when_further_than_l_d(east_line):
    """Discriminant is l_d^2 - e^2, so e > l_d has no intersection."""
    goal = east_line.lookahead_point(7.0, 10.0, 5.0)
    assert goal[0] == pytest.approx(7.0)
    assert goal[1] == pytest.approx(0.0)


def test_lookahead_never_returns_nan(east_line):
    for e in np.linspace(-20, 20, 81):
        goal = east_line.lookahead_point(0.0, float(e), 4.0)
        assert np.all(np.isfinite(goal))


def test_degenerate_line_rejected():
    with pytest.raises(ValueError, match="distinct"):
        ABLine((1.0, 1.0), (1.0, 1.0))


def test_wrap_angle():
    assert wrap_angle(0.5) == pytest.approx(0.5)
    assert wrap_angle(2 * np.pi + 0.5) == pytest.approx(0.5)
    assert wrap_angle(-2 * np.pi - 0.5) == pytest.approx(-0.5)
    for a in np.linspace(-30, 30, 601):
        w = wrap_angle(float(a))
        assert -np.pi - 1e-12 <= w <= np.pi + 1e-12
        assert np.isclose(np.sin(w), np.sin(a)) and np.isclose(np.cos(w), np.cos(a))


def test_wrap_angle_on_the_branch_cut_returns_a_magnitude_of_pi():
    """Sign at the cut is float-dependent; +pi and -pi are the same angle."""
    assert abs(wrap_angle(3 * np.pi)) == pytest.approx(np.pi)
    assert abs(wrap_angle(-3 * np.pi)) == pytest.approx(np.pi)


# --- vehicle model ---------------------------------------------------------

def test_zero_steering_travels_exactly_straight(params):
    vec = np.array([0.0, 0.0, 0.0])
    for _ in range(1000):
        vec = rk4_step(vec, v=4.0, delta=0.0, wheelbase=params.wheelbase, dt=0.01)
    assert vec[0] == pytest.approx(40.0, abs=1e-9)  # v * t
    assert vec[1] == pytest.approx(0.0, abs=1e-12)
    assert vec[2] == pytest.approx(0.0, abs=1e-12)


def test_constant_steering_traces_a_circle_of_radius_L_over_tan_delta(params):
    """The kinematic model's defining property, and the sharpest check on RK4."""
    delta, v, dt = 0.30, 4.0, 0.01
    radius = params.wheelbase / np.tan(delta)
    # Starting at the origin heading +x, the turn centre is at (0, +R).
    centre = np.array([0.0, radius])

    vec = np.array([0.0, 0.0, 0.0])
    for _ in range(2000):
        vec = rk4_step(vec, v=v, delta=delta, wheelbase=params.wheelbase, dt=dt)
        assert np.linalg.norm(vec[:2] - centre) == pytest.approx(radius, abs=1e-6)


def test_rk4_beats_euler_on_the_circle(params):
    """Justifies RK4 over the simpler integrator."""
    delta, v, dt, n = 0.30, 4.0, 0.05, 400
    radius = params.wheelbase / np.tan(delta)
    centre = np.array([0.0, radius])

    rk = np.array([0.0, 0.0, 0.0])
    eu = np.array([0.0, 0.0, 0.0])
    for _ in range(n):
        rk = rk4_step(rk, v, delta, params.wheelbase, dt)
        theta = eu[2]
        eu = eu + dt * np.array(
            [v * np.cos(theta), v * np.sin(theta), v / params.wheelbase * np.tan(delta)]
        )

    err_rk = abs(np.linalg.norm(rk[:2] - centre) - radius)
    err_eu = abs(np.linalg.norm(eu[:2] - centre) - radius)
    assert err_rk < err_eu / 100


def test_vehicle_params_reject_impossible_geometry():
    with pytest.raises(ValueError, match="wheelbase"):
        VehicleParams(wheelbase=0.0, max_steer_angle=0.5)
    with pytest.raises(ValueError, match="max_steer_angle"):
        VehicleParams(wheelbase=2.5, max_steer_angle=np.pi)


def test_gains_reject_zero_l_min():
    """L_d -> 0 at standstill would make the steering law singular."""
    with pytest.raises(ValueError, match="l_min"):
        PurePursuitGains(k=0.5, l_min=0.0)


# --- controller behaviour --------------------------------------------------

def test_steering_is_clamped_to_the_catalog_limit(params, east_line):
    state = State(x=0.0, y=50.0, theta=0.0)  # far off line, hard correction
    gains = PurePursuitGains(k=0.1, l_min=1.0)
    delta = pure_pursuit(state, east_line, 3.0, gains, params)
    assert abs(delta) <= params.max_steer_angle + 1e-12


def test_controller_steers_towards_the_line(params, east_line):
    gains = PurePursuitGains(k=0.5, l_min=3.0)
    left = pure_pursuit(State(0.0, 2.0, 0.0), east_line, 3.0, gains, params)
    right = pure_pursuit(State(0.0, -2.0, 0.0), east_line, 3.0, gains, params)
    assert left < 0  # left of line -> steer right
    assert right > 0
    assert left == pytest.approx(-right)  # symmetric


def test_controller_is_a_pure_function_of_state(params, east_line):
    """Same state in, same command out -- no hidden internal state."""
    gains = PurePursuitGains(k=0.5, l_min=3.0)
    state = State(3.0, 1.7, 0.2)
    first = pure_pursuit(state, east_line, 3.0, gains, params)
    for _ in range(5):
        pure_pursuit(State(99.0, -40.0, 1.0), east_line, 9.0, gains, params)
    assert pure_pursuit(state, east_line, 3.0, gains, params) == first


# --- Stage 1 success criterion --------------------------------------------

def _run(params, initial, k=0.5, l_min=3.0, speed=3.0, duration=60.0):
    line = ABLine((0.0, 0.0), (1.0, 0.0))
    cfg = SimConfig(speed=speed, dt=0.01, duration=duration)
    ctrl = make_pure_pursuit(line, cfg.speed, PurePursuitGains(k=k, l_min=l_min), params)
    return simulate(initial, line, ctrl, params, cfg)


def test_offset_start_decays_towards_zero(params):
    """Stage 1 success criterion."""
    log = _run(params, State(0.0, 3.0, 0.0))
    assert abs(log.final_cross_track()) < 1e-3
    assert abs(log.cross_track[-1]) < abs(log.cross_track[0])


def test_error_decays_monotonically_in_envelope(params):
    """Later error extremes must not exceed earlier ones."""
    log = _run(params, State(0.0, 3.0, 0.0))
    early = np.max(np.abs(log.cross_track[log.t < 5.0]))
    late = np.max(np.abs(log.cross_track[log.t > 15.0]))
    assert late < early / 100


def test_converges_from_pure_heading_error(params):
    log = _run(params, State(0.0, 0.0, np.radians(20.0)))
    assert abs(log.final_cross_track()) < 1e-3


def test_converges_from_both_sides_symmetrically(params):
    up = _run(params, State(0.0, 2.0, 0.0))
    down = _run(params, State(0.0, -2.0, 0.0))
    assert np.allclose(up.cross_track, -down.cross_track, atol=1e-12)


def test_already_on_line_stays_on_line(params):
    log = _run(params, State(0.0, 0.0, 0.0))
    assert np.max(np.abs(log.cross_track)) < 1e-12


@pytest.mark.parametrize("tractor_id", ["jd_5075e", "kubota_m7_172", "jd_8r_410"])
def test_convergence_holds_across_catalog_wheelbases(tractor_id):
    """Wheelbase comes from Stage 0, so convergence must not be tuned to one."""
    p = from_tractor(load_catalog().tractor(tractor_id))
    log = _run(p, State(0.0, 3.0, 0.0))
    assert abs(log.final_cross_track()) < 1e-3
