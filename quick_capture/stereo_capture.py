#!/usr/bin/env python3
"""
stereo_capture.py - 면별 2대 동시 촬영기 (extrinsic = 공간 정합용)

[이 스크립트가 하는 일]
  한 '면'을 이루는 두 카메라(예: 좌면 = cam1 + cam2)를 동시에 켜고,
  chArUco 보드를 여러 위치·각도로 옮기며 '두 카메라가 같은 순간의 보드를
  함께 찍은' 이미지 쌍을 저장한다. 이렇게 모은 쌍을 stereo_calib.py가 읽어
  두 카메라 사이의 상대 자세(R: 회전, T: 이동)를 계산한다.

[왜 chArUco인가]
  체커보드는 '보드 전체'가 화면에 다 보여야만 코너를 쓸 수 있다.
  그런데 두 카메라의 '겹치는 시야'는 각 카메라 시야보다 좁아서,
  보드 전체를 양쪽이 동시에 담기가 까다롭다.
  chArUco는 각 코너에 '고유 번호(ID)'가 붙어 있어, 보드가 일부만 보여도
  '양쪽에 공통으로 보인 코너'만 골라 매칭할 수 있다. → 겹침이 좁아도 정합 가능.

[준비물]
  - 인쇄한 chArUco 보드 (아래 BOARD 설정과 반드시 일치해야 함)
  - config/camera_focus.yaml 에 두 카메라의 고정 초점값

[사용법]
  python3 quick_capture/stereo_capture.py --pair left    # 좌면(cam1+cam2)
  python3 quick_capture/stereo_capture.py --pair right   # 우면(cam3+cam4)

[화면 조작]
  c : 현재 좌/우 프레임을 '쌍'으로 저장 (공통 코너가 충분할 때만)
  q : 종료

[역광/어두운 카메라 대응 - 수동 노출]
  위를 바라보는 하단 카메라(cam1, cam3)는 천장 조명 역광 때문에 자동노출이
  보드를 어둡게 깔아버릴 수 있다. 이때 해당 카메라의 노출을 '수동'으로 올린다.
  예) 우면에서 기준(cam3)만 밝게:
      python3 quick_capture/stereo_capture.py --pair right --exp-ref 300
  노출값은 카메라 고유 단위(대략 크면 밝음)라 정답이 없다. 화면을 보며
  보드가 또렷해질 때까지 값을 키워가며 맞춘다(보드는 정지 상태라 노출을
  길게 줘도 흔들리지 않는다). 캘리브레이션 정확도에 밝기 자체는 영향 없다.

[저장 위치]
  stereo_data/<pair>/<카메라명>/pair_XXX.jpg
  (좌/우 같은 인덱스 XXX 로 짝을 맞춰 저장하므로, 나중에 파일명으로 짝을 찾음)
"""
import cv2
import cv2.aruco as aruco
import numpy as np
import os
import argparse
import yaml

# ─────────────────────────────────────────────────────────────────────────────
# chArUco 보드 설정 (인쇄한 실물 보드와 100% 일치해야 함)
#   - 이 값이 실물과 다르면 코너 3D 좌표가 틀어져 계산이 전부 어긋난다.
#   - squaresX/Y 는 '칸(사각형) 개수'이고, 내부 코너 수는 (X-1)*(Y-1) 이다.
#     여기선 (7-1)*(5-1) = 24개가 최대 코너 수.
# ─────────────────────────────────────────────────────────────────────────────
SQUARES_X = 7          # 가로 칸 수
SQUARES_Y = 5          # 세로 칸 수
SQUARE_LEN_MM = 35.0   # 한 칸(검/흰 사각형) 한 변 길이 [mm]
MARKER_LEN_MM = 26.0   # 칸 안 ArUco 마커 한 변 길이 [mm]
# ArUco 딕셔너리: 마커 무늬의 '사전'. 인쇄 때 쓴 것과 같아야 ID가 맞는다.
# 4.5.4(구버전 함수형 API)에서는 Dictionary_get() 으로 가져온다.
ARUCO_DICT = aruco.Dictionary_get(aruco.DICT_5X5_50)
# 위 설정으로 보드 객체를 만든다. 이 객체가 '코너의 3D 좌표(보드 좌표계)'를 안다.
CHARUCO_BOARD = aruco.CharucoBoard_create(
    SQUARES_X, SQUARES_Y, SQUARE_LEN_MM, MARKER_LEN_MM, ARUCO_DICT)

# 카메라 해상도(프로젝트 공통값). intrinsic 촬영 때와 같게 맞춘다.
FRAME_W, FRAME_H = 1280, 720

# 저장을 허용할 '공통 코너 최소 개수'.
#   두 카메라에 함께 잡힌 코너가 이보다 적으면 그 쌍은 계산에 도움이 안 되고,
#   특히 코너가 적으면 자세 추정이 붕괴할 수 있어 저장 자체를 막는다.
#   (stereo_calib.py 의 MIN_COMMON_CORNERS 와 맞춰 둔다.)
MIN_COMMON_CORNERS = 8

# 면(pair) → (기준 카메라, 상대 카메라) 매핑.
#   'ref'(기준)를 첫 번째 카메라로 두면, 계산 결과 R,T 는
#   "기준 카메라 좌표 → 상대 카메라 좌표" 로 가는 변환을 뜻한다.
#   좌면: cam1(LB) 기준 → cam2(LT),  우면: cam3(RB) 기준 → cam4(RT)
PAIRS = {
    "left":  {"ref": ("cam1", "/dev/cam1"), "tgt": ("cam2", "/dev/cam2")},
    "right": {"ref": ("cam3", "/dev/cam3"), "tgt": ("cam4", "/dev/cam4")},
}


def load_focus(config_path, cam_name):
    """camera_focus.yaml 에서 해당 카메라의 고정 초점값을 읽는다.

    초점이 촬영마다 흔들리면 intrinsic/extrinsic 모두 부정확해지므로,
    intrinsic 측정 때 쓴 값과 동일한 고정 초점을 그대로 적용한다.
    값이 없으면 None 을 돌려주고, 호출부에서 경고 후 진행한다.
    """
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return int(cfg[cam_name]) if cam_name in cfg else None


def open_camera(device, focus, exposure=None):
    """카메라 한 대를 열고 해상도·코덱·초점·(선택)노출을 설정해 돌려준다.

    - MJPG 코덱 + 1280x720: 프로젝트 공통 설정(대역폭 대비 화질 균형).
    - 버퍼 크기 1: 오래된(지연된) 프레임이 쌓이지 않게 해 최신 프레임을 읽음.
    - 오토포커스 OFF + 고정 초점: 캘리브레이션 안정성의 핵심.
    - exposure 가 주어지면 자동노출을 끄고 그 값으로 고정한다.
      (역광으로 어두운 카메라를 밝히기 위함. None 이면 기존처럼 자동노출.)
    실패 시 None 을 돌려준다.
    """
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"[ERROR] {device} 열기 실패")
        return None
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    if focus is not None:
        cap.set(cv2.CAP_PROP_FOCUS, focus)
    if exposure is not None:
        # UVC(웹캠) 규약에서 CAP_PROP_AUTO_EXPOSURE 는
        #   1 = 수동(manual), 3 = 자동(aperture priority) 을 의미한다(값이 헷갈리는 지점).
        # 먼저 수동으로 바꾼 뒤 노출값을 설정하는 순서가 안전하다.
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
        cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
    return cap


def detect_charuco(gray):
    """흑백 이미지에서 chArUco 코너와 그 ID를 검출한다.

    2단계로 이뤄진다.
      1) detectMarkers: 먼저 ArUco '마커(작은 정사각 무늬)'들을 찾는다.
      2) interpolateCornersCharuco: 찾은 마커를 근거로 체스판 코너 위치를
         정밀 보간해 얻는다. 각 코너에는 고유 ID가 함께 나온다.
    돌려주는 값:
      charuco_corners: (N,1,2) 코너 픽셀 좌표, charuco_ids: (N,1) 코너 ID.
      아무것도 못 찾으면 (None, None).
    """
    # 마커 검출 파라미터(기본값). 필요 시 임계값 등을 조정할 수 있다.
    params = aruco.DetectorParameters_create()
    marker_corners, marker_ids, _ = aruco.detectMarkers(
        gray, ARUCO_DICT, parameters=params)

    # 마커를 하나도 못 찾으면 코너 보간도 불가능하다.
    if marker_ids is None or len(marker_ids) == 0:
        return None, None

    # 마커 정보를 바탕으로 체스판 코너를 보간한다.
    retval, charuco_corners, charuco_ids = aruco.interpolateCornersCharuco(
        marker_corners, marker_ids, gray, CHARUCO_BOARD)

    # retval 은 보간에 성공한 코너 개수. 0이면 실패로 본다.
    if retval is None or retval == 0 or charuco_corners is None:
        return None, None
    return charuco_corners, charuco_ids


def common_corner_count(ids_a, ids_b):
    """두 카메라에서 검출된 코너 ID 집합의 '공통 개수'를 센다.

    stereoCalibrate 는 '양쪽 카메라가 동시에 본 같은 코너'만 쓸 수 있으므로,
    이 공통 개수가 그 쌍의 실제 유효 표본 수가 된다. (촬영 중 실시간 피드백용)
    """
    if ids_a is None or ids_b is None:
        return 0
    set_a = set(int(x) for x in ids_a.flatten())
    set_b = set(int(x) for x in ids_b.flatten())
    return len(set_a & set_b)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", choices=["left", "right"], required=True,
                        help="촬영할 면: left(cam1+cam2) 또는 right(cam3+cam4)")
    parser.add_argument("--config", default="config/camera_focus.yaml",
                        help="초점값 YAML 경로")
    # 수동 노출값(선택). 미지정이면 자동노출. 어두운 카메라만 골라 밝힐 수 있게
    # 기준(ref)/상대(tgt) 각각 따로 준다. (역광 하단 카메라 대응)
    parser.add_argument("--exp-ref", type=int, default=None,
                        help="기준 카메라 수동 노출값 (미지정=자동노출)")
    parser.add_argument("--exp-tgt", type=int, default=None,
                        help="상대 카메라 수동 노출값 (미지정=자동노출)")
    args = parser.parse_args()

    pair = PAIRS[args.pair]
    (ref_name, ref_dev) = pair["ref"]   # 기준 카메라 (좌/우면의 아래쪽)
    (tgt_name, tgt_dev) = pair["tgt"]   # 상대 카메라 (좌/우면의 위쪽)

    # 두 카메라의 고정 초점값을 읽는다.
    ref_focus = load_focus(args.config, ref_name)
    tgt_focus = load_focus(args.config, tgt_name)
    for nm, fc in ((ref_name, ref_focus), (tgt_name, tgt_focus)):
        if fc is None:
            print(f"[주의] {args.config} 에 '{nm}' 초점값이 없습니다. 오토포커스 OFF만 적용됩니다.")

    # 저장 폴더 준비: stereo_data/<pair>/<카메라명>/
    out_ref = os.path.join("stereo_data", args.pair, ref_name)
    out_tgt = os.path.join("stereo_data", args.pair, tgt_name)
    os.makedirs(out_ref, exist_ok=True)
    os.makedirs(out_tgt, exist_ok=True)

    # 두 카메라를 연다. 하나라도 실패하면 정리 후 종료.
    cap_ref = open_camera(ref_dev, ref_focus, args.exp_ref)
    cap_tgt = open_camera(tgt_dev, tgt_focus, args.exp_tgt)
    if cap_ref is None or cap_tgt is None:
        if cap_ref:
            cap_ref.release()
        if cap_tgt:
            cap_tgt.release()
        print("[ERROR] 카메라 열기 실패로 종료합니다. 다른 노드가 카메라를 점유 중인지 확인하세요.")
        return

    exp_ref_str = args.exp_ref if args.exp_ref is not None else "auto"
    exp_tgt_str = args.exp_tgt if args.exp_tgt is not None else "auto"
    print(f"[{args.pair}] 기준={ref_name}({ref_dev}, focus={ref_focus}, exp={exp_ref_str}) / "
          f"상대={tgt_name}({tgt_dev}, focus={tgt_focus}, exp={exp_tgt_str})")
    print(f"저장: {out_ref} , {out_tgt}")
    print(f"조작: c=쌍 저장(공통 코너 {MIN_COMMON_CORNERS}개 이상) / q=종료")

    # 이미 저장된 장수를 세어 이어서 인덱스를 매긴다(중복 방지).
    saved = len([n for n in os.listdir(out_ref) if n.endswith('.jpg')])
    if saved:
        print(f"[주의] 기존 쌍 {saved}개가 있습니다. 예전 촬영분이면 지우고 시작하세요.")

    while True:
        # 두 카메라에서 각각 한 프레임씩 읽는다.
        #   보드를 '정지'시킨 순간에 c 를 누르므로, 두 read 사이의 미세한
        #   시간차는 문제되지 않는다(정지 상태라 두 카메라가 같은 포즈를 봄).
        ok_ref, frame_ref = cap_ref.read()
        ok_tgt, frame_tgt = cap_tgt.read()
        if not ok_ref or not ok_tgt:
            continue

        # 각 프레임에서 chArUco 코너를 검출한다.
        gray_ref = cv2.cvtColor(frame_ref, cv2.COLOR_BGR2GRAY)
        gray_tgt = cv2.cvtColor(frame_tgt, cv2.COLOR_BGR2GRAY)
        cc_ref, ids_ref = detect_charuco(gray_ref)
        cc_tgt, ids_tgt = detect_charuco(gray_tgt)

        # 두 카메라에 공통으로 잡힌 코너 개수(이 쌍의 유효 표본 수).
        n_common = common_corner_count(ids_ref, ids_tgt)

        # 화면 표시용 사본을 만들어 검출 결과를 그린다(원본은 저장용으로 보존).
        view_ref = frame_ref.copy()
        view_tgt = frame_tgt.copy()
        if cc_ref is not None:
            # 코너 위치를 점+ID 로 표시 (체커보드의 무지개선과 다른 표시 방식).
            aruco.drawDetectedCornersCharuco(view_ref, cc_ref, ids_ref)
        if cc_tgt is not None:
            aruco.drawDetectedCornersCharuco(view_tgt, cc_tgt, ids_tgt)

        # 좌/우 프리뷰를 나란히 붙이기 위해 각각 640x360 으로 축소.
        small_ref = cv2.resize(view_ref, (640, 360))
        small_tgt = cv2.resize(view_tgt, (640, 360))
        combined = np.hstack([small_ref, small_tgt])

        # 공통 코너가 충분하면 초록, 아니면 빨강으로 안내.
        ok_to_save = n_common >= MIN_COMMON_CORNERS
        color = (0, 255, 0) if ok_to_save else (0, 0, 255)
        msg = "OK - press c" if ok_to_save else "need more shared corners"
        cv2.putText(combined, f"{ref_name}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(combined, f"{tgt_name}", (650, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(combined, f"common={n_common}  {msg}  saved={saved}",
                    (10, 345), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        cv2.imshow(f"stereo capture [{args.pair}]", combined)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('c') and ok_to_save:
            # 좌/우를 같은 인덱스로 저장(원본 프레임). 나중에 파일명으로 짝을 맞춤.
            fname = f"pair_{saved:03d}.jpg"
            cv2.imwrite(os.path.join(out_ref, fname), frame_ref)
            cv2.imwrite(os.path.join(out_tgt, fname), frame_tgt)
            saved += 1
            print(f"  저장 {saved}쌍: {fname} (공통 코너 {n_common}개)")

    cap_ref.release()
    cap_tgt.release()
    cv2.destroyAllWindows()
    print(f"종료. 총 {saved}쌍 저장됨 ({out_ref} / {out_tgt})")


if __name__ == "__main__":
    main()
