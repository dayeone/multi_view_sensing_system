#!/usr/bin/env python3
"""
plot_sync_gap.py - 시간 동기화 gap 비교 그림 생성 (latest vs nearest)

[하는 일]
  recorder.py가 통제 비교 모드로 남긴 sync_log.csv(열 gap_latest_ms, gap_nearest_ms)
  들을 모아, 두 정합 방식의 gap 분포를 한 그림으로 비교한다.
    - 왼쪽: 히스토그램(분포 모양이 얼마나 낮은 gap 쪽으로 몰렸는가)
    - 오른쪽: 누적분포(CDF, 최악값·백분위수 꼬리 비교)
  논문 figure 용도. 색은 색맹 안전(Okabe-Ito) + 해치/선스타일로 이중 부호화한다.

[사용법]
  python3 quick_capture/plot_sync_gap.py
  (gap_latest_ms 열이 있는 모든 세션을 자동으로 모은다)

[출력]
  figures/sync_gap_comparison.png (300dpi)
"""
import csv
import os
import glob
import numpy as np
import matplotlib
matplotlib.use("Agg")  # 창 없이 파일로만 저장(원격/헤드리스에서도 동작)
import matplotlib.pyplot as plt

# 색맹 안전 팔레트(Okabe-Ito) — 두 방식을 색으로 구분하되, 해치/선스타일도 함께 써서
# 색만으로 구분하지 않도록 한다(흑백 인쇄·색각 이상 대비).
C_LATEST = "#0072B2"   # 파랑  = latest(baseline)
C_NEAREST = "#E69F00"  # 주황  = nearest(제안)


def collect():
    """gap_latest_ms 열이 있는 세션들에서 두 방식 gap 배열을 모아 돌려준다."""
    paths = sorted(glob.glob(os.path.expanduser(
        '~/pest_control_ws/quick_capture_data/session_*/sync_log.csv')))
    L, N, n_sessions = [], [], 0
    for p in paths:
        rows = list(csv.DictReader(open(p)))
        if not rows or "gap_latest_ms" not in rows[0]:
            continue  # 옛 형식(비교 열 없음) 세션은 건너뜀
        L += [float(r["gap_latest_ms"]) for r in rows]
        N += [float(r["gap_nearest_ms"]) for r in rows]
        n_sessions += 1
    return np.array(L), np.array(N), n_sessions


def main():
    L, N, n_sessions = collect()
    if len(L) == 0:
        print("비교 로깅(gap_latest_ms) 세션이 없습니다. recorder를 최신 버전으로 녹화하세요.")
        return

    # 전역 스타일: 작은 그림용 글꼴 크기, 옅은 격자
    plt.rcParams.update({"font.size": 11, "axes.grid": True,
                         "grid.color": "#dddddd", "grid.linewidth": 0.6})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    # ── (a) 히스토그램: 분포 모양 비교 ──
    hi = max(L.max(), N.max())
    bins = np.arange(0, np.ceil(hi / 2) * 2 + 2, 2)  # 2ms 폭
    ax1.hist(L, bins=bins, color=C_LATEST, alpha=0.55, label="latest (baseline)",
             edgecolor=C_LATEST, linewidth=0.8)
    ax1.hist(N, bins=bins, color=C_NEAREST, alpha=0.55, label="nearest (proposed)",
             edgecolor=C_NEAREST, linewidth=0.8, hatch="//")
    # 평균선 표시(점선) + 값 주석
    ax1.axvline(L.mean(), color=C_LATEST, ls="--", lw=1.5)
    ax1.axvline(N.mean(), color=C_NEAREST, ls="--", lw=1.5)
    ax1.set_title("(a) Sync gap distribution")
    ax1.set_xlabel("Sync gap (ms)")
    ax1.set_ylabel("Count (sets)")
    ax1.legend(frameon=False)

    # ── (b) 누적분포(CDF): 꼬리(최악값)·백분위수 비교 ──
    for data, c, ls, lab in [(L, C_LATEST, "-", "latest (baseline)"),
                             (N, C_NEAREST, "--", "nearest (proposed)")]:
        xs = np.sort(data)
        ys = np.arange(1, len(xs) + 1) / len(xs)
        ax2.step(xs, ys, where="post", color=c, ls=ls, lw=2, label=lab)
    ax2.axhline(0.95, color="#888888", lw=0.8, ls=":")  # p95 기준선
    ax2.text(hi * 0.62, 0.955, "p95", color="#888888", fontsize=9)
    ax2.set_title("(b) Cumulative distribution")
    ax2.set_xlabel("Sync gap (ms)")
    ax2.set_ylabel("Cumulative fraction")
    ax2.set_ylim(0, 1.02)
    ax2.legend(frameon=False, loc="lower right")

    fig.suptitle(
        f"4-channel capture sync gap: latest vs nearest matching "
        f"({n_sessions} sessions, {len(L)} sets)", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.96])

    out_dir = os.path.expanduser('~/pest_control_ws/figures')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "sync_gap_comparison.png")
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(f"저장: {out}")

    # 그림에 담긴 핵심 수치도 콘솔에 함께 출력
    print(f"세션 {n_sessions} / 세트 {len(L)}")
    print(f"latest : 평균 {L.mean():.2f} | p95 {np.percentile(L,95):.2f} | 최대 {L.max():.2f} ms")
    print(f"nearest: 평균 {N.mean():.2f} | p95 {np.percentile(N,95):.2f} | 최대 {N.max():.2f} ms")
    print(f"평균 개선 {100*(L.mean()-N.mean())/L.mean():.1f}% | 전 tick nearest<=latest {100*(N<=L).mean():.0f}%")


if __name__ == "__main__":
    main()
