#!/usr/bin/env python3
"""
plot_reprojection.py - KIIS 논문 Figure 8 (공간 정합 재투영 시각화) 생성기

[하는 일]
  면별 스테레오 정합의 정확도를, 한 카메라(기준)에서 검출한 chArUco 코너를
  스테레오 R,T로 상대 카메라 좌표계로 옮겨 상대 카메라 이미지에 재투영하고,
  실제 검출 코너와 겹쳐 그려 보여준다.
    - 초록 원(o)  = 실제 검출 코너
    - 빨강 십자(+) = 재투영 코너
  두 점이 겹칠수록 정합이 정확함을 뜻한다. 좌·우 면을 (a)(b) 2패널로 배치한다.

[표 6과의 일관성]
  스테레오 R,T·intrinsic은 표 6(stereoCalibrate)을 산출한 값을 그대로 쓴다.
  시각화 쌍은 per_pair_rms가 가장 낮은(정합이 좋은) 쌍을 각 면에서 자동 선택하고,
  패널 캡션의 재투영 오차는 표 6의 면별 RMS(좌 0.37 / 우 0.51 px)로 표기한다.

[사용법]
  python3 quick_capture/plot_reprojection.py

[출력]
  figures/fig8_reprojection.png (300 dpi)
"""
import cv2
import cv2.aruco as aruco
import numpy as np
import os
import yaml
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

# chArUco 보드 (stereo_calib.py와 동일)
ARUCO_DICT = aruco.Dictionary_get(aruco.DICT_5X5_50)
BOARD = aruco.CharucoBoard_create(7, 5, 35.0, 26.0, ARUCO_DICT)
DET = aruco.DetectorParameters_create()

ROOT = os.path.expanduser("~/pest_control_ws")
FACES = {
    "left":  {"ref": "cam1", "tgt": "cam2", "cap": "Left side"},
    "right": {"ref": "cam3", "tgt": "cam4", "cap": "Right side"},
}


def load_K(cam):
    d = yaml.safe_load(open(f"{ROOT}/calib_params/{cam}_params.yaml"))
    return np.array(d["camera_matrix"], float), np.array(d["dist_coeff"], float)


def load_stereo(face):
    d = yaml.safe_load(open(f"{ROOT}/calib_params/stereo_{face}_params.yaml"))
    return (np.array(d["R"], float), np.array(d["T"], float),
            float(d["rms_error"]), d.get("per_pair_rms", {}))


def detect(gray):
    mc, mi, _ = aruco.detectMarkers(gray, ARUCO_DICT, parameters=DET)
    if mi is None or len(mi) == 0:
        return None, None
    r, cc, ci = aruco.interpolateCornersCharuco(mc, mi, gray, BOARD)
    if r is None or r == 0:
        return None, None
    return cc, ci


def matched(cc_r, ids_r, cc_t, ids_t):
    fr, ft = ids_r.flatten(), ids_t.flatten()
    common = np.intersect1d(fr, ft)
    if len(common) < 4:
        return None
    bpts = BOARD.chessboardCorners
    obj = np.array([bpts[c] for c in common], np.float32)
    pr = np.array([cc_r[np.where(fr == c)[0][0]][0] for c in common], np.float32)
    pt = np.array([cc_t[np.where(ft == c)[0][0]][0] for c in common], np.float32)
    return obj, pr, pt, len(common)


def build_panel(face):
    ref, tgt = FACES[face]["ref"], FACES[face]["tgt"]
    K_ref, D_ref = load_K(ref)
    K_tgt, D_tgt = load_K(tgt)
    R, T, face_rms, ppr = load_stereo(face)

    # per_pair_rms가 가장 낮은(정합 좋은) 쌍 선택
    fn = min(ppr.items(), key=lambda kv: kv[1])[0]
    rp = f"{ROOT}/stereo_data/{face}/{ref}/{fn}"
    tp = f"{ROOT}/stereo_data/{face}/{tgt}/{fn}"

    g_ref = cv2.cvtColor(cv2.imread(rp), cv2.COLOR_BGR2GRAY)
    g_tgt = cv2.cvtColor(cv2.imread(tp), cv2.COLOR_BGR2GRAY)
    cc_r, ids_r = detect(g_ref)
    cc_t, ids_t = detect(g_tgt)
    obj, pr, pt, n = matched(cc_r, ids_r, cc_t, ids_t)

    # 기준 카메라에서 보드 자세 → R,T로 상대 좌표계 → 상대 카메라에 재투영
    ok, rvec, tvec = cv2.solvePnP(obj, pr, K_ref, D_ref)
    Rb, _ = cv2.Rodrigues(rvec)
    X_ref = (Rb @ obj.T + tvec).T
    X_tgt = (R @ X_ref.T + T).T
    proj, _ = cv2.projectPoints(X_tgt, np.zeros(3), np.zeros(3), K_tgt, D_tgt)
    proj = proj.reshape(-1, 2)
    det = pt.reshape(-1, 2)

    # 상대 카메라 원본 이미지에 오버레이
    img = cv2.imread(tp)
    for (x, y) in det.astype(int):
        cv2.circle(img, (x, y), 10, (0, 255, 0), 2, cv2.LINE_AA)         # 초록 원 = 검출
    for (x, y) in proj.astype(int):
        cv2.drawMarker(img, (x, y), (0, 0, 255), cv2.MARKER_CROSS, 16, 2, cv2.LINE_AA)  # 빨강 + = 재투영

    # 보드 영역으로 크롭(코너 가시성↑, 배경 인물·실험실 최소화)
    allp = np.vstack([det, proj])
    x0, y0 = allp.min(0); x1, y1 = allp.max(0)
    pad = 0.22 * max(x1 - x0, y1 - y0)
    H, W = img.shape[:2]
    img = img[int(max(0, y0 - pad)):int(min(H, y1 + pad)),
              int(max(0, x0 - pad)):int(min(W, x1 + pad))]

    return {"img": img, "cap": FACES[face]["cap"], "rms": face_rms, "fn": fn, "n": n}


def main():
    panels = [("a", build_panel("left")), ("b", build_panel("right"))]

    plt.rcParams.update({"font.size": 11})
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.0))
    for ax, (tag, p) in zip(axes, panels):
        ax.imshow(cv2.cvtColor(p["img"], cv2.COLOR_BGR2RGB))
        ax.set_xticks([]); ax.set_yticks([])
        # 패널 하단 영문 캡션 (표 6 면별 RMS)
        ax.set_xlabel(f"({tag}) {p['cap']}, reprojection error {p['rms']:.2f} px", fontsize=12)

    legend = [Line2D([0], [0], marker='o', color='none', markeredgecolor='lime',
                     markerfacecolor='none', markersize=10, markeredgewidth=2,
                     label='detected corner (o)'),
              Line2D([0], [0], marker='P', color='none', markerfacecolor='red',
                     markersize=11, label='reprojected corner (+)')]
    fig.legend(handles=legend, loc='lower center', ncol=2, frameon=False,
               bbox_to_anchor=(0.5, -0.01))
    fig.tight_layout(rect=[0, 0.05, 1, 1])

    out = f"{ROOT}/figures/fig8_reprojection.png"
    os.makedirs(f"{ROOT}/figures", exist_ok=True)
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(f"저장: {out}")
    for tag, p in panels:
        print(f"  ({tag}) {p['cap']}: 쌍 {p['fn']}, 공통코너 {p['n']}, 표6 RMS {p['rms']:.2f}px")


if __name__ == "__main__":
    main()
