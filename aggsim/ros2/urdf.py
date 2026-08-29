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


def build_description(tractor: Tractor, implement: Implement | None = None,
                      geometry=None) -> str:
    """URDF for a tractor, optionally with an implement on the drawbar."""
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

    raw = ET.tostring(robot, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ")


def write_description(path: Path, tractor: Tractor, implement=None, geometry=None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_description(tractor, implement, geometry))
    return path
