"""Write the world and the robot description for one Stage 7 configuration.

Both come out of the same catalog the kinematic model uses, so the two
simulations are describing one machine on one hillside. Anything hand-edited
here would quietly become a difference between the simulators that gets
reported as physics.

    python3 scripts/stage7_assets.py --out build/stage7 --slope-deg 8
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aggsim.catalog import load_catalog
from aggsim.model import implement_from_catalog
from aggsim.ros2.urdf import write_description
from aggsim.ros2.world import WorldParams, write_world


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/stage7")
    ap.add_argument("--tractor", default="jd_6145r")
    ap.add_argument("--implement", default="jd_1775nt_16row30")
    ap.add_argument("--slope-deg", type=float, default=0.0)
    ap.add_argument("--slope-sign", type=float, default=1.0)
    ap.add_argument("--mu", type=float, default=0.75)
    ap.add_argument("--mu2", type=float, default=0.65)
    ap.add_argument("--step", type=float, default=0.001)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    catalog = load_catalog()
    tractor = catalog.tractor(args.tractor)
    implement = catalog.implement(args.implement) if args.implement else None
    geometry = implement_from_catalog(implement) if implement else None

    urdf = write_description(out / "robot.urdf", tractor, implement, geometry,
                             gazebo=True, mu=args.mu, mu2=args.mu2)
    params = WorldParams(slope_deg=args.slope_deg, slope_sign=args.slope_sign,
                         mu=args.mu, mu2=args.mu2, step=args.step)
    world = write_world(out / "world.sdf", params)

    manifest = {
        "tractor": tractor.id,
        "implement": None if implement is None else implement.id,
        "slope_deg": args.slope_deg,
        "slope_sign": args.slope_sign,
        "mu": args.mu,
        "mu2": args.mu2,
        "step": args.step,
        "wheelbase_m": tractor.wheelbase.value,
        "implement_mass_kg": None if implement is None else implement.mass.value,
        "world_roll_rad": params.roll,
        "assumptions": params.assumptions(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"wrote {urdf}")
    print(f"wrote {world}")
    print(f"wrote {out / 'manifest.json'}")
    print(f"\n  side slope {args.slope_deg} deg -> ground roll "
          f"{params.roll:.6f} rad")
    print("\nASSUMED VALUES IN THIS WORLD")
    for key, why in params.assumptions().items():
        print(f"  {key}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
