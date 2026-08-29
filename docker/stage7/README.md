# Stage 7 container

Stages 0 to 6 need none of this. They are NumPy and Matplotlib and run
anywhere. This image exists so the physics half of Stage 7 can be run without
a local ROS 2 installation.

```bash
docker build -t aggsim-stage7 -f docker/stage7/Dockerfile .

# one case
docker run --rm -v "$PWD/build:/work/build" \
  -e NAME=flat_3ms -e SLOPE=0 -e SPEED=3 -e SECONDS_RUN=60 \
  aggsim-stage7

# the whole sweep, then the comparison
python3 scripts/stage7_compare.py --sweep
```

Each case writes `build/stage7/<name>/gazebo.json` alongside the `world.sdf`
and `robot.urdf` it was actually run with, so a result can always be traced
back to the description that produced it.

`scripts/stage7_compare.py` runs the identical configuration through the
kinematic model and reports the divergence. It does not invent a physics run:
with no `gazebo.json` present it says which cases are missing and stops.
