#!/usr/bin/env python3
"""
preview.py - 4채널 카메라 실시간 미리보기 (저장 없음)

[이 코드가 하는 일]
  /dev/cam1~4 네 대를 동시에 켜서, 한 창에 2x2 격자로 실시간 화면만 보여준다.
  사진을 저장하지도, gap을 재지도 않는다. "카메라가 지금 뭘 잡고 있는지"만
  눈으로 빠르게 확인하는 용도다. (녹화·캘리브레이션 전에 상태 점검용)

[화면 배치 - 물리 위치와 동일하게]
  실제 리그 배치(cam1=좌하, cam2=좌상, cam3=우하, cam4=우상)에 맞춰
  화면에도 같은 자리에 놓는다. 그래서 화면 왼쪽위 칸이 실제 왼쪽위(cam2)다.
      ┌────────────┬────────────┐
      │ cam2 (LT)  │ cam4 (RT)  │   ← 위쪽 두 대
      ├────────────┼────────────┤
      │ cam1 (LB)  │ cam3 (RB)  │   ← 아래쪽 두 대
      └────────────┴────────────┘

[초점]
  녹화·캘리브레이션과 같은 고정 초점을 config/camera_focus.yaml 에서 읽어
  적용한다. (미리보기 화면이 실제 촬영과 같은 초점으로 보이도록)

[사용법]
  python3 quick_capture/preview.py

[조작]
  q : 종료
"""
import cv2
import os
import yaml
import numpy as np

# 카메라 장치. 화면 격자에 놓을 위치(행, 열)도 함께 지정한다.
#   (row, col): 0행=위, 1행=아래 / 0열=왼쪽, 1열=오른쪽
CAMERA_LAYOUT = {
    "cam2": (0, 0),  # 좌상(LT)
    "cam4": (0, 1),  # 우상(RT)
    "cam1": (1, 0),  # 좌하(LB)
    "cam3": (1, 1),  # 우하(RB)
}
FOCUS_CONFIG = os.path.expanduser("~/pest_control_ws/config/camera_focus.yaml")

RESOLUTION = (1280, 720)   # 카메라 캡처 해상도
CELL_W, CELL_H = 640, 360  # 격자 한 칸 표시 크기 (전체 창은 1280x720)


def load_focus_map(config_path, names):
    """camera_focus.yaml 에서 카메라별 고정 초점값을 읽어 dict로 돌려준다.
    파일/값이 없으면 그 카메라는 None(오토포커스만 끔)으로 둔다.
    """
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"[주의] 초점 설정 파일이 없습니다: {config_path} (오토포커스 OFF만 적용)")
        cfg = {}
    return {name: (int(cfg[name]) if name in cfg else None) for name in names}


def open_camera(device_path, focus):
    """카메라 한 대를 열고 해상도·코덱·초점을 설정해 돌려준다. 실패 시 None."""
    cap = cv2.VideoCapture(device_path, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUTION[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUTION[1])
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 최신 프레임만 (지연 누적 방지)
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    if focus is not None:
        cap.set(cv2.CAP_PROP_FOCUS, focus)
    return cap


def make_blank(text):
    """카메라가 안 열렸을 때 격자 칸을 채울 '검은 화면 + 안내문'을 만든다."""
    tile = np.zeros((CELL_H, CELL_W, 3), dtype="uint8")
    cv2.putText(tile, text, (20, CELL_H // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return tile


def main():
    names = list(CAMERA_LAYOUT.keys())
    focus_map = load_focus_map(FOCUS_CONFIG, names)

    # 카메라 열기 (실패해도 나머지는 계속 보여준다)
    caps = {}
    for name in names:
        device = f"/dev/{name}"
        cap = open_camera(device, focus_map[name])
        if cap is None:
            print(f"[ERROR] {device} 열기 실패 (해당 칸은 검은 화면으로 표시)")
        else:
            print(f"[OK] {name}({device}) 열림, focus={focus_map[name]}")
        caps[name] = cap

    print("조작: q=종료")

    win = "preview [cam1~4]"
    # 창을 마우스로 자유롭게 크기 조절할 수 있게 한다.
    #   WINDOW_NORMAL  : 이미지 크기에 고정되지 않고 사용자가 리사이즈 가능
    #   WINDOW_KEEPRATIO: 리사이즈할 때 가로세로 비율을 유지(찌그러짐 방지)
    cv2.namedWindow(win, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    cv2.resizeWindow(win, CELL_W * 2, CELL_H * 2)  # 초기 크기 960x540
    try:
        while True:
            # 전체 격자(960x540)를 만들 빈 캔버스
            grid = np.zeros((CELL_H * 2, CELL_W * 2, 3), dtype="uint8")

            for name in names:
                cap = caps[name]
                # 프레임을 읽는다. 실패하거나 안 열린 카메라는 안내 화면으로 대체.
                if cap is not None:
                    ret, frame = cap.read()
                    tile = cv2.resize(frame, (CELL_W, CELL_H)) if ret \
                        else make_blank(f"{name}: no frame")
                else:
                    tile = make_blank(f"{name}: not opened")

                # 각 칸 좌상단에 카메라 이름 표시
                cv2.putText(tile, name, (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

                # 지정된 (행, 열) 위치에 칸을 붙인다
                r, c = CAMERA_LAYOUT[name]
                grid[r * CELL_H:(r + 1) * CELL_H, c * CELL_W:(c + 1) * CELL_W] = tile

            cv2.imshow(win, grid)
            if (cv2.waitKey(1) & 0xFF) == ord('q'):
                break
    finally:
        # 어떤 경우에도 카메라/창을 정리한다
        for cap in caps.values():
            if cap is not None:
                cap.release()
        cv2.destroyAllWindows()
        print("종료")


if __name__ == "__main__":
    main()
