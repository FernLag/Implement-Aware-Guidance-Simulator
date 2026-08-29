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
gz sim -s -r -v 2 "$CASE_DIR/world.sdf" &
GZ_PID=$!
sleep 5

echo "== spawning the machine =="
# Dropped just clear of the ground so the contact solver settles it rather
# than starting it interpenetrating, and offset from the line so there is an
# acquisition transient to compare.
ros2 run ros_gz_sim create \
  -world aggsim_field \
  -file "$CASE_DIR/robot.urdf" \
  -name tractor \
  -x 0 -y "$OFFSET" -z 0.6

sleep 3

echo "== bridging topics =="
ros2 run ros_gz_bridge parameter_bridge \
  /cmd_vel@geometry_msgs/msg/Twist@gz.msgs.Twist \
  /odom@nav_msgs/msg/Odometry@gz.msgs.Odometry \
  /world/aggsim_field/model/tractor/joint_state@sensor_msgs/msg/JointState@gz.msgs.Model \
  --ros-args -r /world/aggsim_field/model/tractor/joint_state:=/joint_states &
BRIDGE_PID=$!
sleep 3

echo "== running the controller =="
python3 /work/scripts/stage7_gazebo_run.py \
  --out "$CASE_DIR/gazebo.json" \
  --tractor "$TRACTOR" --implement "$IMPLEMENT" \
  --speed "$SPEED" --seconds "$SECONDS_RUN" --offset "$OFFSET"

echo "== done: $CASE_DIR/gazebo.json =="
