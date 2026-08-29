"""Run one configuration in Gazebo and record what the machine actually did.

This runs INSIDE the Stage 7 container, where ROS 2 and Gazebo exist. It is
the physics half of the comparison; the kinematic half runs anywhere.

The controller is not reimplemented here. `ControllerBridge` is the same object
Stages 1 to 6 call, holding the same `pure_pursuit` and `stanley` functions, so
that a difference in the result is a difference in the physics and not a
difference in the control law. That is the whole reason the brief insists the
same code run in both environments, and it is the one thing this script must
not get clever about.

    python3 scripts/stage7_gazebo_run.py --out run.json --speed 3 --seconds 60
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggsim.catalog import load_catalog
from aggsim.geometry.abline import ABLine
from aggsim.ros2.nodes import ControllerBridge, require_rclpy, yaw_from_quaternion


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tractor", default="jd_6145r")
    ap.add_argument("--implement", default="jd_1775nt_16row30")
    ap.add_argument("--controller", default="pure_pursuit")
    ap.add_argument("--speed", type=float, default=3.0)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--offset", type=float, default=1.0,
                    help="starting cross-track offset, metres")
    ap.add_argument("--lookahead-gain", type=float, default=0.5)
    ap.add_argument("--lookahead-min", type=float, default=3.0)
    args = ap.parse_args()

    try:
        rclpy = require_rclpy()
    except Exception as exc:  # noqa: BLE001 - the message is the point
        print(exc)
        return 1

    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from sensor_msgs.msg import JointState

    from aggsim.control import PurePursuitGains

    catalog = load_catalog()
    line = ABLine((0.0, 0.0), (1.0, 0.0))
    bridge = ControllerBridge.from_catalog(
        catalog.tractor(args.tractor), line,
        controller=args.controller,
        pursuit=PurePursuitGains(k=args.lookahead_gain, l_min=args.lookahead_min),
    )

    class Recorder(Node):
        """Drives the machine and writes down where it went."""

        def __init__(self) -> None:
            super().__init__("stage7_recorder")
            from geometry_msgs.msg import Twist
            self.records: list[dict] = []
            self.hitch = 0.0
            self.t0 = None
            self.cmd = self.create_publisher(Twist, "cmd_vel", 10)
            self.create_subscription(Odometry, "odom", self._odom, 50)
            self.create_subscription(JointState, "joint_states", self._joints, 10)
            self.Twist = Twist

        def _joints(self, msg) -> None:
            if "hitch_joint" in msg.name:
                self.hitch = float(msg.position[msg.name.index("hitch_joint")])

        def _odom(self, msg) -> None:
            stamp = msg.header.stamp
            t = stamp.sec + stamp.nanosec * 1e-9
            if self.t0 is None:
                self.t0 = t
            t -= self.t0

            p = msg.pose.pose.position
            q = msg.pose.pose.orientation
            yaw = yaw_from_quaternion(q.x, q.y, q.z, q.w)

            delta = bridge.steer(p.x, p.y, yaw, args.speed)

            twist = self.Twist()
            twist.linear.x = float(args.speed)
            twist.angular.z = float(args.speed / bridge.params.wheelbase
                                    * math.tan(delta))
            self.cmd.publish(twist)

            self.records.append({
                "t": t, "x": float(p.x), "y": float(p.y), "theta": float(yaw),
                "cross_track": float(bridge.cross_track(p.x, p.y)),
                "hitch_angle": float(self.hitch),
                "steer_cmd": float(delta),
            })

            if t >= args.seconds:
                raise SystemExit(0)

    rclpy.init()
    node = Recorder()
    try:
        rclpy.spin(node)
    except SystemExit:
        pass
    finally:
        payload = {
            "source": "gazebo",
            "tractor": args.tractor,
            "implement": args.implement,
            "controller": args.controller,
            "speed": args.speed,
            "offset": args.offset,
            "lookahead_gain": args.lookahead_gain,
            "records": node.records,
        }
        Path(args.out).write_text(json.dumps(payload))
        print(f"wrote {args.out} with {len(node.records)} samples")
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
