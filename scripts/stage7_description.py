"""Stage 7: generate robot descriptions from the equipment catalog.

    python3 scripts/stage7_description.py

Writes a URDF per pairing into results/urdf/. Needs neither ROS 2 nor Gazebo,
which is the point: this half of Stage 7 stands on its own if the simulation
environment turns out to be a time sink, as the brief warns it might.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from aggsim.catalog import load_catalog
from aggsim.model import implement_from_catalog
from aggsim.ros2 import write_description

OUT = Path("results/urdf")

PAIRINGS = [
    ("jd_5075e", "landpride_rcr1860"),
    ("jd_6145r", "jd_1590_20ft"),
    ("nh_t7_270", "caseih_tt345_22ft"),
    ("jd_8r_410", "jd_1775nt_16row30"),
    ("mf_8s_265", "kuhn_excelerator_8005_50"),
    ("monarch_mk_v", "laserweeder_g2_200"),
]


def main() -> None:
    catalog = load_catalog()
    OUT.mkdir(parents=True, exist_ok=True)

    print("Stage 7: robot descriptions generated from the catalog\n")
    print(f'{"pairing":52s} {"links":>6} {"joints":>7} {"mass (kg)":>10}  hitch')

    for tractor_id, implement_id in PAIRINGS:
        tractor = catalog.tractor(tractor_id)
        implement = catalog.implement(implement_id)
        geometry = implement_from_catalog(implement)

        path = OUT / f"{tractor_id}__{implement_id}.urdf"
        write_description(path, tractor, implement, geometry)

        root = ET.fromstring(path.read_text())
        mass = sum(float(i.find("mass").get("value")) for i in root.iter("inertial"))
        hitch = root.find("joint[@name='hitch_joint']")
        limit = ("none, mounted" if hitch is None
                 else f"+/-{float(hitch.find('limit').get('upper')):.3f} rad")

        name = f"{tractor.model} + {implement.model}"
        print(f"{name[:52]:52s} {len(root.findall('link')):6d} "
              f"{len(root.findall('joint')):7d} {mass:10.0f}  {limit}")

    print(f"\n  wrote {len(PAIRINGS)} descriptions to {OUT}")
    print("\n  To use them, ROS 2 and Gazebo are needed and neither is installed here:")
    print("    ros2 launch <your bringup> model:=results/urdf/<file>.urdf")
    print("\n  The brief makes Stage 7 conditional and says to abandon it if the")
    print("  environment consumes more than about two weeks. Everything above")
    print("  stands without it.")


if __name__ == "__main__":
    main()
