"""ROS 2 wrappers around the controllers, with the logic kept out of ROS.

The brief requires that the same control code runs in both environments. That
is only true if nothing about the controller changes when it moves, so the
work here is deliberately thin: `ControllerBridge` turns a pose and a speed
into a steering command using the identical `pure_pursuit` and `stanley`
functions the Stages 1 to 6 simulations call, and the node is a shell that
carries messages in and out of it.

Two consequences worth stating. The bridge is ordinary Python, so it is fully
tested on a machine with no ROS installation, which is where most of the
behaviour lives. And rclpy is imported lazily inside the functions that need
it, so importing this module on such a machine works and says why it cannot
run rather than failing at import time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..control import PurePursuitGains, StanleyGains, pure_pursuit, stanley
from ..geometry.abline import ABLine
from ..model.state import State
from ..model.vehicle import VehicleParams, from_tractor


class Ros2NotAvailable(RuntimeError):
    """rclpy is not importable in this environment."""


def require_rclpy():
    """Import rclpy, or explain clearly why the node cannot run."""
    try:
        import rclpy  # noqa: F401
        return rclpy
    except ImportError as exc:
        raise Ros2NotAvailable(
            "rclpy is not installed, so the ROS 2 node cannot run here. The "
            "controllers, the robot description and everything Stages 0 to 6 "
            "produce do not need it. Install ROS 2 and source its setup file "
            "to use this node."
        ) from exc


@dataclass
class ControllerBridge:
    """Pose in, steering command out, using the simulation's own controllers.

    Deliberately free of ROS types. Everything that decides what the machine
    does is here and is tested without a ROS installation; the node below only
    moves numbers across a boundary.
    """

    line: ABLine
    params: VehicleParams
    controller: str = "pure_pursuit"
    pursuit: PurePursuitGains = PurePursuitGains(k=0.5, l_min=3.0)
    stanley_gains: StanleyGains = StanleyGains(k_e=2.0)

    def __post_init__(self) -> None:
        if self.controller not in ("pure_pursuit", "stanley"):
            raise ValueError(f"unknown controller {self.controller!r}")

    @classmethod
    def from_catalog(cls, tractor, line: ABLine, **kwargs) -> ControllerBridge:
        return cls(line=line, params=from_tractor(tractor), **kwargs)

    def steer(self, x: float, y: float, yaw: float, speed: float) -> float:
        """Steering angle in radians, positive to the left."""
        state = State(x, y, yaw)
        if self.controller == "pure_pursuit":
            return pure_pursuit(state, self.line, speed, self.pursuit, self.params)
        return stanley(state, self.line, speed, self.stanley_gains, self.params)

    def cross_track(self, x: float, y: float) -> float:
        return self.line.cross_track(x, y)


def yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    """Yaw from an orientation quaternion, which is all a planar model needs."""
    siny = 2.0 * (w * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny, cosy)


def build_node_class():
    """Define the node type, once rclpy is known to be importable.

    Defined inside a function rather than at module scope so that importing
    this module never requires ROS. The class body needs rclpy's base class,
    which does not exist until then.
    """
    require_rclpy()
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from std_msgs.msg import Float64

    class GuidanceNode(Node):
        """Subscribes to odometry, publishes a steering command."""

        def __init__(self, bridge: ControllerBridge, speed: float = 3.0) -> None:
            super().__init__("implement_aware_guidance")
            self.bridge = bridge
            self.speed = speed
            self.create_subscription(Odometry, "odom", self._on_odom, 10)
            self.steer_pub = self.create_publisher(Float64, "steering_angle", 10)
            self.error_pub = self.create_publisher(Float64, "cross_track_error", 10)
            self.cmd_pub = self.create_publisher(Twist, "cmd_vel", 10)

        def _on_odom(self, msg) -> None:
            p = msg.pose.pose.position
            q = msg.pose.pose.orientation
            yaw = yaw_from_quaternion(q.x, q.y, q.z, q.w)

            delta = self.bridge.steer(p.x, p.y, yaw, self.speed)
            self.steer_pub.publish(Float64(data=float(delta)))
            self.error_pub.publish(Float64(data=float(self.bridge.cross_track(p.x, p.y))))

            twist = Twist()
            twist.linear.x = float(self.speed)
            # The bicycle model's yaw rate, so a differential-drive consumer
            # gets the same motion the kinematic simulation would produce.
            twist.angular.z = float(self.speed / self.bridge.params.wheelbase
                                    * math.tan(delta))
            self.cmd_pub.publish(twist)

    return GuidanceNode


def main(argv=None) -> int:
    """Entry point. Fails with an explanation rather than a traceback."""
    from ..catalog import load_catalog

    try:
        rclpy = require_rclpy()
    except Ros2NotAvailable as exc:
        print(exc)
        return 1

    catalog = load_catalog()
    bridge = ControllerBridge.from_catalog(
        catalog.tractor("jd_6145r"), ABLine((0.0, 0.0), (1.0, 0.0))
    )

    rclpy.init(args=argv)
    node = build_node_class()(bridge)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0
