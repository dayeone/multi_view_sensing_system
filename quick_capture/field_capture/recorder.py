#!/usr/bin/env python3
"""
recorder.py - 4채널 BRIO 웹캠 캡처 + 시간 정합(matching) + 디스크 저장

[이 코드가 하는 일]
  카메라 4대(/dev/cam1~4)를 동시에 켜고, 일정 주기마다
  "가장 비슷한 시각에 찍힌 4장"을 한 묶음(set)으로 저장한다.
  동시에 그 4장이 실제로 얼마나 시간 차이가 나는지(sync gap)를
  측정해 sync_log.csv 에 기록한다. (시간 정합 + 검증)

[카메라 지정 방식 - 물리 위치 기준]
  /dev/cam1~4 는 udev 규칙이 카메라 시리얼로 만든 심볼릭 링크다.
  따라서 USB 포트 순서나 재연결과 무관하게 항상 같은 물리 카메라
  (cam1=좌하, cam2=좌상, cam3=우하, cam4=우상)에 매핑된다.
  (예전에는 /dev/video0,4,8,12 처럼 '연결 순서'로 잡아서, 재부팅/재연결
   때 물리 위치와 어긋날 수 있었다. 이제 위치가 고정된다.)

[설계 핵심 - 왜 이렇게 나눴나]
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

[초점]
  오토포커스를 끄고 카메라별 고정 초점을 config/camera_focus.yaml 에서
  읽어 적용한다. 초점이 변하면 intrinsic(초점거리)도 변해 공간 정합
  신뢰도가 떨어지므로, 캘리브레이션·촬영·녹화가 같은 고정 초점을 써야 한다.

[취득 방식 구분 - 플랜 C]
  이 파일은 '시간 주기' 트리거 방식이다. 로봇 속도와 무관하게 일정 시간마다
  찍으므로, 로봇이 느려지면 같은 자리를 중복 촬영하고 빨라지면 구간을 건너뛴다.
  거리 기반(플랜 A)·정지 후 촬영(플랜 B)은 같은 폴더의 별도 파일로 둔다.

사용법:
  python3 quick_capture/field_capture/recorder.py              # 기본 2Hz
  python3 quick_capture/field_capture/recorder.py --hz 1       # 1Hz로 변경
  python3 quick_capture/field_capture/recorder.py --hz 0.5     # 2초당 1장

명령어 (실행 중):
  s : 캡처 시작 (새 세션 폴더 생성)
  t : 캡처 중지
  q : 프로그램 종료
"""
import cv2
import os
import csv
import time
import yaml
import collections
import threading
import argparse
from datetime import datetime

# ===== 설정 =====
# 물리 위치 기준 카메라 이름과 장치 경로(udev 심볼릭 링크).
CAMERA_NAMES = ["cam1", "cam2", "cam3", "cam4"]
DEVICE_PATHS = {name: f"/dev/{name}" for name in CAMERA_NAMES}

# 저장 위치와 초점 설정 파일. '~'(현재 사용자 홈)로 풀어 어느 계정에서도 동작하게 한다.
#   (예전에는 특정 사용자 경로 '/home/jay/...'가 하드코딩돼 다른 PC에서 저장이 안 됐다.)
DATA_DIR = os.path.expanduser("~/pest_control_ws/quick_capture_data")
FOCUS_CONFIG = os.path.expanduser("~/pest_control_ws/config/camera_focus.yaml")

RESOLUTION = (1280, 720)
JPEG_QUALITY = 85

# 카메라에 '요청'할 프레임레이트(fps). 카메라가 지원해도 실제로 들어오는지는
# 별도로 측정해야 한다(아래 camera_worker의 실효 fps 출력 참고).
# 이 값은 gap의 '천장'만 낮출 뿐, gap 자체가 줄어드는지는 sync_log.csv로 검증한다.
TARGET_FPS = 60

# camera_worker가 시작 직후 이 시간(초) 동안 들어온 프레임 수로 실효 fps를 1회 계산한다.
FPS_MEASURE_WINDOW_S = 3.0

# 오토포커스 OFF 여부. 실제 초점값은 camera_focus.yaml 에서 카메라별로 읽는다.
AUTOFOCUS_OFF = True

# 프레임 '나이'가 이 값을 넘으면 묵은 사진으로 보고 경고한다(초).
# 60FPS에서 정상 프레임은 약 16.7ms 이내이므로, 0.1초(약 6프레임)를
# 넘으면 해당 카메라가 잠깐 멈춘 것으로 간주한다.
STALE_AGE_S = 0.1

# 세트별 gap을 매번 출력하면 매처가 stdout을 계속 채워, 같은 터미널에서
# input()으로 받는 s/t/q 명령이 파묻혀 입력이 어긋난다(두 글자로 합쳐지는 등).
# 그래서 이 간격(세트 수)마다 한 번씩만 출력한다. STALE 경고는 항상 출력한다.
# (모든 세트의 gap은 sync_log.csv에 빠짐없이 기록되므로 분석에는 영향 없다.)
PRINT_EVERY_N_SETS = 20

# ===== 전역 상태 =====
recording = False
session_dir = None
stop_event = threading.Event()

# 녹화/세션/통계 등 제어 상태 보호용 락
state_lock = threading.Lock()

# 카메라별 "최근 프레임 버퍼". 키는 카메라 이름(cam1~4), 각 원소는 (mono_ts, wall_dt, frame).
#   mono_ts : time.monotonic() 기준 캡처 시각 (gap/age 계산용, 단조 증가)
#   wall_dt : datetime.now()  기준 캡처 시각 (파일명·로그 표기용)
#   frame   : 캡처된 이미지(numpy 배열)
# 'latest' 모드는 버퍼 맨 끝(최신) 1장만 쓰고, 'nearest' 모드는 버퍼 전체에서
# 촬영시각이 가장 가까운 4장 조합을 골라 gap을 줄인다.
#   BUFFER_SIZE: 정합에 쓸 과거 프레임 수. 메모리 ≈ 720p BGR 2.6MB × 4대 × 이 값.
BUFFER_SIZE = 8
frame_buffers = {name: collections.deque(maxlen=BUFFER_SIZE) for name in CAMERA_NAMES}
frames_lock = threading.Lock()

# 정합 방식: 'latest'(baseline) 또는 'nearest'(최근접 타임스탬프 매칭). main에서 설정.
MATCH_MODE = "latest"

# nearest 모드에서 정합에 쓸 '최근 구간'(초). 이 구간 안의 프레임만 후보로 삼아
# 과거로 너무 멀리 가지 않게 해 age(지연)를 제한한다. main에서 --lookback로 설정.
#   작을수록 age↓(신선) / 정렬 선택지↓(gap 살짝↑), 클수록 그 반대. (age-gap 트레이드오프 손잡이)
LOOKBACK_S = 0.066  # 기본 66ms ≈ 30fps의 2프레임

# 묶음(set) 공유 카운터 - 매처만 증가시킨다. 4대가 항상 같은 번호를 공유.
set_count = 0

# 세션 단위 검증 통계 (state_lock 하에서 갱신)
gap_samples = []      # 묶음별 gap(ms) 목록
stale_set_count = 0   # 묵은 사진이 섞인 묶음 수

save_interval = 0.5   # main에서 --hz 인자에 따라 갱신


def load_focus_map(config_path, names):
    """camera_focus.yaml 에서 카메라별 고정 초점값을 읽어 dict로 돌려준다.

    파일이 없거나 특정 카메라 값이 없으면 그 카메라는 None(→ 오토포커스 OFF만
    적용, 초점값은 카메라 기본)으로 둔다. 캘리브레이션 때와 같은 값을 써야
    intrinsic 이 흔들리지 않으므로, 가능하면 모든 카메라 값이 채워져 있어야 한다.
    """
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"[주의] 초점 설정 파일이 없습니다: {config_path} (오토포커스 OFF만 적용)")
        cfg = {}
    focus = {}
    for name in names:
        focus[name] = int(cfg[name]) if name in cfg else None
        if focus[name] is None:
            print(f"[주의] '{name}' 초점값이 설정에 없습니다. 기본 초점으로 진행합니다.")
    return focus


def open_camera(name, device_path, focus):
    """카메라 한 대를 열고 해상도·코덱·fps·(고정)초점을 설정해 돌려준다.

    실패 시 None 을 돌려준다. focus 가 None 이면 오토포커스만 끄고 초점값은
    건드리지 않는다.
    """
    cap = cv2.VideoCapture(device_path, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUTION[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUTION[1])
    # fps를 명시적으로 요청한다. 미지정 시 드라이버 기본값(보통 30)으로 잡혀
    # gap의 천장이 높아진다. 단, 요청일 뿐 보장은 아니므로 실효 fps를 따로 측정한다.
    cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    # 오토포커스 OFF + 카메라별 고정 초점 (intrinsic 안정화, 공간 정합 신뢰도 확보).
    # 설정 직후 실제 반영값을 읽어 출력해, 백엔드가 값을 무시하지 않았는지 검증한다.
    if AUTOFOCUS_OFF:
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        if focus is not None:
            cap.set(cv2.CAP_PROP_FOCUS, focus)
        print(f"[focus] {name}({device_path}) autofocus={cap.get(cv2.CAP_PROP_AUTOFOCUS)} "
              f"focus={cap.get(cv2.CAP_PROP_FOCUS)} (요청 {focus})")
    return cap


def camera_worker(name, device_path, focus):
    """카메라 워커(producer): 계속 찍어서 최신 프레임 칸만 갱신한다.

    여기서는 디스크 저장을 하지 않는다. 저장 여부/시점 판단은 전적으로
    매처(matcher_worker)가 담당한다. 이렇게 역할을 분리해야
    '4대가 항상 같은 묶음에 한 장씩'이 보장된다.
    """
    cap = open_camera(name, device_path, focus)
    if cap is None:
        print(f"[ERROR] {device_path} 열기 실패")
        return
    print(f"[OK] {name}({device_path}) 열림")

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
                print(f"[fps] {name} ≈ {fps_count / elapsed:.1f} (요청 {TARGET_FPS})")
                fps_reported = True

        # 캡처 직후 두 종류의 시각을 함께 기록한다.
        #   - monotonic: gap/age 계산용(되감기지 않는 시계)
        #   - wall(datetime): 파일명·로그 표기용
        mono_ts = time.monotonic()
        wall_dt = datetime.now()

        # 최신 프레임 칸을 덮어쓴다. cap.read()는 매번 새 배열을 반환하므로
        # 참조만 갱신하면 되고, 기존 묶음이 잡고 있는 프레임을 훼손하지 않는다.
        with frames_lock:
            frame_buffers[name].append((mono_ts, wall_dt, frame))

    cap.release()
    print(f"[CLOSED] {name}({device_path})")


def select_nearest(buffers, lookback_s):
    """각 카메라 버퍼에서 한 장씩 골라, 고른 4장의 '촬영시각 스프레드'
    (가장 늦게 찍힌 시각 - 가장 먼저 찍힌 시각)가 최소가 되는 조합을 찾는다.

    baseline('최신 1장')은 카메라들의 위상차 때문에 최대 한 프레임 주기만큼
    벌어질 수 있다. 여기서는 버퍼에 쌓인 최근 프레임들 중 서로 촬영시각이
    가장 가까운 조합을 골라 그 벌어짐(gap)을 줄인다. (소프트웨어 시간 동기화)

    [v2 - 최근 구간 제한(방식 A)]
      과거로 너무 멀리 거슬러 가면 gap은 줄어도 고른 프레임이 오래돼(age↑) 버린다.
      그래서 '가장 최신 프레임 시각(t_newest)'을 기준으로 최근 lookback_s 안의
      프레임만 후보로 삼는다. 이렇게 하면 age가 대략 lookback_s 이내로 묶인다.
      (단, 어떤 카메라가 그 구간에 프레임이 없으면 그 카메라의 최신 1장은 예외로 포함.)

    반환: (chosen, gap_ms)
      chosen : {카메라이름: (mono_ts, wall_dt, frame)}
      gap_ms : 고른 4장의 촬영시각 스프레드(ms)
    """
    names = list(buffers.keys())

    # 1) 최근 구간 후보만 남긴다: 가장 최신 프레임 시각에서 lookback_s 이내.
    t_newest = max(buffers[name][-1][0] for name in names)
    t_min = t_newest - lookback_s
    windowed = {}
    for name in names:
        recent = [e for e in buffers[name] if e[0] >= t_min]
        # 구간 안에 하나도 없으면(그 카메라가 크게 밀린 경우) 최신 1장은 넣어준다.
        windowed[name] = recent if recent else [buffers[name][-1]]

    # 2) 남은 후보들 중 스프레드 최소 조합 탐색.
    candidate_times = sorted({e[0] for name in names for e in windowed[name]})
    best_chosen = None
    best_spread = None
    for T in candidate_times:
        chosen = {}
        for name in names:
            # 이 카메라의 (구간 내) 프레임 중 기준시각 T에 가장 가까운 것
            chosen[name] = min(windowed[name], key=lambda e: abs(e[0] - T))
        ts = [chosen[name][0] for name in names]
        spread = max(ts) - min(ts)
        if best_spread is None or spread < best_spread:
            best_spread = spread
            best_chosen = chosen
    return best_chosen, best_spread * 1000.0


def matcher_worker():
    """매처(consumer): 녹화 중일 때 save_interval 주기로 한 번씩,
    버퍼에서 4장을 골라(정합) 한 묶음으로 저장하고 sync gap을 측정·기록한다.
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

        # ----- 1) 버퍼 스냅샷 (락 점유를 줄이려 리스트로 복사) -----
        with frames_lock:
            buffers = {name: list(frame_buffers[name]) for name in CAMERA_NAMES}

        # ----- 2) 시작 직후 빈 버퍼 방지: 4대 모두 프레임이 올라왔을 때만 저장 -----
        if any(len(buffers[name]) == 0 for name in CAMERA_NAMES):
            time.sleep(0.005)
            continue

        # ----- 3) 정합: 두 방식(latest/nearest)을 '같은 버퍼'로 모두 계산 -----
        #   통제된 비교를 위해 매 tick마다 두 gap을 함께 구한다. 카메라는 한 번만
        #   캡처하고, 두 방법은 그 동일한 프레임들에 대한 계산일 뿐이라 장치 충돌이
        #   없고, 두 gap의 차이가 순수하게 알고리즘 차이가 된다.
        #   (계산량은 숫자 몇 개 수준이라 성능·gap 측정에 영향 없음.)
        latest_pick = {name: buffers[name][-1] for name in CAMERA_NAMES}   # 최신 1장
        lt = [latest_pick[name][0] for name in CAMERA_NAMES]
        gap_latest = (max(lt) - min(lt)) * 1000.0
        nearest_pick, gap_nearest = select_nearest(buffers, LOOKBACK_S)    # 최근접 매칭

        # 실제 디스크에 저장할 4장은 MATCH_MODE가 정한 방식으로 고른다.
        if MATCH_MODE == "nearest":
            snapshot, gap_ms = nearest_pick, gap_nearest
        else:
            snapshot, gap_ms = latest_pick, gap_latest

        # 프레임 나이(age)와 stale 판정 (실제 저장하는 프레임 기준)
        ages_ms = {name: (now - snapshot[name][0]) * 1000.0 for name in CAMERA_NAMES}
        is_stale = any(age > STALE_AGE_S * 1000.0 for age in ages_ms.values())

        # ----- 4) 같은 묶음 번호로 4장 저장 -----
        with state_lock:
            seq = set_count
            set_count += 1
        for name in CAMERA_NAMES:
            _mono, wall_dt, frame = snapshot[name]
            ts = wall_dt.strftime("%Y%m%d_%H%M%S_") + f"{wall_dt.microsecond // 1000:03d}"
            cam_dir = os.path.join(cur_session, name)
            filepath = os.path.join(cam_dir, f"set{seq:06d}_{name}_{ts}.jpg")
            try:
                cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            except Exception as e:
                print(f"[ERROR {name}] 저장 실패: {e}")

        # ----- 5) 검증 로그(sync_log.csv) 기록 -----
        if csv_path:
            try:
                with open(csv_path, "a", newline="") as f:
                    writer = csv.writer(f)
                    # gap_saved = 실제 저장한 방식의 gap, 그 뒤에 두 방식 gap을 함께 기록
                    row = [seq, f"{gap_ms:.2f}", f"{gap_latest:.2f}", f"{gap_nearest:.2f}"]
                    row += [f"{ages_ms[name]:.2f}" for name in CAMERA_NAMES]
                    row += [MATCH_MODE, 1 if is_stale else 0]
                    writer.writerow(row)
            except Exception as e:
                print(f"[ERROR] sync_log 기록 실패: {e}")

        # ----- 6) 세션 통계 누적 -----
        with state_lock:
            gap_samples.append(gap_ms)
            if is_stale:
                global stale_set_count
                stale_set_count += 1

        # 터미널 명령(s/t/q)이 묻히지 않도록, 매 세트가 아니라 일정 간격으로만
        # 출력한다. STALE은 놓치면 안 되므로 발생 시 항상 출력한다.
        if is_stale or seq % PRINT_EVERY_N_SETS == 0:
            warn = "  [STALE!]" if is_stale else ""
            print(f"[set {seq:06d}] gap={gap_ms:5.2f}ms{warn}")

        next_tick += save_interval
        # 한참 밀렸으면(예: 디스크 지연) 스케줄을 현재 기준으로 재정렬
        if next_tick < now:
            next_tick = now + save_interval


def main():
    global recording, session_dir, save_interval, gap_samples, stale_set_count
    global MATCH_MODE, LOOKBACK_S

    parser = argparse.ArgumentParser()
    parser.add_argument("--hz", type=float, default=2.0,
                        help="캡처 주기 Hz (기본 2.0)")
    parser.add_argument("--config", default=FOCUS_CONFIG,
                        help="카메라별 초점 YAML 경로")
    parser.add_argument("--match", choices=["latest", "nearest"], default="latest",
                        help="정합 방식: latest(baseline, 최신1장) / "
                             "nearest(최근접 타임스탬프 매칭)")
    parser.add_argument("--lookback", type=int, default=66,
                        help="nearest 모드 탐색 최근 구간(ms). 작을수록 age↓/gap↑, "
                             "클수록 반대 (기본 66)")
    args = parser.parse_args()

    MATCH_MODE = args.match
    LOOKBACK_S = args.lookback / 1000.0

    if args.hz <= 0:
        print("[ERROR] --hz 값은 0보다 커야 합니다.")
        return
    save_interval = 1.0 / args.hz

    # 카메라별 고정 초점값을 설정 파일에서 읽는다.
    focus_map = load_focus_map(args.config, CAMERA_NAMES)

    print("=" * 50)
    print("Quick Capture - 4채널 시간 정합 캡처")
    print(f"디바이스: {[DEVICE_PATHS[n] for n in CAMERA_NAMES]}")
    print(f"해상도: {RESOLUTION[0]}x{RESOLUTION[1]} MJPG")
    print(f"저장 주기: {args.hz} Hz  (간격 {save_interval:.2f}초)")
    print(f"정합 방식: {MATCH_MODE}  (latest=최신1장 / nearest=최근접 매칭, 버퍼 {BUFFER_SIZE}장)")
    if MATCH_MODE == "nearest":
        print(f"  탐색 최근 구간(lookback): {args.lookback}ms")
    print(f"묵은 사진 임계: {STALE_AGE_S * 1000:.0f}ms")
    print(f"초점(카메라별): {focus_map}")
    print(f"저장 위치: {DATA_DIR}")
    print("=" * 50)
    print("명령어: s=시작 / t=중지 / q=종료")
    print()

    # 카메라 워커 4개 + 매처 1개 시작
    threads = []
    for name in CAMERA_NAMES:
        t = threading.Thread(
            target=camera_worker,
            args=(name, DEVICE_PATHS[name], focus_map[name]),
            daemon=True)
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
                    for name in CAMERA_NAMES:
                        os.makedirs(os.path.join(new_session, name), exist_ok=True)
                    # 검증 로그 헤더 생성
                    csv_path = os.path.join(new_session, "sync_log.csv")
                    with open(csv_path, "w", newline="") as f:
                        writer = csv.writer(f)
                        header = ["set", "gap_saved_ms", "gap_latest_ms", "gap_nearest_ms"]
                        header += [f"{name}_age_ms" for name in CAMERA_NAMES]
                        header += ["match_mode", "stale_warn"]
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
                print(f"  저장된 묶음 수: {n} (묶음당 {len(CAMERA_NAMES)}장 = 총 {n * len(CAMERA_NAMES)}장)")
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
