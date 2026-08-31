#!/usr/bin/env bash
# Run one Stage 7 configuration through Gazebo and write the trajectory out.
#
# Everything is torn down on exit, including on failure, because a Gazebo
# server left running holds the transport port and the next case then fails
# for a reason that has nothing to do with the case.
set -euo pipefail

source /opt/ros/jazzy/setup.bash

OUT=${OUT:-/work/build/stage7}
SLOPE=${SLOPE:-0}
SPEED=${SPEED:-3.0}
SECONDS_RUN=${SECONDS_RUN:-60}
OFFSET=${OFFSET:-1.0}
MU=${MU:-0.75}
TRACTOR=${TRACTOR:-jd_6145r}
IMPLEMENT=${IMPLEMENT:-jd_1775nt_16row30}
NAME=${NAME:-case}

if [[ "${1:-}" == "--help" ]]; then
  echo "Stage 7 physics runner."
  echo "  environment: SLOPE SPEED SECONDS_RUN OFFSET MU TRACTOR IMPLEMENT NAME OUT"
  exit 0
fi

mkdir -p "$OUT"
CASE_DIR="$OUT/$NAME"
mkdir -p "$CASE_DIR"

echo "== generating world and description =="
python3 /work/scripts/stage7_assets.py --out "$CASE_DIR" \
  --tractor "$TRACTOR" --implement "$IMPLEMENT" \
  --slope-deg "$SLOPE" --mu "$MU"

cleanup() {
  local status=$?
  [[ -n "${GZ_PID:-}"     ]] && kill "$GZ_PID"     2>/dev/null || true
  [[ -n "${BRIDGE_PID:-}" ]] && kill "$BRIDGE_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  exit $status
}
trap cleanup EXIT INT TERM

echo "== starting gazebo server =="
gz sim -s -r -v 2 "$CASE_DIR/world.sdf" >"$CASE_DIR/gazebo.log" 2>&1 &
GZ_PID=$!

# Wait for the world to answer rather than sleeping a guessed number of
# seconds. A container starts Gazebo at a different speed every time, and a
# fixed sleep either wastes time or spawns into a world that does not exist
# yet, which fails with a message about the service being unavailable and
# looks like a modelling problem.
echo "-- waiting for the world --"
for i in $(seq 1 60); do
  if gz service -l 2>/dev/null | grep -q "/world/aggsim_field/create"; then
    echo "-- world up after ${i}s --"; break
  fi
  if ! kill -0 "$GZ_PID" 2>/dev/null; then
    echo "!! gazebo exited during startup:"; tail -30 "$CASE_DIR/gazebo.log"; exit 1
  fi
  sleep 1
done
if ! gz service -l 2>/dev/null | grep -q "/world/aggsim_field/create"; then
  echo "!! the world never came up:"; tail -30 "$CASE_DIR/gazebo.log"; exit 1
fi

echo "== spawning the machine =="
# Dropped just clear of the ground so the contact solver settles it rather
# than starting it interpenetrating, and offset from the line so there is an
# acquisition transient to compare.
ros2 run ros_gz_sim create \
  -world aggsim_field \
  -file "$CASE_DIR/robot.urdf" \
  -name tractor \
  -x 0 -y "$OFFSET" -z 0.6

echo "== bridging topics =="
ros2 run ros_gz_bridge parameter_bridge \
  /cmd_vel@geometry_msgs/msg/Twist@gz.msgs.Twist \
  /odom@nav_msgs/msg/Odometry@gz.msgs.Odometry \
  /world/aggsim_field/model/tractor/joint_state@sensor_msgs/msg/JointState@gz.msgs.Model \
  --ros-args -r /world/aggsim_field/model/tractor/joint_state:=/joint_states &
BRIDGE_PID=$!

# Odometry has to be arriving before the controller starts, or it publishes
# nothing and records an empty run that looks like a physics result.
echo "-- waiting for odometry --"
for i in $(seq 1 40); do
  if timeout 2 ros2 topic echo /odom --once >/dev/null 2>&1; then
    echo "-- odometry flowing after ${i}s --"; break
  fi
  sleep 1
done

echo "== running the controller =="
python3 /work/scripts/stage7_gazebo_run.py \
  --out "$CASE_DIR/gazebo.json" \
  --tractor "$TRACTOR" --implement "$IMPLEMENT" \
  --speed "$SPEED" --seconds "$SECONDS_RUN" --offset "$OFFSET"

echo "== done: $CASE_DIR/gazebo.json =="
