# Base: ROS 2 Humble desktop on Ubuntu 22.04
FROM osrf/ros:humble-desktop

ENV DEBIAN_FRONTEND=noninteractive

# 시스템 패키지
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-colcon-common-extensions \
    v4l-utils \
    git \
    nano \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/pest_control_ws

# 파이썬 의존성 (캐시 효율 위해 소스보다 먼저 복사)
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt || \
    echo "[WARN] 일부 pip 패키지 설치 실패 - 빌드 후 점검 필요"

# 워크스페이스 소스 복사
COPY . /workspace/pest_control_ws

# ROS 의존성 자동 설치
RUN . /opt/ros/humble/setup.sh && \
    rosdep update && \
    rosdep install --from-paths src --ignore-src -r -y

# colcon 빌드
RUN . /opt/ros/humble/setup.sh && \
    colcon build --symlink-install

# 셸 진입 시 자동 source
RUN echo "source /opt/ros/humble/setup.bash" >> /root/.bashrc && \
    echo "source /workspace/pest_control_ws/install/setup.bash" >> /root/.bashrc

CMD ["bash"]