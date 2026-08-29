"""Stage 7 groundwork: URDF description and ROS 2 node wrappers.

Stage 7 is conditional in this project's brief and is not to be begun until
Stages 0 to 6 produce validated results, nor pursued if the Gazebo environment
becomes a time sink. This package is the half that does not need ROS 2 or
Gazebo installed: a robot description generated from the equipment catalog,
and node wrappers around the existing controllers.

Nothing here imports rclpy at module level, so the package can be built and
tested on a machine with no ROS installation, which is the point: the risky
half stays isolated and can be abandoned without losing this.
"""

from .nodes import ControllerBridge, Ros2NotAvailable, require_rclpy
from .urdf import build_description, write_description

__all__ = [
    "ControllerBridge",
    "Ros2NotAvailable",
    "build_description",
    "require_rclpy",
    "write_description",
]
