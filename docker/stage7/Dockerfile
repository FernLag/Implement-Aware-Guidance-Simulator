# Stage 7: ROS 2 and Gazebo, so the physics comparison is reproducible.
#
# Stages 0 to 6 need none of this. They are NumPy and Matplotlib and run
# anywhere. This image exists only so that the physics half of Stage 7 can be
# run by someone who does not have ROS 2 on their machine, which is most
# people, and so that the result does not depend on which version they happen
# to have if they do.
#
# ROS 2 Jazzy and Gazebo Harmonic are the pairing supported together on Ubuntu
# Noble, and both publish arm64 builds, so this works on Apple silicon as well
# as on x86.
FROM ros:jazzy-ros-base

SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-ros-gz \
      ros-jazzy-ros-gz-bridge \
      ros-jazzy-ros-gz-sim \
      python3-numpy \
      python3-yaml \
    && rm -rf /var/lib/apt/lists/*

# Headless. Nothing here needs a window, and asking for one is the usual way
# a container simulation fails on a machine with no display.
ENV QT_QPA_PLATFORM=offscreen
ENV GZ_SIM_HEADLESS=1
ENV PYTHONUNBUFFERED=1

WORKDIR /work
COPY . /work

ENTRYPOINT ["/work/docker/stage7/entrypoint.sh"]
CMD ["--help"]
