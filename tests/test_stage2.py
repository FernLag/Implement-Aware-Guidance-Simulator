"""Stage 2 tests: steering actuator dynamics and oscillation detection."""

import numpy as np
import pytest

from aggsim.analysis import analyse_oscillation, error_extrema, onset_speed
from aggsim.catalog import load_catalog
from aggsim.config import load_steering
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry import ABLine
from aggsim.model import State, from_tractor, steering_derivative
from aggsim.sim import SimConfig, simulate


@pytest.fixture(scope="module")
def params():
    return from_tractor(load_catalog().tractor("jd_6145r"))


@pytest.fixture(scope="module")
def steering():
    return load_steering()


@pytest.fixture
def line():
    return ABLine((0.0, 0.0), (1.0, 0.0))


def _run(params, steering, *, k=0.3, speed=4.0, e0=1.0, duration=60.0, dt=0.01):
    line = ABLine((0.0, 0.0), (1.0, 0.0))
    cfg = SimConfig(speed=speed, dt=dt, duration=duration)
    ctrl = make_pure_pursuit(line, cfg.speed, PurePursuitGains(k=k, l_min=3.0), params)
    return simulate(State(0.0, e0, 0.0), line, ctrl, params, cfg, steering=steering)


# --- actuator law ----------------------------------------------------------

def test_steering_derivative_moves_towards_the_command():
    assert steering_derivative(0.0, 0.1, tau=0.2, rate_limit=10.0) > 0
    assert steering_derivative(0.0, -0.1, tau=0.2, rate_limit=10.0) < 0


def test_steering_derivative_is_zero_when_already_at_command():
    assert steering_derivative(0.3, 0.3, tau=0.2, rate_limit=10.0) == 0.0


def test_steering_derivative_respects_the_rate_limit():
    """A huge error must not produce an unbounded rate."""
    rate = steering_derivative(0.0, 100.0, tau=0.01, rate_limit=0.4)
    assert rate == pytest.approx(0.4)
    rate = steering_derivative(0.0, -100.0, tau=0.01, rate_limit=0.4)
    assert rate == pytest.approx(-0.4)


def test_unsaturated_response_follows_first_order_lag(params):
    """Below the rate limit the step response must be 1 - exp(-t/tau)."""
    from aggsim.model import rk4_step_augmented

    tau, cmd = 0.3, 0.05  # small command so the rate limit never binds
    vec = np.array([0.0, 0.0, 0.0, 0.0])
    dt = 0.001
    for i in range(int(1.5 / dt)):
        vec = rk4_step_augmented(vec, 0.0, cmd, params.wheelbase, tau, 10.0, dt)
        t = (i + 1) * dt
        assert vec[3] == pytest.approx(cmd * (1 - np.exp(-t / tau)), abs=1e-9)


def test_steering_state_converges_to_the_command(params, steering):
    log = _run(params, steering, duration=40.0)
    assert log.delta[-1] == pytest.approx(log.delta_cmd[-1], abs=1e-6)


# --- the actuator must actually change behaviour ---------------------------

def test_ideal_actuator_reproduces_stage1(params, line):
    """steering=None must leave Stage 1 results untouched."""
    cfg = SimConfig(speed=3.0, dt=0.01, duration=30.0)
    ctrl = make_pure_pursuit(line, cfg.speed, PurePursuitGains(k=0.5, l_min=3.0), params)
    log = simulate(State(0.0, 3.0, 0.0), line, ctrl, params, cfg, steering=None)
    assert np.allclose(log.delta, log.delta_cmd)
    assert abs(log.final_cross_track()) < 1e-3


def test_actual_steering_lags_the_command(params, steering):
    log = _run(params, steering, e0=3.0, speed=6.0)
    # During the initial correction the wheels trail the command.
    early = log.t < 2.0
    assert np.max(np.abs(log.delta_cmd[early])) > np.max(np.abs(log.delta[early]))


def test_lag_never_exceeds_the_commanded_magnitude_at_rest(params, steering):
    log = _run(params, steering, e0=3.0, speed=6.0)
    assert np.max(np.abs(log.delta)) <= params.max_steer_angle + 1e-12


def test_lag_degrades_tracking_relative_to_ideal(params, steering, line):
    """The core Stage 2 claim: the actuator makes tracking worse."""
    cfg = SimConfig(speed=8.0, dt=0.01, duration=60.0)
    ctrl = make_pure_pursuit(line, cfg.speed, PurePursuitGains(k=0.15, l_min=3.0), params)
    ideal = simulate(State(0.0, 1.0, 0.0), line, ctrl, params, cfg, steering=None)
    lagged = simulate(State(0.0, 1.0, 0.0), line, ctrl, params, cfg, steering=steering)
    assert lagged.rms_cross_track() > ideal.rms_cross_track()


# --- speed dependence ------------------------------------------------------

def test_damping_falls_as_speed_rises(params, steering):
    """Tracking degrades with speed once lag is present."""
    zetas = []
    for v in (6.0, 9.0, 12.0, 15.0):
        m = analyse_oscillation(_run(params, steering, k=0.2, speed=v, duration=120.0))
        zetas.append(m.damping_ratio)
    assert all(np.isfinite(zetas))
    assert all(a > b for a, b in zip(zetas, zetas[1:])), zetas


def test_larger_lookahead_gain_is_more_stable(params, steering):
    low = analyse_oscillation(_run(params, steering, k=0.15, speed=12.0, duration=120.0))
    high = analyse_oscillation(_run(params, steering, k=0.40, speed=12.0, duration=120.0))
    assert high.damping_ratio > low.damping_ratio


def test_longer_lag_destabilises(params, steering):
    slow = steering.replace(tau=0.8)
    base = analyse_oscillation(_run(params, steering, k=0.2, speed=8.0, duration=120.0))
    lagged = analyse_oscillation(_run(params, slow, k=0.2, speed=8.0, duration=120.0))
    assert lagged.damping_ratio < base.damping_ratio


# --- oscillation metrics ---------------------------------------------------

def test_error_extrema_finds_turning_points():
    t = np.linspace(0, 4 * np.pi, 4001)
    e = np.sin(t)
    times, values = error_extrema(t, e)
    assert len(values) == 4
    assert np.allclose(np.abs(values), 1.0, atol=1e-3)


def test_damping_ratio_recovers_a_known_decay():
    """Synthetic decaying sinusoid with known zeta must be recovered."""
    zeta_true, wn = 0.10, 2.0
    wd = wn * np.sqrt(1 - zeta_true**2)
    t = np.linspace(0, 40, 40001)
    e = np.exp(-zeta_true * wn * t) * np.cos(wd * t)

    class FakeLog:
        pass

    log = FakeLog()
    log.t, log.cross_track = t, e
    log.is_settled = lambda tol=0.02, tail_fraction=0.25: False
    log.rms_cross_track = lambda settle_time=0.0: 0.0

    m = analyse_oscillation(log, skip_peaks=0)
    assert m.damping_ratio == pytest.approx(zeta_true, rel=0.05)


def test_undamped_sinusoid_is_reported_as_oscillating():
    t = np.linspace(0, 60, 60001)
    e = np.sin(2.0 * t)

    class FakeLog:
        pass

    log = FakeLog()
    log.t, log.cross_track = t, e
    log.is_settled = lambda tol=0.02, tail_fraction=0.25: False
    log.rms_cross_track = lambda settle_time=0.0: 0.7

    m = analyse_oscillation(log, skip_peaks=0)
    assert m.damping_ratio == pytest.approx(0.0, abs=1e-3)
    assert m.oscillating


def test_noise_floor_prevents_fitting_to_machine_epsilon(params, steering):
    """A well-damped run decays to ~1e-16; those wobbles must not be peaks."""
    log = _run(params, steering, k=0.5, speed=3.0, duration=120.0)
    m = analyse_oscillation(log)
    assert m.n_peaks < 10
    assert not m.oscillating


def test_onset_speed_returns_none_when_nothing_oscillates(params, steering):
    """A negative result must not be reported as a number."""
    def run(v):
        return _run(params, steering, k=1.0, speed=v, duration=60.0)

    assert onset_speed(run, np.arange(2.0, 8.1, 2.0)) is None
