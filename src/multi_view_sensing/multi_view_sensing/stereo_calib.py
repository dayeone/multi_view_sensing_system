#!/usr/bin/env python3
"""
stereo_calib.py - 면별 2대 상대 자세(extrinsic) 계산기

[이 스크립트가 하는 일]
  stereo_capture.py 로 모은 좌/우 이미지 쌍을 읽어, 두 카메라 사이의
  '상대 자세'를 구한다.
    - R (3x3 회전행렬): 기준 카메라 좌표계를 상대 카메라 좌표계로 돌리는 회전
    - T (3x1 이동벡터): 두 카메라 원점 사이의 이동 [mm]
  즉 '기준 카메라에서 본 점'을 '상대 카메라에서 본 점'으로 바꾸는 변환이며,
  이것이 두 시점을 하나로 잇는 '공간 정합'의 핵심 값이다.

[핵심 아이디어 - intrinsic 고정]
  각 카메라의 내부 파라미터(초점거리·왜곡)는 이미 calib_params/ 에 있으므로,
  stereoCalibrate 에 CALIB_FIX_INTRINSIC 플래그를 줘서 '내부값은 그대로 두고
  두 카메라의 상대 자세(R,T)만' 추정한다. 이렇게 하면 미지수가 줄어 더 안정적이다.

[chArUco 매칭]
  두 카메라가 같은 순간 찍은 한 쌍에서, 각자 검출한 코너 중
  'ID가 양쪽에 공통인 코너'만 골라 3D-2D 대응점을 만든다.
  (chArUco 는 코너마다 ID가 있어 이런 부분 매칭이 가능하다.)

[사용법]
  python3 src/multi_view_sensing/multi_view_sensing/stereo_calib.py --pair left
  python3 src/multi_view_sensing/multi_view_sensing/stereo_calib.py --pair right

[출력]
  calib_params/stereo_<pair>_params.yaml
    (R, T, baseline_mm, rms, num_pairs, reference_cam, target_cam)
"""
import cv2
import cv2.aruco as aruco
import numpy as np
import glob
import os
import argparse
import yaml

# ─────────────────────────────────────────────────────────────────────────────
# chArUco 보드 설정 — stereo_capture.py 와 반드시 동일해야 한다.
#   (촬영 때와 계산 때의 보드 정의가 다르면 코너 3D 좌표가 어긋난다.)
# ─────────────────────────────────────────────────────────────────────────────
SQUARES_X = 7          # 가로 칸 수
SQUARES_Y = 5          # 세로 칸 수
SQUARE_LEN_MM = 35.0   # 한 칸 한 변 [mm]
MARKER_LEN_MM = 26.0   # 마커 한 변 [mm]
ARUCO_DICT = aruco.Dictionary_get(aruco.DICT_5X5_50)
CHARUCO_BOARD = aruco.CharucoBoard_create(
    SQUARES_X, SQUARES_Y, SQUARE_LEN_MM, MARKER_LEN_MM, ARUCO_DICT)

# 한 쌍에서 이만큼 이상 '공통 코너'가 있어야 계산에 사용한다.
#   코너가 너무 적으면(특히 6개 근처에 일렬로 늘어선 경우) 자세 추정이
#   붕괴(degenerate)해 전체 계산을 망칠 수 있으므로 넉넉히 잡는다.
MIN_COMMON_CORNERS = 8

# 개별 카메라에서 solvePnP 재투영 오차가 이 값(px)을 넘는 쌍은
#   검출/자세가 불량한 것으로 보고 계산에서 제외한다(이상치 제거).
MAX_PER_VIEW_ERR = 1.0

# 면(pair) → (기준 카메라, 상대 카메라). stereo_capture.py 와 동일하게 유지.
PAIRS = {
    "left":  {"ref": "cam1", "tgt": "cam2"},
    "right": {"ref": "cam3", "tgt": "cam4"},
}


def load_intrinsics(cam_name):
    """calib_params/<cam>_params.yaml 에서 내부 파라미터를 읽어온다.

    돌려주는 값:
      K: (3x3) 카메라 행렬(초점거리·주점), D: (1xN) 왜곡 계수.
    이 값들은 intrinsic 캘리브레이션(calib_calc.py) 결과다.
    """
    path = os.path.expanduser(f'~/pest_control_ws/calib_params/{cam_name}_params.yaml')
    with open(path) as f:
        data = yaml.safe_load(f)
    K = np.array(data['camera_matrix'], dtype=np.float64)
    D = np.array(data['dist_coeff'], dtype=np.float64)
    return K, D


def detect_charuco(gray):
    """흑백 이미지에서 chArUco 코너와 ID를 검출한다.

    (stereo_capture.py 의 동명 함수와 같은 절차: 마커 검출 → 코너 보간)
    돌려주는 값: (코너 (N,1,2), ID (N,1)) 또는 검출 실패 시 (None, None).
    """
    params = aruco.DetectorParameters_create()
    marker_corners, marker_ids, _ = aruco.detectMarkers(
        gray, ARUCO_DICT, parameters=params)
    if marker_ids is None or len(marker_ids) == 0:
        return None, None
    retval, charuco_corners, charuco_ids = aruco.interpolateCornersCharuco(
        marker_corners, marker_ids, gray, CHARUCO_BOARD)
    if retval is None or retval == 0 or charuco_corners is None:
        return None, None
    return charuco_corners, charuco_ids


def match_common_points(cc_ref, ids_ref, cc_tgt, ids_tgt):
    """두 카메라의 검출 결과에서 'ID가 공통인 코너'만 골라 대응점을 만든다.

    stereoCalibrate 에 넣을 세 묶음을 같은 순서로 만들어 돌려준다.
      obj : (M,1,3) 코너의 보드 좌표계 3D 위치 [mm]
      pt_ref : (M,1,2) 기준 카메라에서의 코너 픽셀 위치
      pt_tgt : (M,1,2) 상대 카메라에서의 코너 픽셀 위치
    공통 코너가 MIN_COMMON_CORNERS 미만이면 None 을 돌려준다(그 쌍은 버림).
    """
    if ids_ref is None or ids_tgt is None:
        return None

    # ID 를 1차원 배열로 펴서 다루기 쉽게 한다.
    flat_ref = ids_ref.flatten()
    flat_tgt = ids_tgt.flatten()
    common_ids = np.intersect1d(flat_ref, flat_tgt)  # 양쪽에 다 있는 ID
    if len(common_ids) < MIN_COMMON_CORNERS:
        return None

    # 보드가 아는 '코너별 3D 좌표'. shape (전체코너수, 3).
    board_pts = CHARUCO_BOARD.chessboardCorners

    obj, pt_ref, pt_tgt = [], [], []
    for cid in common_ids:
        # 각 카메라에서 이 ID 코너가 몇 번째로 검출됐는지 위치를 찾는다.
        i_ref = np.where(flat_ref == cid)[0][0]
        i_tgt = np.where(flat_tgt == cid)[0][0]
        obj.append(board_pts[cid])            # 이 코너의 3D 좌표(보드 기준)
        pt_ref.append(cc_ref[i_ref][0])       # 기준 카메라 픽셀 좌표
        pt_tgt.append(cc_tgt[i_tgt][0])       # 상대 카메라 픽셀 좌표

    # OpenCV 가 기대하는 형태 (M,1,3)/(M,1,2), float32 로 정리한다.
    obj = np.array(obj, dtype=np.float32).reshape(-1, 1, 3)
    pt_ref = np.array(pt_ref, dtype=np.float32).reshape(-1, 1, 2)
    pt_tgt = np.array(pt_tgt, dtype=np.float32).reshape(-1, 1, 2)
    return obj, pt_ref, pt_tgt


def pnp_reproj_error(obj, pts, K, D):
    """대응점(obj 3D ↔ pts 2D)으로 카메라 한 대의 보드 자세를 풀고(solvePnP),
    그 자세로 다시 투영했을 때의 재투영 오차 RMS(px)를 돌려준다.

    이 값이 크거나(불량 검출) 무한대이면(자세 붕괴) 그 쌍은 계산에서 뺀다.
    코너가 적고 일렬로 늘어선 쌍은 자세가 붕괴해 inf 가 나오는데,
    이런 쌍 하나가 stereoCalibrate 전체를 망칠 수 있어 미리 걸러낸다.
    """
    ok, rvec, tvec = cv2.solvePnP(obj, pts, K, D)
    if not ok:
        return float('inf')
    proj, _ = cv2.projectPoints(obj, rvec, tvec, K, D)
    err = np.linalg.norm(proj.reshape(-1, 2) - pts.reshape(-1, 2), axis=1)
    rms = float(np.sqrt(np.mean(err ** 2)))
    return rms if np.isfinite(rms) else float('inf')


def manual_stereo_rms(objpoints, pts_ref, pts_tgt, K_ref, D_ref, K_tgt, D_tgt, R, T):
    """검증용: 신뢰할 수 있는 스테레오 재투영 오차(RMS, px)를 직접 계산한다.

    절차: 기준 카메라에서 보드 자세를 풀고 → 그 3D 점을 R,T 로 상대 카메라
    좌표계로 옮긴 뒤 → 상대 카메라에 재투영해 실제 검출 위치와 비교한다.
    stereoCalibrate 가 돌려주는 RMS 가 드물게 수치적으로 폭주할 때를 대비한,
    독립적이고 믿을 수 있는 정확도 지표다.
    """
    all_err = []
    for obj, p_ref, p_tgt in zip(objpoints, pts_ref, pts_tgt):
        ok, rvec, tvec = cv2.solvePnP(obj, p_ref, K_ref, D_ref)
        if not ok:
            continue
        R_b, _ = cv2.Rodrigues(rvec)
        X_ref = (R_b @ obj.reshape(-1, 3).T + tvec).T   # 기준 카메라 좌표계 3D 점
        X_tgt = (R @ X_ref.T + T).T                      # 상대 카메라 좌표계로 변환
        proj, _ = cv2.projectPoints(X_tgt, np.zeros(3), np.zeros(3), K_tgt, D_tgt)
        err = np.linalg.norm(proj.reshape(-1, 2) - p_tgt.reshape(-1, 2), axis=1)
        all_err.extend(err)
    if not all_err:
        return float('inf')
    all_err = np.array(all_err)
    return float(np.sqrt(np.mean(all_err ** 2)))


def stereo_calibrate_pair(pair_name):
    """한 면(pair)의 좌/우 쌍들을 모두 읽어 상대 자세(R,T)를 계산하고 저장한다."""
    ref_name = PAIRS[pair_name]["ref"]
    tgt_name = PAIRS[pair_name]["tgt"]

    # 두 카메라의 내부 파라미터를 불러온다(고정해서 쓸 값).
    K_ref, D_ref = load_intrinsics(ref_name)
    K_tgt, D_tgt = load_intrinsics(tgt_name)

    # 저장된 쌍 목록을 기준 카메라 폴더 기준으로 나열한다.
    ref_dir = os.path.expanduser(f'~/pest_control_ws/stereo_data/{pair_name}/{ref_name}')
    tgt_dir = os.path.expanduser(f'~/pest_control_ws/stereo_data/{pair_name}/{tgt_name}')
    ref_files = sorted(glob.glob(os.path.join(ref_dir, '*.jpg')))
    if not ref_files:
        print(f"[{pair_name}] {ref_dir} 에 이미지가 없습니다. 먼저 stereo_capture.py 로 촬영하세요.")
        return None

    print(f"\n===== {pair_name}: 기준={ref_name}, 상대={tgt_name} / {len(ref_files)}쌍 분석 =====")

    # stereoCalibrate 에 넣을, 쌍마다의 대응점 묶음을 모은다.
    objpoints, imgpoints_ref, imgpoints_tgt = [], [], []
    used_names = []          # 계산에 사용한 쌍의 파일명(순서 보존)
    per_view_err = []        # (파일명, cam_ref solvePnP오차, cam_tgt solvePnP오차)
    dropped = []             # (파일명, 제외 사유) — 파일로 남겨 나중에 원인 추적
    used, skipped = 0, 0
    img_size = None

    for ref_path in ref_files:
        # 같은 파일명이 상대 카메라 폴더에도 있어야 '짝'이 성립한다.
        fname = os.path.basename(ref_path)
        tgt_path = os.path.join(tgt_dir, fname)
        if not os.path.exists(tgt_path):
            print(f"  건너뜀(짝 없음): {fname}")
            dropped.append((fname, "짝 없음"))
            skipped += 1
            continue

        img_ref = cv2.imread(ref_path)
        img_tgt = cv2.imread(tgt_path)
        if img_ref is None or img_tgt is None:
            dropped.append((fname, "이미지 읽기 실패"))
            skipped += 1
            continue

        gray_ref = cv2.cvtColor(img_ref, cv2.COLOR_BGR2GRAY)
        gray_tgt = cv2.cvtColor(img_tgt, cv2.COLOR_BGR2GRAY)
        if img_size is None:
            # stereoCalibrate 에 넘길 이미지 크기 (width, height).
            img_size = gray_ref.shape[::-1]

        # 각 이미지에서 코너 검출 후, 공통 ID 코너만 대응점으로 만든다.
        cc_ref, ids_ref = detect_charuco(gray_ref)
        cc_tgt, ids_tgt = detect_charuco(gray_tgt)
        matched = match_common_points(cc_ref, ids_ref, cc_tgt, ids_tgt)
        if matched is None:
            n = 0 if ids_ref is None or ids_tgt is None else \
                len(np.intersect1d(ids_ref.flatten(), ids_tgt.flatten()))
            print(f"  건너뜀(공통 코너 {n}개 < {MIN_COMMON_CORNERS}): {fname}")
            dropped.append((fname, f"공통 코너 {n}개 < {MIN_COMMON_CORNERS}"))
            skipped += 1
            continue

        obj, pt_ref, pt_tgt = matched

        # ── 이상치 사전 제거 ──
        #   각 카메라에서 이 쌍의 보드 자세를 개별로 풀어보고, 재투영이
        #   불량하거나 붕괴한(=degenerate) 쌍은 계산에 넣지 않는다.
        #   (코너 몇 개가 일렬로 늘어선 쌍 하나가 전체 계산을 망치는 것 방지)
        err_ref = pnp_reproj_error(obj, pt_ref, K_ref, D_ref)
        err_tgt = pnp_reproj_error(obj, pt_tgt, K_tgt, D_tgt)
        if err_ref > MAX_PER_VIEW_ERR or err_tgt > MAX_PER_VIEW_ERR:
            print(f"  건너뜀(자세 불량 ref={err_ref:.2f}/tgt={err_tgt:.2f}px): {fname}")
            dropped.append((fname, f"자세 불량 ref={err_ref:.2f}/tgt={err_tgt:.2f}px"))
            skipped += 1
            continue

        objpoints.append(obj)
        imgpoints_ref.append(pt_ref)
        imgpoints_tgt.append(pt_tgt)
        used_names.append(fname)
        per_view_err.append((fname, round(err_ref, 4), round(err_tgt, 4)))
        used += 1

    if used < 5:
        print(f"[{pair_name}] 사용 가능한 쌍이 {used}개뿐입니다(최소 5개 권장). "
              f"촬영을 더 하거나 겹침을 늘리세요.")
        if used == 0:
            return None

    # ── 핵심 계산: 내부 파라미터 고정, 상대 자세(R,T)만 추정 ──
    #   flags=CALIB_FIX_INTRINSIC → K,D 는 그대로 두고 R,T,E,F 만 최적화.
    flags = cv2.CALIB_FIX_INTRINSIC
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-5)
    rms, K1, D1, K2, D2, R, T, E, F = cv2.stereoCalibrate(
        objpoints, imgpoints_ref, imgpoints_tgt,
        K_ref, D_ref, K_tgt, D_tgt, img_size,
        criteria=criteria, flags=flags)

    # baseline = 두 카메라 원점 사이 거리(=T 벡터의 길이) [mm].
    #   실제 카메라 간격(자로 잰 값)과 비슷해야 결과가 신뢰할 만하다(sanity check).
    baseline = float(np.linalg.norm(T))

    # stereoCalibrate 가 돌려주는 RMS 는 드물게 수치적으로 폭주(오버플로우)할 수
    # 있어, 신뢰할 수 있는 지표를 직접(수동) 재투영으로 한 번 더 계산한다.
    manual_rms = manual_stereo_rms(objpoints, imgpoints_ref, imgpoints_tgt,
                                   K_ref, D_ref, K_tgt, D_tgt, R, T)
    # 반환값이 정상 범위면 그대로, 비정상이면 수동 계산값을 대표값으로 쓴다.
    rms_report = rms if (np.isfinite(rms) and rms < 100) else manual_rms

    print(f"\n사용 {used}쌍 (건너뜀 {skipped}쌍)")
    print(f"스테레오 재투영 오차(RMS): {rms_report:.4f} px  (1.0 미만이면 양호)")
    print(f"  (참고: stereoCalibrate 반환값={rms:.4g}, 수동 검증값={manual_rms:.4f} px)")
    print(f"baseline(‖T‖): {baseline:.1f} mm  ← 실측 카메라 간격과 비교해 보세요")
    print("R(회전행렬):")
    print(np.array2string(R, precision=5, suppress_small=True))
    print(f"T(이동, mm): {np.array2string(T.flatten(), precision=2)}")

    # 이미지별(쌍별) 스테레오 재투영 오차도 계산해 파일에 남긴다(진단용).
    #   manual_stereo_rms 를 쌍 하나짜리 리스트로 호출하면 그 쌍의 RMS가 나온다.
    per_pair_rms = {}
    for name, obj, p_ref, p_tgt in zip(
            used_names, objpoints, imgpoints_ref, imgpoints_tgt):
        e = manual_stereo_rms([obj], [p_ref], [p_tgt],
                              K_ref, D_ref, K_tgt, D_tgt, R, T)
        per_pair_rms[name] = round(float(e), 4)

    # 개별 카메라 solvePnP 재투영 오차(사전검증 값)도 파일에 남긴다.
    per_view = {name: {'ref_px': er, 'tgt_px': et}
                for (name, er, et) in per_view_err}

    # 결과를 YAML 로 저장. (R,T 는 list 로 변환해 사람이 읽을 수 있게)
    out_dir = os.path.expanduser('~/pest_control_ws/calib_params')
    os.makedirs(out_dir, exist_ok=True)
    save_file = os.path.join(out_dir, f'stereo_{pair_name}_params.yaml')
    with open(save_file, 'w') as f:
        yaml.dump({
            'pair': pair_name,
            'reference_cam': ref_name,   # R,T 변환의 '기준' 카메라
            'target_cam': tgt_name,      # 변환의 '상대' 카메라
            'R': R.tolist(),
            'T': T.tolist(),
            'baseline_mm': baseline,
            'rms_error': float(rms_report),          # 대표 재투영 오차(신뢰값)
            'rms_error_manual': float(manual_rms),   # 수동 검증 재투영 오차
            'num_pairs': used,
            'num_dropped': skipped,
            'per_pair_rms': per_pair_rms,            # 쌍별 스테레오 재투영 오차[px]
            'per_view_solvepnp_err': per_view,       # 쌍별 카메라 개별 재투영[px]
            'dropped_pairs': {n: r for (n, r) in dropped},  # 제외된 쌍과 사유
        }, f, allow_unicode=True, sort_keys=False)
    print(f"  저장: {save_file}")
    return rms_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pair', choices=['left', 'right', 'all'], default='all',
                        help="계산할 면: left, right, 또는 all(둘 다)")
    args = parser.parse_args()

    targets = ['left', 'right'] if args.pair == 'all' else [args.pair]

    summary = {}
    for p in targets:
        rms = stereo_calibrate_pair(p)
        if rms is not None:
            summary[p] = rms

    print("\n===== 요약 (스테레오 RMS, 낮을수록 좋음) =====")
    for p in targets:
        val = f"{summary[p]:.4f} px" if p in summary else "실패/건너뜀"
        print(f"  {p}: {val}")


if __name__ == "__main__":
    main()
