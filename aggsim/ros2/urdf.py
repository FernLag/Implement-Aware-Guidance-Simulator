"""A robot description generated from the equipment catalog.

The brief asks for a tractor-plus-implement URDF with an articulated hitch
joint for trailed implements, with link dimensions and masses taken from the
Stage 0 catalog. Generating it rather than hand-writing it means the physics
simulation and the kinematic model are describing the same machine: one
wheelbase, one set of wheel diameters, one hitch geometry.

Where a dimension is sourced it is used. Where it is an assumption it is used
and said so, in a comment written into the file itself, so a description
pulled out of this repository still carries the provenance of the numbers in
it.

Inertias are computed from the primitive each link is approximated by, a solid
cylinder for wheels and a box for bodies. They are approximations of an
approximation and are labelled as such: a kinematic model has no use for them
at all, and Gazebo needs something non-zero to integrate.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

from ..catalog.schema import Implement, Tractor
from ..catalog.tyres import wheel_dimensions
from ..model.implement import DEFAULT_MAX_HITCH_ANGLE

# Split of tractor mass between the bodies, so the total matches the catalog.
# Not published by anyone; a rear-biased split is typical of a machine built
# to pull.
CHASSIS_FRACTION = 0.62
WHEEL_FRACTION = 0.38


def _box_inertia(mass: float, x: float, y: float, z: float) -> dict[str, float]:
    return {
        "ixx": mass * (y * y + z * z) / 12.0,
        "iyy": mass * (x * x + z * z) / 12.0,
        "izz": mass * (x * x + y * y) / 12.0,
    }


def _cylinder_inertia(mass: float, radius: float, length: float) -> dict[str, float]:
    radial = mass * (3.0 * radius * radius + length * length) / 12.0
    return {"ixx": radial, "iyy": radial, "izz": mass * radius * radius / 2.0}


def _inertial(parent: ET.Element, mass: float, inertia: dict[str, float],
              origin: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> None:
    node = ET.SubElement(parent, "inertial")
    ET.SubElement(node, "origin", xyz=" ".join(f"{v:.4f}" for v in origin), rpy="0 0 0")
    ET.SubElement(node, "mass", value=f"{mass:.3f}")
    ET.SubElement(node, "inertia", ixy="0", ixz="0", iyz="0",
                  **{k: f"{v:.4f}" for k, v in inertia.items()})


def _visual_box(parent: ET.Element, size: tuple[float, float, float],
                origin: tuple[float, float, float], material: str) -> None:
    for tag in ("visual", "collision"):
        node = ET.SubElement(parent, tag)
        ET.SubElement(node, "origin", xyz=" ".join(f"{v:.4f}" for v in origin), rpy="0 0 0")
        geometry = ET.SubElement(node, "geometry")
        ET.SubElement(geometry, "box", size=" ".join(f"{v:.4f}" for v in size))
        if tag == "visual":
            ET.SubElement(node, "material", name=material)


def _wheel_link(robot: ET.Element, name: str, radius: float, width: float,
                mass: float) -> None:
    link = ET.SubElement(robot, "link", name=name)
    _inertial(link, mass, _cylinder_inertia(mass, radius, width))
    for tag in ("visual", "collision"):
        node = ET.SubElement(link, tag)
        # A URDF cylinder stands on its z axis, so it is rolled to lie on the
        # wheel axis.
        ET.SubElement(node, "origin", xyz="0 0 0", rpy="1.5708 0 0")
        geometry = ET.SubElement(node, "geometry")
        ET.SubElement(geometry, "cylinder", radius=f"{radius:.4f}", length=f"{width:.4f}")
        if tag == "visual":
            ET.SubElement(node, "material", name="tyre")


# Contact stiffness and damping for a tyre on soil. Neither is published, and
# neither is a property of any machine: they are what Gazebo needs to make a
# contact behave like something other than a rock hitting glass.
CONTACT_KP = 1.0e6
CONTACT_KD = 1.0e3


def _gazebo_friction(robot: ET.Element, link: str, mu: float, mu2: float) -> None:
    """Coulomb friction on one wheel, which the kinematic model has none of."""
    node = ET.SubElement(robot, "gazebo", reference=link)
    ET.SubElement(node, "mu1").text = f"{mu}"
    ET.SubElement(node, "mu2").text = f"{mu2}"
    ET.SubElement(node, "kp").text = f"{CONTACT_KP}"
    ET.SubElement(node, "kd").text = f"{CONTACT_KD}"


def add_gazebo_extensions(robot: ET.Element, tractor: Tractor,
                          wheels: list[str], has_implement_wheels: bool,
                          mu: float = 0.75, mu2: float = 0.65,
                          topic: str = "/cmd_vel") -> None:
    """Everything Gazebo needs that a kinematic model has no use for.

    The steering command still comes from the same controller: the node
    publishes a Twist whose yaw rate is the bicycle model's, and the Ackermann
    system turns that back into a steering angle using the same wheelbase. What
    happens after that -- whether the tyre actually goes where it points -- is
    the physics, and is the entire subject of Stage 7.
    """
    from ..catalog.tyres import wheel_dimensions

    for link in wheels:
        _gazebo_friction(robot, link, mu, mu2)

    dims = wheel_dimensions(tractor)
    track = dims["track_width"]
    L = tractor.wheelbase.value

    node = ET.SubElement(robot, "gazebo")
    plugin = ET.SubElement(
        node, "plugin",
        filename="gz-sim-ackermann-steering-system",
        name="gz::sim::systems::AckermannSteering")
    for tag, value in (
        ("left_joint", "rear_left_joint"),
        ("right_joint", "rear_right_joint"),
        ("left_steering_joint", "front_left_steer_joint"),
        ("right_steering_joint", "front_right_steer_joint"),
        ("wheel_separation", f"{track:.4f}"),
        ("kingpin_width", f"{track * 0.88:.4f}"),
        ("wheel_base", f"{L:.4f}"),
        ("steering_limit", f"{tractor.max_steer_angle.value:.4f}"),
        ("wheel_radius", f"{dims['rear_radius']:.4f}"),
        ("topic", topic),
        ("odom_topic", "/odom"),
        ("frame_id", "world"),
        ("child_frame_id", "base_link"),
        ("odom_publish_frequency", "50"),
    ):
        ET.SubElement(plugin, tag).text = value

    # Joint states, so the hitch angle can be compared against the kinematic
    # model's fifth state rather than inferred from the pose.
    states = ET.SubElement(robot, "gazebo")
    ET.SubElement(states, "plugin",
                  filename="gz-sim-joint-state-publisher-system",
                  name="gz::sim::systems::JointStatePublisher")

    if has_implement_wheels:
        for link in ("implement_left", "implement_right"):
            _gazebo_friction(robot, link, mu, mu2)


def build_description(tractor: Tractor, implement: Implement | None = None,
                      geometry=None, gazebo: bool = False,
                      mu: float = 0.75, mu2: float = 0.65) -> str:
    """URDF for a tractor, optionally with an implement on the drawbar.

    With `gazebo` set, the description also carries what a physics simulation
    needs and a kinematic model does not: Coulomb friction at each contact, a
    steering system, and wheels under a trailed implement so that it is held
    up by the ground rather than by the drawbar. Those additions do not change
    a single dimension; they only say what happens where the machine touches
    the earth, which is precisely what Stage 7 is measuring.
    """
    implement_wheels = False
    robot = ET.Element("robot", name=f"{tractor.id}"
                       + (f"__{implement.id}" if implement else ""))

    provenance = [
        "",
        f"  Generated from the equipment catalog for {tractor.name}.",
        "",
        f"  wheelbase       {tractor.wheelbase.value:.3f} m  "
        + ("ASSUMED" if tractor.wheelbase.assumed else f"source: {tractor.wheelbase.source}"),
        f"  mass            {tractor.mass.value:.0f} kg  "
        + ("ASSUMED" if tractor.mass.assumed else f"source: {tractor.mass.source}"),
        f"  front tyre      {tractor.tire_front or 'not published'}",
        f"  rear tyre       {tractor.tire_rear or 'not published'}",
        "",
        "  ASSUMED, because no manufacturer in this catalog publishes them:",
        "",
        "    track width       ASSUMED  derived from rear tyre diameter",
        "    body dimensions   ASSUMED  proportions of the wheelbase",
        f"    mass split        ASSUMED  {CHASSIS_FRACTION:.2f} chassis / "
        f"{WHEEL_FRACTION:.2f} wheels",
        "    steering limit    ASSUMED  see the catalog entry",
        "",
        "  Inertias are computed from the primitive each link is approximated",
        "  by, so they are approximations of an approximation. Gazebo needs",
        "  something non-zero to integrate; the kinematic model this is meant",
        "  to be checked against has no use for them at all.",
    ]
    if implement is not None:
        provenance += [
            "",
            f"  Implement: {implement.name}",
            f"  working width   {implement.working_width.value:.3f} m  "
            + ("ASSUMED" if implement.working_width.assumed
               else f"source: {implement.working_width.source}"),
            "  hitch geometry  ASSUMED, and swept in Stage 6",
        ]
    robot.append(ET.Comment("\n".join(provenance) + "\n"))

    dims = wheel_dimensions(tractor)
    L = tractor.wheelbase.value
    track = dims["track_width"]
    front_r = dims["front_radius"]
    rear_r = dims["rear_radius"]
    front_w = dims["front_width"]
    rear_w = dims["rear_width"]

    total = tractor.mass.value
    chassis_mass = total * CHASSIS_FRACTION
    wheel_mass = total * WHEEL_FRACTION / 4.0

    for name, rgba in (("chassis", "0.21 0.49 0.17 1"), ("tyre", "0.15 0.13 0.10 1"),
                       ("implement", "0.64 0.35 0.20 1")):
        material = ET.SubElement(robot, "material", name=name)
        ET.SubElement(material, "color", rgba=rgba)

    # base_link is at the rear axle, matching the kinematic model's reference
    # point. Anything else would make the two simulations disagree about where
    # the machine is before any physics happened.
    base = ET.SubElement(robot, "link", name="base_link")
    body_len, body_w, body_h = L * 1.30, track * 0.62, rear_r * 1.10
    _inertial(base, chassis_mass,
              _box_inertia(chassis_mass, body_len, body_w, body_h),
              (L * 0.45, 0.0, rear_r * 0.9))
    _visual_box(base, (body_len, body_w, body_h), (L * 0.45, 0.0, rear_r * 0.9), "chassis")

    axles = [
        ("rear_left", 0.0, track / 2, rear_r, rear_w, False),
        ("rear_right", 0.0, -track / 2, rear_r, rear_w, False),
        ("front_left", L, track / 2 * 0.88, front_r, front_w, True),
        ("front_right", L, -track / 2 * 0.88, front_r, front_w, True),
    ]
    for name, x, y, radius, width, steered in axles:
        if steered:
            knuckle = f"{name}_steer"
            ET.SubElement(robot, "link", name=knuckle)
            joint = ET.SubElement(robot, "joint", name=f"{knuckle}_joint", type="revolute")
            ET.SubElement(joint, "parent", link="base_link")
            ET.SubElement(joint, "child", link=knuckle)
            ET.SubElement(joint, "origin", xyz=f"{x:.4f} {y:.4f} {radius:.4f}", rpy="0 0 0")
            ET.SubElement(joint, "axis", xyz="0 0 1")
            limit = tractor.max_steer_angle.value
            ET.SubElement(joint, "limit", lower=f"{-limit:.4f}", upper=f"{limit:.4f}",
                          effort="4000", velocity="1.0")
            parent, origin = knuckle, (0.0, 0.0, 0.0)
        else:
            parent, origin = "base_link", (x, y, radius)

        _wheel_link(robot, name, radius, width, wheel_mass)
        joint = ET.SubElement(robot, "joint", name=f"{name}_joint", type="continuous")
        ET.SubElement(joint, "parent", link=parent)
        ET.SubElement(joint, "child", link=name)
        ET.SubElement(joint, "origin",
                      xyz=" ".join(f"{v:.4f}" for v in origin), rpy="0 0 0")
        ET.SubElement(joint, "axis", xyz="0 1 0")

    if implement is not None and geometry is not None:
        a, b = geometry.hitch_distance, geometry.implement_wheelbase
        width = geometry.working_width
        mass = implement.mass.value

        if geometry.type == "trailed" and b > 0:
            # The hitch is the whole reason this description exists: a revolute
            # joint whose limit is the same mechanical stop the kinematic model
            # enforces, so the two agree about what is impossible.
            hitch = ET.SubElement(robot, "link", name="hitch")
            _inertial(hitch, 5.0, _box_inertia(5.0, 0.2, 0.2, 0.2))
            joint = ET.SubElement(robot, "joint", name="hitch_joint", type="revolute")
            ET.SubElement(joint, "parent", link="base_link")
            ET.SubElement(joint, "child", link="hitch")
            ET.SubElement(joint, "origin", xyz=f"{-a:.4f} 0 {rear_r * 0.55:.4f}", rpy="0 0 0")
            ET.SubElement(joint, "axis", xyz="0 0 1")
            ET.SubElement(joint, "limit",
                          lower=f"{-geometry.max_hitch_angle:.4f}",
                          upper=f"{geometry.max_hitch_angle:.4f}",
                          effort="20000", velocity="2.0")
            ET.SubElement(joint, "dynamics", damping="40.0", friction="10.0")
            parent, offset = "hitch", -b
        else:
            parent, offset = "base_link", -a

        frame = ET.SubElement(robot, "link", name="implement")
        depth = max(0.8, width * 0.06)
        _inertial(frame, mass, _box_inertia(mass, depth, width, 0.6))
        _visual_box(frame, (depth, width, 0.6), (0.0, 0.0, 0.0), "implement")

        joint = ET.SubElement(robot, "joint", name="implement_joint", type="fixed")
        ET.SubElement(joint, "parent", link=parent)
        ET.SubElement(joint, "child", link="implement")
        ET.SubElement(joint, "origin", xyz=f"{offset:.4f} 0 0.6", rpy="0 0 0")

        # Under physics a trailed implement has to be carried by something. In
        # the kinematic model it is a rolling constraint at an abstract axle;
        # here that axle needs wheels, or the frame hangs off the drawbar and
        # ploughs the ground with its corner. The lateral grip of these wheels
        # is what makes the hitch angle behave, so their friction is swept with
        # everything else.
        if gazebo and geometry.type == "trailed" and b > 0:
            imp_r = max(0.45, rear_r * 0.62)
            imp_w = max(0.25, rear_w * 0.7)
            imp_mass = max(50.0, mass * 0.06)
            for side, sign in (("implement_left", 1.0), ("implement_right", -1.0)):
                _wheel_link(robot, side, imp_r, imp_w, imp_mass)
                wj = ET.SubElement(robot, "joint", name=f"{side}_joint",
                                   type="continuous")
                ET.SubElement(wj, "parent", link="implement")
                ET.SubElement(wj, "child", link=side)
                ET.SubElement(wj, "origin",
                              xyz=f"0 {sign * width * 0.22:.4f} {imp_r - 0.6:.4f}",
                              rpy="0 0 0")
                ET.SubElement(wj, "axis", xyz="0 1 0")
            implement_wheels = True

    if gazebo:
        add_gazebo_extensions(
            robot, tractor,
            ["rear_left", "rear_right", "front_left", "front_right"],
            implement_wheels, mu=mu, mu2=mu2,
        )

    raw = ET.tostring(robot, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ")


def write_description(path: Path, tractor: Tractor, implement=None, geometry=None,
                      gazebo: bool = False, mu: float = 0.75,
                      mu2: float = 0.65) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_description(tractor, implement, geometry,
                                      gazebo=gazebo, mu=mu, mu2=mu2))
    return path
