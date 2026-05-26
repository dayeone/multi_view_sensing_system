#!/usr/bin/env python3
"""
recorder.py - 4채널 BRIO 웹캠 캡처 + 토글 + 디스크 저장

사용법:
  python3 recorder.py              # 기본 2Hz
  python3 recorder.py --hz 1       # 1Hz로 변경
  python3 recorder.py --hz 0.5     # 2초당 1장

명령어 (실행 중):
  s : 캡처 시작 (새 세션 폴더 생성)
  t : 캡처 중지
  q : 프로그램 종료
"""
import cv2
import os
import time
import threading
import argparse
from datetime import datetime

# ===== 설정 =====
CAMERA_DEVICES = [0, 4, 8, 12]
DATA_DIR = "/home/jay/pest_control_ws/quick_capture_data"
RESOLUTION = (1280, 720)
JPEG_QUALITY = 85

# ===== 전역 상태 =====
recording = False
session_dir = None
stop_event = threading.Event()
state_lock = threading.Lock()
saved_counts = {idx: 0 for idx in CAMERA_DEVICES}
save_interval = 0.5  # main에서 인자에 따라 갱신


def open_camera(device_idx):
    cap = cv2.VideoCapture(device_idx, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUTION[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUTION[1])
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def camera_worker(device_idx):
    cap = open_camera(device_idx)
    if cap is None:
        print(f"[ERROR] /dev/video{device_idx} 열기 실패")
        return
    print(f"[OK] /dev/video{device_idx} 열림")

    next_save_time = time.monotonic()

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.005)
            continue

        now = time.monotonic()
        with state_lock:
            cur_recording = recording
            cur_session = session_dir

        if cur_recording and cur_session and now >= next_save_time:
            now_dt = datetime.now()
            ts = now_dt.strftime("%Y%m%d_%H%M%S_") + f"{now_dt.microsecond // 1000:03d}"
            with state_lock:
                seq = saved_counts[device_idx]
                saved_counts[device_idx] += 1
            cam_dir = os.path.join(cur_session, f"cam{device_idx}")
            filepath = os.path.join(cam_dir, f"{seq:06d}_{ts}.jpg")
            try:
                cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            except Exception as e:
                print(f"[ERROR cam{device_idx}] 저장 실패: {e}")
            next_save_time = now + save_interval

    cap.release()
    print(f"[CLOSED] /dev/video{device_idx}")


def main():
    global recording, session_dir, save_interval

    parser = argparse.ArgumentParser()
    parser.add_argument("--hz", type=float, default=2.0,
                        help="캡처 주기 Hz (기본 2.0)")
    args = parser.parse_args()

    if args.hz <= 0:
        print("[ERROR] --hz 값은 0보다 커야 합니다.")
        return
    save_interval = 1.0 / args.hz

    print("=" * 50)
    print("Quick Capture - 4채널 캡처")
    print(f"디바이스: {CAMERA_DEVICES}")
    print(f"해상도: {RESOLUTION[0]}x{RESOLUTION[1]} MJPG")
    print(f"저장 주기: {args.hz} Hz  (간격 {save_interval:.2f}초)")
    print(f"저장 위치: {DATA_DIR}")
    print("=" * 50)
    print("명령어: s=시작 / t=중지 / q=종료")
    print()

    threads = []
    for idx in CAMERA_DEVICES:
        t = threading.Thread(target=camera_worker, args=(idx,), daemon=True)
        t.start()
        threads.append(t)

    time.sleep(2)
    print("준비 완료. 명령 입력:\n")

    try:
        while True:
            cmd = input("> ").strip().lower()

            if cmd == 's':
                with state_lock:
                    if recording:
                        print("이미 캡처 중입니다.")
                        continue
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    new_session = os.path.join(DATA_DIR, f"session_{ts}")
                    for idx in CAMERA_DEVICES:
                        os.makedirs(os.path.join(new_session, f"cam{idx}"), exist_ok=True)
                        saved_counts[idx] = 0
                    session_dir = new_session
                    recording = True
                print(f"[캡처 시작] {new_session}")

            elif cmd == 't':
                with state_lock:
                    if not recording:
                        print("캡처 중이 아닙니다.")
                        continue
                    recording = False
                    counts = dict(saved_counts)
                    cur = session_dir
                    session_dir = None
                print(f"[캡처 중지] {cur}")
                print(f"  저장된 프레임 수: {counts}")

            elif cmd == 'q':
                with state_lock:
                    recording = False
                    session_dir = None
                break

            elif cmd == '':
                continue

            else:
                print("명령어: s=시작 / t=중지 / q=종료")

    except (EOFError, KeyboardInterrupt):
        print("\n[중단]")

    print("종료 중...")
    stop_event.set()
    for t in threads:
        t.join(timeout=3)
    print("프로그램 종료")


if __name__ == "__main__":
    main()