"""Stage 7 groundwork: the robot description and the node wrappers.

Stage 7 is conditional in the brief and must not become a time sink. These
test the half that needs no ROS 2 and no Gazebo, so if the environment is
abandoned nothing here is lost.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from aggsim.catalog import load_catalog
from aggsim.catalog.tyres import parse_tyre, wheel_dimensions
from aggsim.control import PurePursuitGains, pure_pursuit, stanley
from aggsim.geometry import ABLine
from aggsim.model import State, from_tractor, implement_from_catalog
from aggsim.ros2 import ControllerBridge, Ros2NotAvailable, build_description
from aggsim.ros2.nodes import yaw_from_quaternion

LINE = ABLine((0.0, 0.0), (1.0, 0.0))


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def _urdf(catalog, tractor_id="jd_8r_410", implement_id="jd_1775nt_16row30"):
    tractor = catalog.tractor(tractor_id)
    implement = catalog.implement(implement_id) if implement_id else None
    geometry = implement_from_catalog(implement) if implement else None
    return ET.fromstring(build_description(tractor, implement, geometry))


# --- the description ------------------------------------------------------

def test_description_is_well_formed_xml(catalog):
    assert _urdf(catalog).tag == "robot"


def test_base_link_is_the_rear_axle(catalog):
    """The kinematic model references the rear axle. Anything else would make
    the two simulations disagree about where the machine is before any physics
    happened."""
    root = _urdf(catalog)
    assert root.find("link[@name='base_link']") is not None
    for name in ("rear_left", "rear_right"):
        joint = root.find(f"joint[@name='{name}_joint']")
        assert joint.find("parent").get("link") == "base_link"
        x = float(joint.find("origin").get("xyz").split()[0])
        assert x == pytest.approx(0.0, abs=1e-6)


def test_front_axle_sits_at_the_catalogued_wheelbase(catalog):
    root = _urdf(catalog)
    wheelbase = catalog.tractor("jd_8r_410").wheelbase.value
    joint = root.find("joint[@name='front_left_steer_joint']")
    x = float(joint.find("origin").get("xyz").split()[0])
    assert x == pytest.approx(wheelbase, abs=1e-4)


def test_wheels_are_the_size_the_tyre_codes_give(catalog):
    root = _urdf(catalog)
    dims = wheel_dimensions(catalog.tractor("jd_8r_410"))
    radius = float(root.find("link[@name='rear_left']/visual/geometry/cylinder").get("radius"))
    assert radius == pytest.approx(dims["rear_radius"], abs=1e-3)
    assert dims["rear_sourced"] is True


def test_steering_limit_matches_the_catalog(catalog):
    root = _urdf(catalog)
    limit = float(root.find("joint[@name='front_left_steer_joint']/limit").get("upper"))
    assert limit == pytest.approx(catalog.tractor("jd_8r_410").max_steer_angle.value)


def test_the_hitch_stop_matches_the_kinematic_model(catalog):
    """Both simulations must agree about what is impossible, or the physics
    run would fold a machine the kinematic run says cannot fold."""
    root = _urdf(catalog)
    geometry = implement_from_catalog(catalog.implement("jd_1775nt_16row30"))
    joint = root.find("joint[@name='hitch_joint']")
    assert joint.get("type") == "revolute"
    assert float(joint.find("limit").get("upper")) == pytest.approx(geometry.max_hitch_angle)
    assert float(joint.find("limit").get("lower")) == pytest.approx(-geometry.max_hitch_angle)


def test_hitch_sits_behind_the_rear_axle_by_the_catalogued_distance(catalog):
    root = _urdf(catalog)
    geometry = implement_from_catalog(catalog.implement("jd_1775nt_16row30"))
    x = float(root.find("joint[@name='hitch_joint']/origin").get("xyz").split()[0])
    assert x == pytest.approx(-geometry.hitch_distance, abs=1e-4)


def test_mass_matches_the_catalog(catalog):
    """A description whose machine weighs something else is describing a
    different machine."""
    root = _urdf(catalog)
    tractor = catalog.tractor("jd_8r_410")
    implement = catalog.implement("jd_1775nt_16row30")
    total = sum(float(i.find("mass").get("value")) for i in root.iter("inertial"))
    expected = tractor.mass.value + implement.mass.value
    assert total == pytest.approx(expected, rel=0.01)


def test_inertias_are_positive_and_finite(catalog):
    for inertia in _urdf(catalog).iter("inertia"):
        for axis in ("ixx", "iyy", "izz"):
            value = float(inertia.get(axis))
            assert value > 0 and math.isfinite(value)


def test_a_mounted_implement_gets_no_hitch_joint(catalog):
    root = _urdf(catalog, implement_id="landpride_rcr1860")
    assert root.find("joint[@name='hitch_joint']") is None
    assert root.find("link[@name='implement']") is not None


def test_a_tractor_alone_has_no_implement(catalog):
    root = _urdf(catalog, implement_id=None)
    assert root.find("link[@name='implement']") is None


def test_provenance_travels_with_the_description(catalog):
    """A description pulled out of this repository still says which of its
    numbers are sourced and which are assumed."""
    xml = build_description(catalog.tractor("jd_8r_410"))
    assert "source:" in xml
    assert "ASSUMED" in xml
    assert "tractordata.com" in xml


@pytest.mark.parametrize("tractor_id", ["jd_5075e", "kubota_m5_091", "monarch_mk_v",
                                        "mf_8s_265", "jd_8r_410"])
def test_every_simulatable_tractor_produces_a_description(catalog, tractor_id):
    root = ET.fromstring(build_description(catalog.tractor(tractor_id)))
    assert root.find("link[@name='base_link']") is not None


# --- the bridge -----------------------------------------------------------

def test_the_module_imports_without_ros_installed():
    """The point of the lazy import: this half of Stage 7 is usable and
    testable on a machine with no ROS."""
    import aggsim.ros2.nodes as nodes
    assert nodes.ControllerBridge is not None


def test_running_without_ros_explains_itself():
    with pytest.raises(Ros2NotAvailable, match="rclpy is not installed"):
        from aggsim.ros2.nodes import require_rclpy
        require_rclpy()


def test_the_bridge_uses_the_identical_controller(catalog):
    """The brief requires the same control code in both environments. That is
    only true if the bridge adds nothing of its own."""
    tractor = catalog.tractor("jd_6145r")
    params = from_tractor(tractor)
    bridge = ControllerBridge.from_catalog(tractor, LINE)

    for x, y, yaw in [(0.0, 0.0, 0.0), (5.0, 2.0, 0.1), (-3.0, -1.5, -0.2)]:
        direct = pure_pursuit(State(x, y, yaw), LINE, 3.0,
                              PurePursuitGains(k=0.5, l_min=3.0), params)
        assert bridge.steer(x, y, yaw, 3.0) == direct


def test_the_bridge_can_run_stanley_too(catalog):
    from aggsim.control import StanleyGains

    tractor = catalog.tractor("jd_6145r")
    params = from_tractor(tractor)
    bridge = ControllerBridge.from_catalog(tractor, LINE, controller="stanley")
    direct = stanley(State(0.0, 2.0, 0.0), LINE, 3.0, StanleyGains(k_e=2.0), params)
    assert bridge.steer(0.0, 2.0, 0.0, 3.0) == direct


def test_the_bridge_rejects_an_unknown_controller(catalog):
    with pytest.raises(ValueError, match="unknown controller"):
        ControllerBridge.from_catalog(catalog.tractor("jd_6145r"), LINE,
                                      controller="telepathy")


def test_the_required_geometry_test_holds_through_the_bridge(catalog):
    """On the line with zero heading error, zero steering. The brief's test,
    checked at the ROS boundary as well as in the simulation."""
    bridge = ControllerBridge.from_catalog(catalog.tractor("jd_6145r"), LINE)
    assert bridge.steer(10.0, 0.0, 0.0, 3.0) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("yaw", [0.0, 0.4, -0.9, 3.0, -3.0])
def test_quaternion_to_yaw_round_trips(yaw):
    z, w = math.sin(yaw / 2), math.cos(yaw / 2)
    assert yaw_from_quaternion(0.0, 0.0, z, w) == pytest.approx(yaw, abs=1e-9)


def test_articulated_tractors_are_still_refused(catalog):
    with pytest.raises(ValueError, match="articulation"):
        ControllerBridge.from_catalog(catalog.tractor("caseih_steiger_500_quadtrac"), LINE)


# --- the shared tyre data -------------------------------------------------

def test_tyre_parsing_is_shared_not_duplicated():
    """The 3D view and the robot description must agree about the machine."""
    from web.machine_geometry import machine_geometry

    catalog = load_catalog()
    tractor = catalog.tractor("jd_8r_410")
    drawn = machine_geometry(tractor, None, None)["rear_wheel"]["diameter"]
    described = wheel_dimensions(tractor)["rear_radius"] * 2
    assert drawn == pytest.approx(described, abs=1e-3)
    assert parse_tyre("480/80R50").diameter == pytest.approx(2.038, abs=0.002)
