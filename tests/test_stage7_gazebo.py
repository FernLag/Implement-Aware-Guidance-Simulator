"""Stage 7: the world, the physics description, and the divergence measure.

None of this needs ROS or Gazebo. What is testable here is everything that
decides whether the two simulations are describing the same experiment, which
is where a comparison goes wrong long before the physics does.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from aggsim.analysis.divergence import (
    EnvelopePoint,
    Trajectory,
    compare,
    validity_envelope,
)
from aggsim.catalog import load_catalog
from aggsim.model import implement_from_catalog
from aggsim.ros2.urdf import build_description
from aggsim.ros2.world import WorldParams, build_world


@pytest.fixture(scope="module")
def rig():
    catalog = load_catalog()
    tractor = catalog.tractor("jd_6145r")
    implement = catalog.implement("jd_1775nt_16row30")
    return tractor, implement, implement_from_catalog(implement)


# ------------------------------------------------------------------ the world

def test_positive_side_slope_rolls_the_ground_so_it_rises_to_the_right():
    """Stage 3 defines a positive side slope as ground rising to the RIGHT,
    which drifts the machine left. Travel is +x and left is +y, so the ground
    must rise toward -y, which is a NEGATIVE roll about +x. Getting this
    backwards would compare two different experiments and report the
    difference as physics."""
    assert WorldParams(slope_deg=8.0, slope_sign=1.0).roll < 0
    assert WorldParams(slope_deg=8.0, slope_sign=-1.0).roll > 0
    assert WorldParams(slope_deg=0.0).roll == pytest.approx(0.0)


def test_roll_magnitude_is_the_slope_angle():
    p = WorldParams(slope_deg=12.0)
    assert abs(math.degrees(p.roll)) == pytest.approx(12.0)


def test_world_is_valid_xml_with_a_tilted_ground_plane():
    root = ET.fromstring(build_world(WorldParams(slope_deg=8.0)))
    ground = root.find("./world/model[@name='ground']")
    assert ground is not None
    roll = float(ground.find("pose").text.split()[3])
    # The file writes six decimals, which is 6e-5 of a degree.
    assert roll == pytest.approx(WorldParams(slope_deg=8.0).roll, abs=1e-6)


def test_world_carries_friction_on_the_collision_surface():
    """Coulomb friction is the thing the kinematic model does not have. If it
    is missing here the physics simulation is not testing anything."""
    root = ET.fromstring(build_world(WorldParams(mu=0.8, mu2=0.6)))
    ode = root.find("./world/model/link/collision/surface/friction/ode")
    assert float(ode.find("mu").text) == pytest.approx(0.8)
    assert float(ode.find("mu2").text) == pytest.approx(0.6)


def test_world_states_its_assumptions_in_the_file():
    """A world file that leaves the repository must carry the provenance of
    the numbers in it."""
    text = build_world(WorldParams())
    assert "ASSUMED VALUES" in text
    for key in WorldParams().assumptions():
        assert key in text


def test_impossible_worlds_are_refused():
    for kwargs in ({"slope_deg": -1.0}, {"slope_deg": 45.0}, {"mu": 0.0},
                   {"step": 1.0}, {"size": 0.0}, {"slope_sign": 0.0}):
        with pytest.raises(ValueError):
            WorldParams(**kwargs)


# ------------------------------------------------- the physics description

def test_gazebo_description_adds_contact_but_not_dimensions(rig):
    """The physics extensions must not move anything. If they do, the two
    simulations stop describing one machine."""
    tractor, implement, geometry = rig
    plain = ET.fromstring(build_description(tractor, implement, geometry))
    physical = ET.fromstring(
        build_description(tractor, implement, geometry, gazebo=True))

    def joint_origins(root):
        return {j.get("name"): j.find("origin").get("xyz")
                for j in root.findall("joint")
                if j.find("origin") is not None
                and not j.get("name").startswith("implement_")}

    shared = joint_origins(plain)
    assert shared, "no joints to compare"
    for name, xyz in shared.items():
        assert joint_origins(physical)[name] == xyz


def test_gazebo_description_has_a_steering_system(rig):
    tractor, implement, geometry = rig
    root = ET.fromstring(
        build_description(tractor, implement, geometry, gazebo=True))
    plugins = [p.get("filename") for p in root.iter("plugin")]
    assert "gz-sim-ackermann-steering-system" in plugins


def test_steering_system_uses_the_catalog_wheelbase(rig):
    """The plugin reconstructs a steering angle from the commanded yaw rate.
    If its wheelbase differs from the controller's, the physics machine steers
    by a different amount than was asked for and the comparison is void."""
    tractor, implement, geometry = rig
    root = ET.fromstring(
        build_description(tractor, implement, geometry, gazebo=True))
    plugin = next(p for p in root.iter("plugin")
                  if p.get("filename") == "gz-sim-ackermann-steering-system")
    assert float(plugin.find("wheel_base").text) == pytest.approx(
        tractor.wheelbase.value, abs=1e-3)
    assert float(plugin.find("steering_limit").text) == pytest.approx(
        tractor.max_steer_angle.value, abs=1e-3)


def test_every_tractor_wheel_gets_friction(rig):
    tractor, implement, geometry = rig
    root = ET.fromstring(
        build_description(tractor, implement, geometry, gazebo=True))
    withmu = {g.get("reference") for g in root.findall("gazebo")
              if g.find("mu1") is not None}
    for wheel in ("rear_left", "rear_right", "front_left", "front_right"):
        assert wheel in withmu


def test_a_trailed_implement_is_carried_by_wheels_under_physics(rig):
    """In the kinematic model the implement axle is an abstract rolling
    constraint. Under physics something has to hold the frame up, or it hangs
    off the drawbar and ploughs the ground with a corner."""
    tractor, implement, geometry = rig
    plain = ET.fromstring(build_description(tractor, implement, geometry))
    physical = ET.fromstring(
        build_description(tractor, implement, geometry, gazebo=True))
    names = lambda r: {l.get("name") for l in r.findall("link")}  # noqa: E731
    assert "implement_left" not in names(plain)
    assert {"implement_left", "implement_right"} <= names(physical)


def test_the_hitch_stop_is_the_same_in_both_models(rig):
    """A drawbar that folds further in one simulation than the other is not the
    same machine."""
    tractor, implement, geometry = rig
    root = ET.fromstring(
        build_description(tractor, implement, geometry, gazebo=True))
    limit = root.find("./joint[@name='hitch_joint']/limit")
    assert float(limit.get("upper")) == pytest.approx(geometry.max_hitch_angle)
    assert float(limit.get("lower")) == pytest.approx(-geometry.max_hitch_angle)


# --------------------------------------------------------------- divergence

def _straight(speed, n=400, seconds=20.0, y=0.0):
    t = np.linspace(0, seconds, n)
    return Trajectory(t=t, x=speed * t, y=np.full(n, y),
                      theta=np.zeros(n), cross_track=np.full(n, y))


def test_a_slower_physics_run_is_not_counted_as_a_tracking_error():
    """The physics machine slips, so it covers less ground in the same time.
    Compared sample by sample in time that shows up as a growing position
    error which has nothing to do with tracking. Compared at equal distance
    along the line it does not."""
    div = compare(_straight(3.0), _straight(2.85))
    assert div.rms_lateral == pytest.approx(0.0, abs=1e-9)
    assert div.speed_ratio == pytest.approx(0.95, abs=1e-3)


def test_a_real_lateral_difference_is_reported():
    div = compare(_straight(3.0, y=0.0), _straight(3.0, y=0.25))
    assert div.max_lateral == pytest.approx(0.25, abs=1e-6)
    assert not div.within(0.10)
    assert div.within(0.30)


def test_breakdown_distance_is_where_tolerance_is_first_exceeded():
    t = np.linspace(0, 20, 400)
    x = 3.0 * t
    drift = np.where(x < 30.0, 0.0, (x - 30.0) * 0.01)
    physics = Trajectory(t=t, x=x, y=drift, theta=np.zeros(400),
                         cross_track=drift)
    div = compare(_straight(3.0), physics)
    where = div.breakdown_distance(0.10)
    assert where is not None
    assert where == pytest.approx(40.0, abs=2.0)


def test_runs_that_do_not_overlap_are_refused():
    a = _straight(3.0)
    b = Trajectory(t=a.t, x=a.x + 1000.0, y=a.y, theta=a.theta,
                   cross_track=a.cross_track)
    with pytest.raises(ValueError):
        compare(a, b)


def test_envelope_reports_the_boundary_not_a_verdict():
    def point(label, speed, slope, mass, offset):
        return EnvelopePoint(label=label, speed=speed, slope_deg=slope,
                             implement_mass=mass,
                             divergence=compare(_straight(3.0),
                                                _straight(3.0, y=offset)))

    points = [point("slow", 2.0, 0.0, 5000.0, 0.02),
              point("mid", 4.0, 5.0, 5000.0, 0.05),
              point("fast", 8.0, 15.0, 11000.0, 0.40)]
    env = validity_envelope(points, tolerance_m=0.10)
    assert env["within"] == 2
    assert env["speed_ok"] == (2.0, 4.0)
    assert env["slope_ok"] == (0.0, 5.0)
    assert env["worst"] == "fast"


def test_an_empty_envelope_is_refused():
    with pytest.raises(ValueError):
        validity_envelope([], 0.1)
