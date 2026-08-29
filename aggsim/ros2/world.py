"""A Gazebo world for the Stage 7 comparison.

Stage 7 exists to find where the kinematic model stops being trustworthy, so
the world has to differ from that model in exactly the ways the brief names:
tyres that can slip, weight that transfers, an implement that touches the
ground and pulls back. Everything else should be as close to identical as it
can be made, or the divergence measured is a difference of setup rather than
of physics.

SIDE SLOPE. The kinematic model represents a side slope as a lateral drift
velocity. Here it is what it actually is: a tilted floor, with gravity doing
the work. That is the single most important difference in the whole stage,
because it is the one place the kinematic model replaces a force with an
assumed kinematic consequence.

THE SIGN. Stage 3 defines a positive side slope as ground rising to the
RIGHT of travel, which makes the machine drift left, and cross-track error is
positive to the left. Travel is along +x and left is +y, so ground rising to
the right means height increasing toward -y. A right-handed rotation about +x
by angle phi raises +y, so the roll applied here is -phi. Getting this
backwards would produce a beautifully executed comparison of two different
experiments.

FRICTION. Coulomb friction between tyre and soil is what the kinematic model
has no representation of at all: it assumes the wheel goes where it points.
The coefficients here are assumptions and are written into the world file as
such. They are the knob that decides when the physics simulation starts to
slide, so a result that depends on them has to say so.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from xml.dom import minidom

# Soil is not rubber on tarmac. No published tyre-soil Coulomb coefficient was
# found for an agricultural tyre on tilled ground, and the value governs when
# the physics simulation begins to slide, so it is swept rather than trusted.
DEFAULT_MU = 0.75
DEFAULT_MU2 = 0.65

# Gazebo's default step is 1 ms. The kinematic model runs at 10 to 20 ms with
# RK4; the physics needs a smaller step because contact is stiff.
DEFAULT_STEP = 0.001


@dataclass(frozen=True)
class WorldParams:
    """Everything about the ground that the comparison can vary."""

    slope_deg: float = 0.0
    slope_sign: float = 1.0
    mu: float = DEFAULT_MU
    mu2: float = DEFAULT_MU2
    step: float = DEFAULT_STEP
    size: float = 600.0
    gravity: float = 9.80665

    def __post_init__(self) -> None:
        if not (0.0 <= self.slope_deg <= 30.0):
            raise ValueError("slope must be between 0 and 30 degrees")
        if self.slope_sign not in (-1.0, 1.0):
            raise ValueError("slope sign must be -1 or +1")
        if self.mu <= 0 or self.mu2 <= 0:
            raise ValueError("friction coefficients must be positive")
        if not (1e-5 <= self.step <= 0.01):
            raise ValueError("physics step must be between 10 us and 10 ms")
        if self.size <= 0:
            raise ValueError("world must have a positive size")

    @property
    def roll(self) -> float:
        """Roll of the ground plane, radians. See the module docstring."""
        return -math.radians(self.slope_deg) * self.slope_sign

    def assumptions(self) -> dict[str, str]:
        return {
            "mu": (
                f"{self.mu} static friction, tyre on soil. No published "
                "Coulomb coefficient for an agricultural tyre on tilled ground "
                "was found. This value decides when the physics simulation "
                "begins to slide, so Stage 7 sweeps it and no conclusion may "
                "rest on the default."
            ),
            "mu2": (
                f"{self.mu2} lateral friction, taken below the longitudinal "
                "value because a lugged tyre grips better along its direction "
                "of travel than across it. The ratio is an assumption."
            ),
            "step": (
                f"{self.step} s physics step. Not a property of any machine; "
                "chosen small enough that contact is stable."
            ),
        }


def _pretty(root: ET.Element) -> str:
    raw = ET.tostring(root, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ")


def build_world(params: WorldParams, name: str = "aggsim_field") -> str:
    """SDF for a tilted, finite field with configurable friction."""
    sdf = ET.Element("sdf", version="1.9")
    world = ET.SubElement(sdf, "world", name=name)

    physics = ET.SubElement(world, "physics", name="default", type="ode")
    ET.SubElement(physics, "max_step_size").text = f"{params.step}"
    ET.SubElement(physics, "real_time_factor").text = "0"  # as fast as it can

    for plugin, fname in (
        ("gz::sim::systems::Physics", "gz-sim-physics-system"),
        ("gz::sim::systems::UserCommands", "gz-sim-user-commands-system"),
        ("gz::sim::systems::SceneBroadcaster", "gz-sim-scene-broadcaster-system"),
        ("gz::sim::systems::Contact", "gz-sim-contact-system"),
    ):
        ET.SubElement(world, "plugin", filename=fname, name=plugin)

    ET.SubElement(world, "gravity").text = f"0 0 -{params.gravity}"

    light = ET.SubElement(world, "light", type="directional", name="sun")
    ET.SubElement(light, "cast_shadows").text = "true"
    ET.SubElement(light, "pose").text = "0 0 100 0 0 0"
    ET.SubElement(light, "diffuse").text = "0.9 0.9 0.9 1"
    ET.SubElement(light, "specular").text = "0.2 0.2 0.2 1"
    ET.SubElement(light, "direction").text = "-0.4 0.46 -0.79"

    ground = ET.SubElement(world, "model", name="ground")
    ET.SubElement(ground, "static").text = "true"
    # Rolled about the travel axis. The whole plane tilts, so the slope is
    # uniform, which is the case the kinematic model represents exactly.
    ET.SubElement(ground, "pose").text = f"0 0 0 {params.roll:.6f} 0 0"
    link = ET.SubElement(ground, "link", name="surface")

    for tag in ("collision", "visual"):
        node = ET.SubElement(link, tag, name=tag)
        geometry = ET.SubElement(node, "geometry")
        plane = ET.SubElement(geometry, "plane")
        ET.SubElement(plane, "normal").text = "0 0 1"
        ET.SubElement(plane, "size").text = f"{params.size} {params.size}"
        if tag == "collision":
            surface = ET.SubElement(node, "surface")
            friction = ET.SubElement(surface, "friction")
            ode = ET.SubElement(friction, "ode")
            ET.SubElement(ode, "mu").text = f"{params.mu}"
            ET.SubElement(ode, "mu2").text = f"{params.mu2}"
        else:
            material = ET.SubElement(node, "material")
            ET.SubElement(material, "ambient").text = "0.45 0.40 0.32 1"
            ET.SubElement(material, "diffuse").text = "0.62 0.56 0.44 1"

    header = (
        "<!--\n"
        "  Generated by aggsim.ros2.world. Do not edit by hand.\n\n"
        f"  side slope       {params.slope_deg} deg, sign {params.slope_sign:+.0f}\n"
        f"  ground roll      {params.roll:.6f} rad about the travel axis\n"
        "  ASSUMED VALUES, none of them a machine specification:\n"
        + "".join(f"    {k}: {v}\n" for k, v in params.assumptions().items())
        + "-->\n"
    )
    body = _pretty(sdf)
    first, rest = body.split("\n", 1)
    return f"{first}\n{header}{rest}"


def write_world(path: Path, params: WorldParams) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_world(params), encoding="utf-8")
    return path
