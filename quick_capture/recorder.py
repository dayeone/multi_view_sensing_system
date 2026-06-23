#!/usr/bin/env python3
"""
recorder.py - 4채널 BRIO 웹캠 캡처 + 시간 정합(matching) + 디스크 저장

[이 코드가 하는 일]
  카메라 4대(/dev/video0,4,8,12)를 동시에 켜고, 일정 주기마다
  "가장 비슷한 시각에 찍힌 4장"을 한 묶음(set)으로 저장한다.
  동시에 그 4장이 실제로 얼마나 시간 차이가 나는지(sync gap)를
  측정해 sync_log.csv 에 기록한다. (시간 정합 + 검증)

[설계 핵심 - 왜 이렇게 바꿨나]
  기존에는 카메라 4대가 "각자 자기 시계로" 따로 저장해서,
  같은 시간 녹화해도 저장 장수가 90/89 처럼 어긋났다.
  (감독 없이 4명이 각자 횟수를 셌기 때문)

  이번 방식은 역할을 둘로 나눈다.
    - 카메라 워커(producer): 계속 찍기만 하고, "방금 찍은 한 장 + 찍은 시각"을
      각자의 칸(latest_frames)에 덮어쓴다. 저장은 하지 않는다.
    - 매처(consumer): "고르는 담당" 한 명이 일정 주기마다 한 번씩,
      4개 칸을 동시에 집어 4장을 같은 묶음 번호로 저장한다.
  저장이 '매처의 시계 하나'로만 일어나므로, 카메라별 저장 장수는
  항상 똑같다(묶음마다 정확히 4장). 장수 불일치가 구조적으로 사라진다.

[보강 - 묵은 사진 끼임 검증]
  녹화 중 카메라 한 대가 잠깐 새 프레임을 못 올리면, 그 칸에는
  직전(오래된) 사진이 남아 있어 묶음에 섞일 수 있다. 장수는 맞지만
  내용이 묵은 경우다. 이를 잡기 위해 각 프레임의 '나이(age, 집은 순간
  기준 몇 ms 전에 찍혔는지)'를 함께 기록하고, 임계값을 넘으면 경고 표시한다.

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
import csv
import time
import threading
import argparse
from datetime import datetime

# ===== 설정 =====
CAMERA_DEVICES = [0, 4, 8, 12]
DATA_DIR = "/home/jay/pest_control_ws/quick_capture_data"
RESOLUTION = (1280, 720)
JPEG_QUALITY = 85

# 카메라에 '요청'할 프레임레이트(fps). 카메라가 지원해도 실제로 들어오는지는
# 별도로 측정해야 한다(아래 camera_worker의 실효 fps 출력 참고).
# 이 값은 gap의 '천장'만 낮출 뿐, gap 자체가 줄어드는지는 sync_log.csv로 검증한다.
TARGET_FPS = 60

# camera_worker가 시작 직후 이 시간(초) 동안 들어온 프레임 수로 실효 fps를 1회 계산한다.
FPS_MEASURE_WINDOW_S = 3.0

# 프레임 '나이'가 이 값을 넘으면 묵은 사진으로 보고 경고한다(초).
# 60FPS에서 정상 프레임은 약 16.7ms 이내이므로, 0.1초(약 6프레임)를
# 넘으면 해당 카메라가 잠깐 멈춘 것으로 간주한다.
STALE_AGE_S = 0.1

# ===== 전역 상태 =====
recording = False
session_dir = None
stop_event = threading.Event()

# 녹화/세션/통계 등 제어 상태 보호용 락
state_lock = threading.Lock()

# 카메라별 "최신 프레임 칸". 값은 (mono_ts, wall_dt, frame) 또는 None.
#   mono_ts : time.monotonic() 기준 캡처 시각 (gap/age 계산용, 단조 증가)
#   wall_dt : datetime.now()  기준 캡처 시각 (파일명·로그 표기용)
#   frame   : 캡처된 이미지(numpy 배열)
latest_frames = {idx: None for idx in CAMERA_DEVICES}
frames_lock = threading.Lock()

# 묶음(set) 공유 카운터 - 매처만 증가시킨다. 4대가 항상 같은 번호를 공유.
set_count = 0

# 세션 단위 검증 통계 (state_lock 하에서 갱신)
gap_samples = []      # 묶음별 gap(ms) 목록
stale_set_count = 0   # 묵은 사진이 섞인 묶음 수

save_interval = 0.5   # main에서 --hz 인자에 따라 갱신


def open_camera(device_idx):
    cap = cv2.VideoCapture(device_idx, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUTION[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUTION[1])
    # fps를 명시적으로 요청한다. 미지정 시 드라이버 기본값(보통 30)으로 잡혀
    # gap의 천장이 높아진다. 단, 요청일 뿐 보장은 아니므로 실효 fps를 따로 측정한다.
    cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def camera_worker(device_idx):
    """카메라 워커(producer): 계속 찍어서 최신 프레임 칸만 갱신한다.

    여기서는 디스크 저장을 하지 않는다. 저장 여부/시점 판단은 전적으로
    매처(matcher_worker)가 담당한다. 이렇게 역할을 분리해야
    '4대가 항상 같은 묶음에 한 장씩'이 보장된다.
    """
    cap = open_camera(device_idx)
    if cap is None:
        print(f"[ERROR] /dev/video{device_idx} 열기 실패")
        return
    print(f"[OK] /dev/video{device_idx} 열림")

    # 실효 fps 측정용: 시작 직후 일정 시간 동안 들어온 프레임 수를 센다.
    # fps 설정값(요청)이 실제로 반영됐는지 '관문 1'을 확인하기 위함이다.
    fps_t0 = time.monotonic()
    fps_count = 0
    fps_reported = False

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.005)
            continue

        # 실효 fps 1회 출력 (측정 창이 끝나면 한 번만 보고)
        if not fps_reported:
            fps_count += 1
            elapsed = time.monotonic() - fps_t0
            if elapsed >= FPS_MEASURE_WINDOW_S:
                print(f"[fps] cam{device_idx} ≈ {fps_count / elapsed:.1f} "
                      f"(요청 {TARGET_FPS})")
                fps_reported = True

        # 캡처 직후 두 종류의 시각을 함께 기록한다.
        #   - monotonic: gap/age 계산용(되감기지 않는 시계)
        #   - wall(datetime): 파일명·로그 표기용
        mono_ts = time.monotonic()
        wall_dt = datetime.now()

        # 최신 프레임 칸을 덮어쓴다. cap.read()는 매번 새 배열을 반환하므로
        # 참조만 갱신하면 되고, 기존 묶음이 잡고 있는 프레임을 훼손하지 않는다.
        with frames_lock:
            latest_frames[device_idx] = (mono_ts, wall_dt, frame)

    cap.release()
    print(f"[CLOSED] /dev/video{device_idx}")


def matcher_worker():
    """매처(consumer): 녹화 중일 때 save_interval 주기로 한 번씩,
    4개 칸을 동시에 집어 한 묶음으로 저장하고 sync gap을 측정·기록한다.
    """
    global set_count

    prev_recording = False
    next_tick = time.monotonic()
    csv_path = None

    while not stop_event.is_set():
        now = time.monotonic()

        with state_lock:
            cur_recording = recording
            cur_session = session_dir

        # 녹화가 막 시작된 순간: 스케줄과 묶음 번호를 초기화한다.
        if cur_recording and not prev_recording:
            next_tick = now
            with state_lock:
                set_count = 0
            csv_path = os.path.join(cur_session, "sync_log.csv")
        prev_recording = cur_recording

        # 녹화 중이 아니거나 아직 다음 tick 시각이 아니면 잠깐 쉰다.
        if not cur_recording or now < next_tick:
            time.sleep(0.002)
            continue

        # ----- 1) 4개 칸을 '동시에' 스냅샷 -----
        with frames_lock:
            snapshot = {idx: latest_frames[idx] for idx in CAMERA_DEVICES}

        # ----- 2) 시작 직후 빈 칸 방지: 4대 모두 첫 프레임이 올라왔을 때만 저장 -----
        if any(snapshot[idx] is None for idx in CAMERA_DEVICES):
            # 아직 준비 안 됨 - 다음 tick으로 미루지 않고 곧 재시도
            time.sleep(0.005)
            continue

        # ----- 3) sync gap 과 프레임 나이(age) 계산 -----
        mono_list = [snapshot[idx][0] for idx in CAMERA_DEVICES]
        gap_ms = (max(mono_list) - min(mono_list)) * 1000.0
        ages_ms = {idx: (now - snapshot[idx][0]) * 1000.0 for idx in CAMERA_DEVICES}
        is_stale = any(age > STALE_AGE_S * 1000.0 for age in ages_ms.values())

        # ----- 4) 같은 묶음 번호로 4장 저장 -----
        with state_lock:
            seq = set_count
            set_count += 1
        for idx in CAMERA_DEVICES:
            _mono, wall_dt, frame = snapshot[idx]
            ts = wall_dt.strftime("%Y%m%d_%H%M%S_") + f"{wall_dt.microsecond // 1000:03d}"
            cam_dir = os.path.join(cur_session, f"cam{idx}")
            filepath = os.path.join(cam_dir, f"set{seq:06d}_cam{idx}_{ts}.jpg")
            try:
                cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            except Exception as e:
                print(f"[ERROR cam{idx}] 저장 실패: {e}")

        # ----- 5) 검증 로그(sync_log.csv) 기록 -----
        if csv_path:
            try:
                with open(csv_path, "a", newline="") as f:
                    writer = csv.writer(f)
                    row = [seq, f"{gap_ms:.2f}"]
                    row += [f"{ages_ms[idx]:.2f}" for idx in CAMERA_DEVICES]
                    row += [1 if is_stale else 0]
                    writer.writerow(row)
            except Exception as e:
                print(f"[ERROR] sync_log 기록 실패: {e}")

        # ----- 6) 세션 통계 누적 -----
        with state_lock:
            gap_samples.append(gap_ms)
            if is_stale:
                global stale_set_count
                stale_set_count += 1

        warn = "  [STALE!]" if is_stale else ""
        print(f"[set {seq:06d}] gap={gap_ms:5.2f}ms{warn}")

        next_tick += save_interval
        # 한참 밀렸으면(예: 디스크 지연) 스케줄을 현재 기준으로 재정렬
        if next_tick < now:
            next_tick = now + save_interval


def main():
    global recording, session_dir, save_interval, gap_samples, stale_set_count

    parser = argparse.ArgumentParser()
    parser.add_argument("--hz", type=float, default=2.0,
                        help="캡처 주기 Hz (기본 2.0)")
    args = parser.parse_args()

    if args.hz <= 0:
        print("[ERROR] --hz 값은 0보다 커야 합니다.")
        return
    save_interval = 1.0 / args.hz

    print("=" * 50)
    print("Quick Capture - 4채널 시간 정합 캡처")
    print(f"디바이스: {CAMERA_DEVICES}")
    print(f"해상도: {RESOLUTION[0]}x{RESOLUTION[1]} MJPG")
    print(f"저장 주기: {args.hz} Hz  (간격 {save_interval:.2f}초)")
    print(f"묵은 사진 임계: {STALE_AGE_S * 1000:.0f}ms")
    print(f"저장 위치: {DATA_DIR}")
    print("=" * 50)
    print("명령어: s=시작 / t=중지 / q=종료")
    print()

    # 카메라 워커 4개 + 매처 1개 시작
    threads = []
    for idx in CAMERA_DEVICES:
        t = threading.Thread(target=camera_worker, args=(idx,), daemon=True)
        t.start()
        threads.append(t)

    matcher = threading.Thread(target=matcher_worker, daemon=True)
    matcher.start()
    threads.append(matcher)

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
                    # 검증 로그 헤더 생성
                    csv_path = os.path.join(new_session, "sync_log.csv")
                    with open(csv_path, "w", newline="") as f:
                        writer = csv.writer(f)
                        header = ["set", "gap_ms"]
                        header += [f"cam{idx}_age_ms" for idx in CAMERA_DEVICES]
                        header += ["stale_warn"]
                        writer.writerow(header)
                    # 세션 통계 초기화
                    gap_samples = []
                    stale_set_count = 0
                    session_dir = new_session
                    recording = True
                print(f"[캡처 시작] {new_session}")

            elif cmd == 't':
                with state_lock:
                    if not recording:
                        print("캡처 중이 아닙니다.")
                        continue
                    recording = False
                    cur = session_dir
                    session_dir = None
                    n = len(gap_samples)
                    avg_gap = sum(gap_samples) / n if n else 0.0
                    max_gap = max(gap_samples) if n else 0.0
                    stale_n = stale_set_count
                print(f"[캡처 중지] {cur}")
                print(f"  저장된 묶음 수: {n} (묶음당 {len(CAMERA_DEVICES)}장 = 총 {n * len(CAMERA_DEVICES)}장)")
                print(f"  sync gap: 평균 {avg_gap:.2f}ms / 최대 {max_gap:.2f}ms")
                print(f"  묵은 사진 섞인 묶음: {stale_n}개")

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
