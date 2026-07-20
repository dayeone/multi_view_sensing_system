#!/usr/bin/env python3
"""
calib_coverage.py - 캘리브레이션 촬영 커버리지 맵 생성기

[하는 일]
  calib_data/cam{N}/ 의 모든 사진에서 체커보드를 검출하고,
  각 보드의 외곽(초록 선)과 검출 코너(초록 점)를 하나의 프레임 위에
  누적 오버레이하여 "보드가 프레임 어디를 얼마나 덮었는지"를 보여준다.
  intrinsic 품질은 프레임 가장자리·모서리·다양한 기울기를 얼마나
  고르게 덮었는지에 크게 좌우되므로, 촬영 전략 점검용으로 쓴다.

[사용법]
  python3 quick_capture/calib_coverage.py --cams 1 2 3 4
  python3 quick_capture/calib_coverage.py --cams 1        # 한 대만

[출력]
  coverage_maps/cam{N}_coverage.png   카메라별 커버리지 맵
  coverage_maps/coverage_grid.png     2x2 통합 그리드
"""
import cv2
import numpy as np
import glob
import os
import argparse

CHECKERBOARD = (7, 9)  # 내부 코너 (cols, rows) — calib_calc.py와 동일
FRAME_W, FRAME_H = 1280, 720


def board_outline_indices():
    """검출 코너 배열(row-major)에서 외곽 사각형 4점의 인덱스."""
    cols, rows = CHECKERBOARD
    tl = 0
    tr = cols - 1
    bl = cols * (rows - 1)
    br = cols * rows - 1
    return [tl, tr, br, bl]


def build_coverage(cam_idx):
    """cam{cam_idx} 커버리지 맵 이미지(BGR)를 만들어 반환. 없으면 None."""
    images = sorted(glob.glob(
        os.path.expanduser(f'~/pest_control_ws/calib_data/cam{cam_idx}/*.jpg')))
    if not images:
        print(f"[cam{cam_idx}] 이미지 없음. 건너뜀.")
        return None, 0, 0

    canvas = np.full((FRAME_H, FRAME_W, 3), 30, np.uint8)  # 어두운 회색 배경
    # 프레임 테두리
    cv2.rectangle(canvas, (0, 0), (FRAME_W - 1, FRAME_H - 1), (90, 90, 90), 2)

    outline_idx = board_outline_indices()
    overlay = canvas.copy()
    n_found = 0
    for fname in images:
        img = cv2.imread(fname)
        if img is None:
            continue
        # 촬영 해상도가 다를 수 있으니 좌표를 프레임 기준으로 스케일
        h, w = img.shape[:2]
        sx, sy = FRAME_W / w, FRAME_H / h
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, CHECKERBOARD, None)
        if not ret:
            continue
        n_found += 1
        pts = corners.reshape(-1, 2).copy()
        pts[:, 0] *= sx
        pts[:, 1] *= sy
        quad = pts[outline_idx].astype(np.int32)
        # 반투명 채움(밀도 표현) + 외곽선
        cv2.fillPoly(overlay, [quad], (0, 90, 0))
        cv2.polylines(canvas, [quad], True, (0, 255, 0), 1, cv2.LINE_AA)
        for p in pts.astype(np.int32):
            cv2.circle(canvas, tuple(p), 2, (0, 255, 0), -1, cv2.LINE_AA)

    out = cv2.addWeighted(overlay, 0.5, canvas, 0.5, 0)
    label = f"cam{cam_idx}  boards={n_found}/{len(images)}"
    cv2.putText(out, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (255, 255, 255), 2, cv2.LINE_AA)
    return out, n_found, len(images)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cams', type=int, nargs='+', default=[1, 2, 3, 4])
    args = parser.parse_args()

    out_dir = os.path.expanduser('~/pest_control_ws/coverage_maps')
    os.makedirs(out_dir, exist_ok=True)

    maps = {}
    for idx in args.cams:
        img, found, total = build_coverage(idx)
        if img is None:
            continue
        path = os.path.join(out_dir, f'cam{idx}_coverage.png')
        cv2.imwrite(path, img)
        maps[idx] = img
        print(f"cam{idx}: 검출 {found}/{total}장 -> {path}")

    # 2x2 통합 그리드 (요청 순서 기준 최대 4대)
    if maps:
        cell_w, cell_h = FRAME_W // 2, FRAME_H // 2
        grid = np.full((cell_h * 2, cell_w * 2, 3), 15, np.uint8)
        for slot, idx in enumerate(sorted(maps.keys())[:4]):
            r, c = divmod(slot, 2)
            cell = cv2.resize(maps[idx], (cell_w, cell_h))
            grid[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w] = cell
        gpath = os.path.join(out_dir, 'coverage_grid.png')
        cv2.imwrite(gpath, grid)
        print(f"통합 그리드 -> {gpath}")


if __name__ == "__main__":
    main()
