"""Multi-pass field work: the plan, the pass switching, and cross-pass coverage.

The single-line stages verify tracking. These verify the things that only
exist once there is a second pass: that the machine changes line at the right
place, that a return pass is scored in its own frame, that the side slope
pushes the other way coming back, and that two neighbours are compared edge
against the correct edge.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from aggsim.analysis.coverage import coverage_across_passes, coverage_between_passes
from aggsim.catalog import load_catalog
from aggsim.config import load_steering
from aggsim.config.terrain import Terrain
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry.field import FieldPlan
from aggsim.model import State, from_tractor, implement_from_catalog
from aggsim.sim import SimConfig, simulate

WIDTH = 12.192


@pytest.fixture(scope="module")
def plan():
    return FieldPlan(working_width=WIDTH, passes=4, length=140.0)


@pytest.fixture(scope="module")
def rig():
    cat = load_catalog()
    params = from_tractor(cat.tractor("jd_6145r"))
    geom = implement_from_catalog(cat.implement("jd_1775nt_16row30"))
    return params, geom


def run(plan, rig, terrain, speed=3.0, duration=420.0):
    params, geom = rig
    gains = PurePursuitGains(k=0.5, l_min=3.0)

    def make(line):
        return make_pure_pursuit(line, speed, gains, params)

    x0, y0, h0 = plan.entry(0)
    return simulate(
        State(x0, y0, h0), plan.line(0), make(plan.line(0)), params,
        SimConfig(speed=speed, dt=0.02, duration=duration),
        steering=load_steering(), terrain=terrain, geometry=geom,
        plan=plan, make_controller=make,
    )


# ---------------------------------------------------------------- the plan

def test_passes_are_spaced_one_working_width_apart(plan):
    for i in range(plan.passes - 1):
        assert plan.offset(i) - plan.offset(i + 1) == pytest.approx(WIDTH)


def test_alternate_passes_run_opposite_ways(plan):
    for i in range(plan.passes):
        line = plan.line(i)
        heading = math.atan2(line.direction[1], line.direction[0])
        expected = 0.0 if plan.forward(i) else math.pi
        assert math.cos(heading - expected) == pytest.approx(1.0)


def test_a_pass_ends_only_past_the_headland(plan):
    assert not plan.finished(0, plan.length)  # still on the crop
    assert plan.finished(0, plan.length + plan.headland + 1.0)
    assert not plan.finished(1, plan.length)  # pass 1 runs the other way
    assert plan.finished(1, -plan.headland - 1.0)


def test_the_last_pass_never_finishes(plan):
    """There is nothing to turn onto, so the run simply ends."""
    assert not plan.finished(plan.passes - 1, 1e6)


def test_entry_matches_the_line_it_starts(plan):
    for i in range(plan.passes):
        x, y, heading = plan.entry(i)
        assert y == pytest.approx(plan.offset(i))
        line = plan.line(i)
        assert math.cos(heading - math.atan2(*line.direction[::-1])) == pytest.approx(1.0)


def test_a_plan_needs_a_positive_width_and_at_least_one_pass():
    for kwargs in ({"working_width": 0.0}, {"passes": 0}, {"length": -1.0},
                   {"headland": -1.0}):
        base = {"working_width": WIDTH, "passes": 2, "length": 100.0}
        base.update(kwargs)
        with pytest.raises(ValueError):
            FieldPlan(**base)


# ------------------------------------------------------------ pass switching

def test_the_run_works_every_pass(plan, rig):
    log = run(plan, rig, Terrain(slip=0.1))
    assert log.passes_worked == plan.passes


def test_the_run_stops_at_the_end_of_the_field(plan, rig):
    """Without a stop the last pass has nothing to turn onto and the machine
    drives hundreds of metres down an infinite line. `duration` is an upper
    bound on the work, not the length of the log."""
    log = run(plan, rig, Terrain(slip=0.1), duration=420.0)
    assert log.t[-1] < 420.0

    # The machine may run past the headland while it comes round -- the turn
    # itself takes room -- but on the order of a turning circle, not the
    # hundreds of metres it covered before the stop existed.
    margin = plan.headland + 25.0
    assert log.x.min() > -margin
    assert log.x.max() < plan.length + margin


def test_pass_index_only_ever_advances(plan, rig):
    log = run(plan, rig, Terrain(slip=0.1))
    assert np.all(np.diff(log.pass_index) >= 0)


def test_each_pass_settles_onto_its_own_line(plan, rig):
    """Error is measured against the active line, so it returns near zero on
    every pass rather than growing by a working width each time."""
    log = run(plan, rig, Terrain(slip=0.1))
    for i in range(log.passes_worked):
        sl = log.pass_slice(i)
        settled = log.cross_track[sl][-200:]  # last 4 s of the pass
        assert abs(np.mean(settled)) < 0.30, f"pass {i} never settled"


def test_the_machine_is_near_the_nominal_line_of_each_pass(plan, rig):
    log = run(plan, rig, Terrain(slip=0.1))
    for i in range(log.passes_worked):
        sl = log.pass_slice(i)
        y = log.y[sl][-200:]
        assert abs(np.mean(y) - plan.offset(i)) < 0.5


# ------------------------------------------------- the slope flips on return

def test_side_slope_drift_reverses_on_the_return_pass(plan, rig):
    """The hillside has not moved; the machine has turned round. So the drift
    that pushed it one way going out pushes it the other way coming back, and
    the settled error must change sign between adjacent passes."""
    log = run(plan, rig, Terrain(slope_angle=math.radians(8.0), slip=0.1))
    settled = [float(np.mean(log.cross_track[log.pass_slice(i)][-200:]))
               for i in range(log.passes_worked)]
    for i in range(len(settled) - 1):
        assert settled[i] * settled[i + 1] < 0, (
            f"passes {i} and {i+1} drifted the same way: {settled}")


def test_flat_ground_leaves_no_settled_offset_to_flip(plan, rig):
    log = run(plan, rig, Terrain(slip=0.1))
    for i in range(log.passes_worked):
        settled = log.cross_track[log.pass_slice(i)][-200:]
        assert abs(np.mean(settled)) < 0.05


# ------------------------------------------------------- cross-pass coverage

def test_adjacent_passes_abut_rather_than_sitting_a_width_apart(plan, rig):
    """The regression this file exists for. Each boundary is reached by a
    forward pass's RIGHT edge and a return pass's LEFT edge; using one rule for
    both compares edges a whole working width apart."""
    log = run(plan, rig, Terrain(slip=0.1))
    for i in range(log.passes_worked - 1):
        cov = coverage_across_passes(log, plan, i)
        assert abs(cov.mean_skip) < 0.10, (
            f"passes {i}|{i+1} mean skip {cov.mean_skip:.3f} m")
        assert cov.rms_skip < 0.10


def test_coverage_is_worse_on_a_slope_than_on_the_flat(plan, rig):
    flat = run(plan, rig, Terrain(slip=0.1))
    tilted = run(plan, rig, Terrain(slope_angle=math.radians(8.0), slip=0.1))

    def lost(log):
        return np.mean([coverage_across_passes(log, plan, i).gap_area_per_100m
                        for i in range(log.passes_worked - 1)])

    assert lost(tilted) > lost(flat)


def test_gap_area_counts_only_gaps_not_overlap(plan, rig):
    """Overlap somewhere else does not backfill a skip."""
    log = run(plan, rig, Terrain(slip=0.1))
    cov = coverage_across_passes(log, plan, 0)
    assert cov.gap_area_per_100m >= 0.0
    if cov.worst_skip == 0.0:
        assert cov.gap_area_per_100m == 0.0


def test_coverage_needs_a_real_pair(plan, rig):
    log = run(plan, rig, Terrain(slip=0.1))
    with pytest.raises(ValueError, match="pass"):
        coverage_across_passes(log, plan, log.passes_worked - 1)


def test_single_pass_coverage_rejects_a_multi_pass_log(plan, rig):
    """A multi-pass log includes headland turns, where the implement is metres
    off a line it is not yet following. Comparing that against itself produced
    a large, meaningless number instead of an error."""
    log = run(plan, rig, Terrain(slip=0.1))
    _, geom = rig
    with pytest.raises(ValueError, match="passes"):
        coverage_between_passes(log, log, geom.working_width)
