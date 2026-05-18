#!/bin/bash
# pest_control_ws 컨테이너 실행 스크립트
# - NUC: 4개 카메라 device 자동 감지 후 매핑
# - 데스크톱: 카메라 없으면 device 매핑 생략, 그대로 동작

IMAGE_NAME="multi_view_sensing:dev"
WORKSPACE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# 카메라 디바이스 자동 탐지 (존재 시에만 매핑)
CAMERA_DEVICES=""
for dev in /dev/video0 /dev/video4 /dev/video8 /dev/video12; do
    if [ -e "$dev" ]; then
        CAMERA_DEVICES="$CAMERA_DEVICES --device=$dev"
    fi
done

docker run -it --rm \
    --name pest_control_dev \
    --network host \
    --ipc=host \
    --gpus all \
    $CAMERA_DEVICES \
    -e DISPLAY="$DISPLAY" \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v "$WORKSPACE_DIR":/workspace/pest_control_ws \
    "$IMAGE_NAME" \
    bash