"""Ground that changes along the pass, and the hitch stop.

Both came out of a sanity sweep over the parameter space rather than from a
specification: the sweep found the hitch winding past 1800 degrees, and found
that the cross-track error was identical at 50 m, 100 m and 200 m because the
model had one slope number for an entire field.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from aggsim.catalog import load_catalog
from aggsim.config import load_steering
from aggsim.config.terrain import SlopeProfile, Terrain
from aggsim.control import PurePursuitGains, make_pure_pursuit
from aggsim.geometry import ABLine
from aggsim.model import ImplementGeometry, State, from_tractor, implement_from_catalog
from aggsim.sim import SimConfig, simulate

LINE = ABLine((0.0, 0.0), (1.0, 0.0))


@pytest.fixture(scope="module")
def params():
    return from_tractor(load_catalog().tractor("jd_6145r"))


def _run(params, terrain=None, geometry=None, *, k=0.5, v=3.0, e0=0.0,
         duration=90.0, steering=None):
    cfg = SimConfig(speed=v, dt=0.01, duration=duration)
    ctrl = make_pure_pursuit(LINE, v, PurePursuitGains(k=k, l_min=3.0), params)
    return simulate(State(0.0, e0, 0.0), LINE, ctrl, params, cfg,
                    steering=steering, terrain=terrain, geometry=geometry)


# --- the profile -----------------------------------------------------------

def test_profile_interpolates_between_samples():
    profile = SlopeProfile(positions=np.array([0.0, 10.0, 20.0]),
                           side_slope=np.array([0.0, 0.1, 0.0]))
    assert profile.at(0.0) == pytest.approx(0.0)
    assert profile.at(5.0) == pytest.approx(0.05)
    assert profile.at(10.0) == pytest.approx(0.1)


def test_profile_holds_its_ends_rather_than_extrapolating():
    """Extrapolating a hillside past the data is inventing terrain."""
    profile = SlopeProfile(positions=np.array([0.0, 10.0]),
                           side_slope=np.array([0.05, 0.09]))
    assert profile.at(-500.0) == pytest.approx(0.05)
    assert profile.at(9999.0) == pytest.approx(0.09)


@pytest.mark.parametrize("positions,slopes,match", [
    ([0.0], [0.0], "at least two"),
    ([0.0, 1.0], [0.0], "same length"),
    ([0.0, 1.0, 0.5], [0.0, 0.0, 0.0], "must increase"),
])
def test_malformed_profiles_are_refused(positions, slopes, match):
    with pytest.raises(ValueError, match=match):
        SlopeProfile(positions=np.array(positions), side_slope=np.array(slopes))


def test_drift_follows_the_ground_under_the_machine():
    profile = SlopeProfile(positions=np.array([0.0, 100.0]),
                           side_slope=np.array([0.0, math.radians(10.0)]))
    terrain = Terrain(profile=profile)
    assert terrain.drift_at(0.0) == pytest.approx(0.0, abs=1e-9)
    assert terrain.drift_at(100.0) > 0.15
    assert terrain.drift_at(50.0) == pytest.approx(terrain.drift_at(100.0) / 2, rel=0.02)


def test_a_profile_counts_as_slope_being_enabled():
    flat = Terrain()
    rolling = Terrain(profile=SlopeProfile(positions=np.array([0.0, 10.0]),
                                           side_slope=np.array([0.01, 0.02])))
    assert not flat.slope_enabled
    assert rolling.slope_enabled


# --- behaviour -------------------------------------------------------------

def test_without_a_profile_nothing_changes(params):
    """Every earlier stage must be untouched by this extension."""
    plain = _run(params, Terrain(slope_angle=math.radians(10.0)))
    explicit = _run(params, Terrain(slope_angle=math.radians(10.0), profile=None))
    assert np.array_equal(plain.cross_track, explicit.cross_track)


def test_a_constant_profile_matches_a_constant_slope(params):
    """The two paths must agree where they describe the same ground."""
    angle = math.radians(8.0)
    uniform = _run(params, Terrain(slope_angle=angle, slope_sign=1.0))
    profile = SlopeProfile(positions=np.array([0.0, 1000.0]),
                           side_slope=np.array([angle, angle]))
    rolling = _run(params, Terrain(profile=profile))
    assert rolling.final_cross_track() == pytest.approx(uniform.final_cross_track(), abs=1e-9)


def test_error_wanders_when_the_ground_does(params):
    """A single slope number cannot produce this: the disturbance changes sign
    under the machine, so the error crosses the line more than once."""
    positions = np.linspace(0.0, 300.0, 13)
    slopes = math.radians(9.0) * np.sin(positions / 40.0)
    rolling = _run(params, Terrain(profile=SlopeProfile(positions, slopes)), duration=100.0)

    tail = rolling.cross_track[rolling.t > 20.0]
    assert tail.max() > 0.05 and tail.min() < -0.05
    assert not rolling.is_settled()

    uniform = _run(params, Terrain(slope_angle=math.radians(9.0)), duration=100.0)
    settled = uniform.cross_track[uniform.t > 20.0]
    assert settled.min() > 0.0  # pushed one way and held there


def test_a_flat_profile_leaves_the_machine_on_the_line(params):
    profile = SlopeProfile(positions=np.array([0.0, 500.0]), side_slope=np.zeros(2))
    log = _run(params, Terrain(profile=profile), e0=2.0)
    assert abs(log.final_cross_track()) < 1e-6


# --- the hitch stop --------------------------------------------------------

def test_hitch_angle_cannot_exceed_its_stop(params):
    """Before this the sweep found the hitch winding past 1800 degrees."""
    catalog = load_catalog()
    geometry = implement_from_catalog(catalog.implement("kuhn_excelerator_8005_50"))
    log = _run(params, Terrain(slope_angle=math.radians(20.0)), geometry=geometry,
               k=0.1, v=12.0, e0=8.0, duration=40.0, steering=load_steering())

    relative = np.abs(np.degrees(log.theta_implement - log.theta))
    assert relative.max() <= math.degrees(geometry.max_hitch_angle) + 1e-6


def test_reaching_the_stop_is_reported_not_hidden(params):
    catalog = load_catalog()
    geometry = implement_from_catalog(catalog.implement("kuhn_excelerator_8005_50"))
    log = _run(params, Terrain(slope_angle=math.radians(20.0)), geometry=geometry,
               k=0.1, v=12.0, e0=8.0, duration=40.0, steering=load_steering())
    assert log.jackknifed is True
    assert log.jackknife_time is not None and log.jackknife_time > 0


def test_an_ordinary_run_never_reaches_the_stop(params):
    catalog = load_catalog()
    geometry = implement_from_catalog(catalog.implement("jd_1775nt_16row30"))
    log = _run(params, Terrain(slope_angle=math.radians(10.0)), geometry=geometry, e0=3.0)
    assert log.jackknifed is False
    assert log.jackknife_time is None


def test_the_stop_does_not_disturb_normal_runs(params):
    """Clamping must be inert until it is needed."""
    catalog = load_catalog()
    geometry = implement_from_catalog(catalog.implement("jd_1590_10ft"))
    log = _run(params, geometry=geometry, e0=3.0)
    assert log.jackknifed is False
    assert abs(log.final_cross_track()) < 1e-3


def test_geometry_rejects_an_impossible_stop():
    with pytest.raises(ValueError, match="max_hitch_angle"):
        ImplementGeometry("trailed", 6.0, 0.9, 4.5, max_hitch_angle=0.0)
    with pytest.raises(ValueError, match="max_hitch_angle"):
        ImplementGeometry("trailed", 6.0, 0.9, 4.5, max_hitch_angle=4.0)


def test_a_mounted_implement_has_no_stop_to_reach(params):
    log = _run(params, Terrain(slope_angle=math.radians(15.0)),
               geometry=ImplementGeometry("mounted", 3.0), e0=5.0)
    assert log.jackknifed is False
