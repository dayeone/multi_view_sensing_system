#!/usr/bin/env python3
"""
calib_capture.py - 체커보드 캘리브레이션 이미지 촬영기 (intrinsic용)

[하는 일]
  한 카메라를 '고정 초점'으로 켜고, 체커보드를 여러 위치·각도로 옮기며
  '전체 보드가 화면에 다 보일 때만' 사진을 저장한다.
  초점값은 config/camera_focus.yaml 에서 카메라별로 읽어 적용한다.

[준비]
  - config/camera_focus.yaml 에 해당 카메라 초점값이 있어야 함
  - 체커보드(내부 코너 7x10) 준비

[사용법]
  python3 quick_capture/calib_capture.py --device /dev/cam0

[조작 (영상 창에서)]
  c : 현재 화면 저장 (보드 전체가 검출됐을 때만)
  q : 종료
"""
import cv2
import os
import argparse
import yaml
from datetime import datetime

CHECKERBOARD = (7, 10)  # 내부 코너 개수 (calib_calc.py와 동일해야 함)


def load_focus(config_path, cam_name):
    """YAML에서 이 카메라의 초점값을 읽는다. 없으면 None."""
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return int(cfg[cam_name]) if cam_name in cfg else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="/dev/cam0", help="카메라 장치 (기본 /dev/cam0)")
    parser.add_argument("--config", default="config/camera_focus.yaml", help="초점값 YAML 경로")
    parser.add_argument("--outdir", default=None, help="저장 폴더 (기본: calib_data/<카메라명>)")
    args = parser.parse_args()

    cam_name = os.path.basename(args.device)             # /dev/cam0 -> cam0
    if args.outdir is None:
        args.outdir = os.path.join("calib_data", cam_name)
    os.makedirs(args.outdir, exist_ok=True)

    focus = load_focus(args.config, cam_name)
    if focus is None:
        print(f"[ERROR] {args.config} 에 '{cam_name}' 초점값이 없습니다.")
        return

    cap = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"[ERROR] {args.device} 열기 실패")
        return
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    # 오토포커스 OFF + 이 카메라 고정 초점값 적용 (intrinsic 안정화)
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    cap.set(cv2.CAP_PROP_FOCUS, focus)
    print(f"{cam_name}: 초점 {focus} 적용 → 저장 폴더 {args.outdir}")

    # 기존 사진(예전 오토포커스 ON 촬영분)이 섞이면 안 되므로 경고
    existing = len([n for n in os.listdir(args.outdir) if n.endswith('.jpg')])
    if existing:
        print(f"[주의] 폴더에 기존 사진 {existing}장이 있습니다. 예전(오토포커스 ON) 사진이면 지우고 시작하세요.")

    print("조작: c=저장(보드 전체 검출 시) / q=종료")
    saved = existing
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        # 빠른 검출: 0.5배 축소 영상에서 보드가 다 보이는지 확인(피드백용)
        small = cv2.resize(frame, None, fx=0.5, fy=0.5)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(
            gray, CHECKERBOARD,
            flags=cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_FAST_CHECK)

        view = frame.copy()
        if found:
            cv2.drawChessboardCorners(view, CHECKERBOARD, corners * 2, found)
            msg, color = "OK - press c to save", (0, 255, 0)
        else:
            msg, color = "board not fully visible", (0, 0, 255)
        # 화면 글자는 영문(OpenCV가 한글을 못 그림)
        cv2.putText(view, f"{msg}   saved={saved}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
        cv2.imshow(f"calib capture [{cam_name}]", view)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('c') and found:
            ts = datetime.now().strftime("%H%M%S_%f")[:-3]
            path = os.path.join(args.outdir, f"calib_{saved:03d}_{ts}.jpg")
            cv2.imwrite(path, frame)   # 글자/코너 안 그린 '원본'을 저장
            saved += 1
            print(f"  저장 {saved}장: {path}")

    cap.release()
    cv2.destroyAllWindows()
    print(f"종료. 총 {saved}장 저장됨 ({args.outdir})")


if __name__ == "__main__":
    main()
