import cv2
import numpy as np
import glob
import os
import argparse
import yaml

# 체커보드 정보 (촬영한 보드와 동일해야 함)
CHECKERBOARD = (7, 9)  # 내부 코너 개수
SQUARE_SIZE = 20.0      # mm 단위

# 3D 실제 좌표 (0,0,0), (20,0,0), (40,0,0) ...
objp = np.zeros((CHECKERBOARD[0] * CHECKERBOARD[1], 3), np.float32)
objp[:, :2] = np.mgrid[0:CHECKERBOARD[0], 0:CHECKERBOARD[1]].T.reshape(-1, 2)
objp *= SQUARE_SIZE


def per_image_errors(objpoints, imgpoints, rvecs, tvecs, mtx, dist):
    """이미지별 재투영 오차(px) 목록."""
    errs = []
    for i in range(len(objpoints)):
        proj, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], mtx, dist)
        e = np.sqrt(np.mean(np.sum(
            (imgpoints[i].reshape(-1, 2) - proj.reshape(-1, 2)) ** 2, axis=1)))
        errs.append(e)
    return errs


def calibrate(cam_idx, max_err, min_images):
    """calib_data/cam{cam_idx}/ 이미지로 intrinsic 계산.
    오차 큰 사진을 한 장씩 제외하며(이상치 제거) 재계산하고 calib_params/에 저장한다.
    사진 파일은 지우지 않고 계산에서만 제외한다."""
    images = glob.glob(os.path.expanduser(f'~/pest_control_ws/calib_data/cam{cam_idx}/*.jpg'))
    if not images:
        print(f"[cam{cam_idx}] 이미지를 찾을 수 없습니다. 건너뜀.")
        return None

    print(f"\n===== cam{cam_idx}: {len(images)}장 분석 =====")
    objpoints, imgpoints, used = [], [], []
    gray = None
    for fname in images:
        img = cv2.imread(fname)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, CHECKERBOARD, None)
        if ret:
            objpoints.append(objp)
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners2 = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            imgpoints.append(corners2)
            used.append(os.path.basename(fname))
        else:
            print(f"  인식 실패: {os.path.basename(fname)}")

    if len(objpoints) < min_images:
        print(f"[cam{cam_idx}] 인식 성공 {len(objpoints)}장 < 최소 {min_images}장. 건너뜀.")
        return None

    n_start = len(objpoints)
    img_size = gray.shape[::-1]
    dropped = []

    # 이상치 제거 반복: 가장 오차 큰 사진을 한 장씩 빼며 재계산
    while True:
        ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
            objpoints, imgpoints, img_size, None, None)
        errs = per_image_errors(objpoints, imgpoints, rvecs, tvecs, mtx, dist)
        worst = int(np.argmax(errs))
        if errs[worst] <= max_err or len(objpoints) <= min_images:
            break
        dropped.append((used[worst], errs[worst]))
        for lst in (objpoints, imgpoints, used):
            del lst[worst]

    print(f"사용 {len(used)}장 (시작 {n_start}장, 이상치 제외 {len(dropped)}장, 임계 {max_err}px)")
    if dropped:
        print("  제외된 사진:", ", ".join(f"{n}({e:.2f})" for n, e in dropped))
    print(f"재투영 오차(RMS): {ret:.4f} px  (1.0 미만이면 양호)")

    out_dir = os.path.expanduser('~/pest_control_ws/calib_params')
    os.makedirs(out_dir, exist_ok=True)
    save_file = os.path.join(out_dir, f'cam{cam_idx}_params.yaml')
    with open(save_file, 'w') as f:
        yaml.dump({
            'camera_matrix': mtx.tolist(),
            'dist_coeff': dist.tolist(),
            'rms_error': float(ret),
            'used_images': len(used),
        }, f)
    print(f"  저장: {save_file}")
    return ret


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cams', type=int, nargs='+', default=[0, 1, 2, 3],
                        help='계산할 카메라 번호들 (기본: 0 1 2 3)')
    parser.add_argument('--max-err', type=float, default=1.0,
                        help='이 값(px)을 넘는 사진은 이상치로 제외 (기본 1.0)')
    parser.add_argument('--min-images', type=int, default=15,
                        help='이상치 제거 후 유지할 최소 장수 (기본 15)')
    args = parser.parse_args()

    summary = {}
    for idx in args.cams:
        rms = calibrate(idx, args.max_err, args.min_images)
        if rms is not None:
            summary[idx] = rms

    print("\n===== 요약 (RMS 재투영 오차, 낮을수록 좋음) =====")
    for idx in args.cams:
        val = f"{summary[idx]:.4f} px" if idx in summary else "실패/건너뜀"
        print(f"  cam{idx}: {val}")


if __name__ == "__main__":
    main()
