"""Stage 6 tests: coverage translation and dual-objective gain search."""

import numpy as np
import pytest

from aggsim.analysis.coverage import coverage_between_passes
from aggsim.analysis.tuning import optimal_gain, scan_gains
from aggsim.catalog import load_catalog
from aggsim.config import load_steering
from aggsim.config.terrain import Terrain
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry import ABLine
from aggsim.model import State, from_tractor, implement_from_catalog
from aggsim.sim import SimConfig, simulate

LINE = ABLine((0.0, 0.0), (1.0, 0.0))


@pytest.fixture(scope="module")
def params():
    return from_tractor(load_catalog().tractor("jd_6145r"))


@pytest.fixture(scope="module")
def geometry():
    return implement_from_catalog(load_catalog().implement("jd_1775nt_16row30"))


def _run(params, geometry, *, k=0.5, terrain=None, e0=0.0, duration=120.0, steering=None):
    cfg = SimConfig(speed=3.0, dt=0.01, duration=duration)
    ctrl = make_pure_pursuit(LINE, 3.0, PurePursuitGains(k=k, l_min=3.0), params)
    return simulate(State(0.0, e0, 0.0), LINE, ctrl, params, cfg,
                    steering=steering, terrain=terrain, geometry=geometry)


# --- coverage --------------------------------------------------------------

def test_perfect_tracking_leaves_no_skip(params, geometry):
    log = _run(params, geometry)
    cov = coverage_between_passes(log, log, geometry.working_width)
    assert cov.rms_skip == pytest.approx(0.0, abs=1e-9)
    assert cov.worst_skip == pytest.approx(0.0, abs=1e-9)
    assert cov.worst_overlap == pytest.approx(0.0, abs=1e-9)


def test_uniform_lateral_offset_creates_no_skip(params, geometry):
    """The non-obvious result: a systematic offset shifts the whole pattern
    without opening a gap. Only differential effects create skip."""
    slope = Terrain(slope_angle=np.radians(10.0))
    log = _run(params, geometry, terrain=slope)
    cov = coverage_between_passes(log, log, geometry.working_width)

    assert abs(log.implement_cross_track[-1]) > 0.5  # a large centreline offset
    assert cov.rms_skip < 0.05  # yet almost no skip


def test_skip_equals_projected_width_loss(params, geometry):
    """For identical passes, skip = w (1 - cos theta_i) exactly."""
    slope = Terrain(slope_angle=np.radians(10.0))
    log = _run(params, geometry, terrain=slope, e0=2.0)
    cov = coverage_between_passes(log, log, geometry.working_width)
    yaw = log.theta_implement - log.theta + (log.theta - LINE.heading)
    expected = geometry.working_width * (1.0 - np.cos(yaw))
    assert np.allclose(cov.skip, expected, atol=1e-9)


def test_skip_is_never_negative_for_identical_passes(params, geometry):
    """A yawed implement under-covers; it cannot over-cover."""
    log = _run(params, geometry, terrain=Terrain(slope_angle=np.radians(12.0)), e0=3.0)
    cov = coverage_between_passes(log, log, geometry.working_width)
    assert cov.skip.min() >= -1e-12


def test_opposite_direction_matches_by_mirror_symmetry(params, geometry):
    """Worked back and forth on a slope the drift mirrors, so the abutting
    edges give the same gap."""
    a = _run(params, geometry, terrain=Terrain(slope_angle=np.radians(10.0), slope_sign=1.0))
    b = _run(params, geometry, terrain=Terrain(slope_angle=np.radians(10.0), slope_sign=-1.0))
    same = coverage_between_passes(a, a, geometry.working_width, same_direction=True)
    opposite = coverage_between_passes(a, b, geometry.working_width, same_direction=False)
    assert opposite.rms_skip == pytest.approx(same.rms_skip, rel=1e-6)


def test_skip_percentage_uses_working_width(params, geometry):
    log = _run(params, geometry, terrain=Terrain(slope_angle=np.radians(10.0)))
    cov = coverage_between_passes(log, log, geometry.working_width)
    assert cov.rms_skip_percent == pytest.approx(
        100.0 * cov.rms_skip / geometry.working_width
    )


def test_coverage_requires_an_implement(params):
    log = _run(params, None, duration=10.0)
    with pytest.raises(ValueError, match="implement"):
        coverage_between_passes(log, log, 5.0)


def test_coverage_requires_equal_length_runs(params, geometry):
    a = _run(params, geometry, duration=20.0)
    b = _run(params, geometry, duration=30.0)
    with pytest.raises(ValueError, match="same length"):
        coverage_between_passes(a, b, geometry.working_width)


# --- gain search -----------------------------------------------------------

@pytest.mark.parametrize("vertex", [0.37, 0.5, 0.62, 0.8])
def test_parabolic_refinement_recovers_a_known_vertex(vertex):
    """Sub-grid resolution matters: the preliminary divergence was one to two
    grid steps, so grid-snapped optima could not support a claim."""
    gains = np.arange(0.1, 1.21, 0.05)
    scores = (gains - vertex) ** 2 + 1.0
    assert optimal_gain(gains, scores) == pytest.approx(vertex, abs=1e-6)


def test_refinement_falls_back_at_an_endpoint():
    gains = np.arange(0.1, 1.01, 0.05)
    scores = gains.copy()  # minimum at the left endpoint
    assert optimal_gain(gains, scores) == pytest.approx(0.1)


def test_refinement_falls_back_when_not_convex():
    gains = np.array([0.1, 0.2, 0.3])
    scores = np.array([1.0, 0.5, 1.0]) * -1.0  # concave
    assert optimal_gain(gains, scores) in (0.1, 0.3)


def test_scan_gains_scores_all_three_objectives(params, geometry):
    gains = np.arange(0.3, 0.71, 0.1)
    steering = load_steering()

    def run(k):
        return _run(params, geometry, k=k, e0=1.0, duration=60.0,
                    terrain=Terrain(slope_angle=np.radians(10.0), slip=0.12),
                    steering=steering)

    res = scan_gains(run, gains, geometry.working_width)
    assert len(res.rms_tractor) == len(gains)
    assert np.all(np.isfinite(res.rms_tractor))
    assert np.all(np.isfinite(res.rms_edge))
    assert np.all(np.isfinite(res.rms_skip))
    assert res.divergence == res.k_implement - res.k_tractor


def test_edge_penalty_is_non_negative(params, geometry):
    """Tuning for the tractor can never beat tuning for the implement, on the
    implement's own objective."""
    gains = np.arange(0.2, 0.91, 0.1)
    steering = load_steering()

    def run(k):
        return _run(params, geometry, k=k, e0=1.0, duration=60.0,
                    terrain=Terrain(slope_angle=np.radians(10.0), slip=0.12),
                    steering=steering)

    res = scan_gains(run, gains, geometry.working_width)
    assert res.edge_penalty_at_tractor_optimum() >= -1e-12
