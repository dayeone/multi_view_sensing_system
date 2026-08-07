#!/usr/bin/env python3
"""
plot_results.py - 학습 결과(results.csv)를 발표용 그래프로 렌더링

ultralytics가 만드는 results.png는 10개 패널이 빽빽해 발표에 쓰기 어렵다.
이 스크립트는 (1) 검증 성능 지표, (2) 손실 3종(train/val)을 읽기 쉬운 형태로 그린다.

사용법:
  python3 plot_results.py                                   # disease_v2 기본
  python3 plot_results.py --run runs/detect/disease_b_v1 --out v1_curves.png
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

SCRIPT_DIR = Path(__file__).resolve().parent

# 검증 통과 팔레트 (dataviz 기준 팔레트, light surface #fcfcfb)
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e3e2df"


def use_korean_font() -> None:
    """한글 폰트가 있으면 지정(없으면 기본 폰트 유지)."""
    for name in ("Noto Sans CJK KR", "Noto Sans CJK JP", "NanumGothic"):
        try:
            font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams["font.family"] = name
            break
        except Exception:
            continue
    plt.rcParams["axes.unicode_minus"] = False


def load(run: Path) -> dict[str, list[float]]:
    rows = list(csv.DictReader(open(run / "results.csv")))
    cols = {k.strip(): [float(r[k]) for r in rows] for k in rows[0]}
    return cols


def style(ax) -> None:
    """공통 축 스타일: 그리드·축은 뒤로 물리고 마크를 앞세운다."""
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9, length=0)


def main() -> int:
    ap = argparse.ArgumentParser(description="학습 결과 그래프 렌더링")
    ap.add_argument("--run", default=str(SCRIPT_DIR / "runs/detect/disease_v2"))
    ap.add_argument("--out", default=None, help="출력 PNG 경로")
    ap.add_argument("--title", default="딸기 병해 검출 v2 — AI Hub 데이터 학습 결과")
    args = ap.parse_args()

    run = Path(args.run)
    if not (run / "results.csv").exists():
        print(f"[오류] results.csv 없음: {run}")
        return 1
    use_korean_font()
    c = load(run)
    ep = c["epoch"]
    out = Path(args.out) if args.out else run / "training_curves.png"

    fig = plt.figure(figsize=(12, 7.5), facecolor=SURFACE)
    gs = fig.add_gridspec(2, 3, height_ratios=[1.35, 1], hspace=0.42, wspace=0.28,
                          left=0.07, right=0.93, top=0.87, bottom=0.09)

    # ── 상단: 검증 성능 지표 (모두 0~1 척도라 한 축에 둘 수 있음) ──────────────
    ax = fig.add_subplot(gs[0, :])
    style(ax)
    series = [
        ("Precision",  c["metrics/precision(B)"], BLUE),
        ("Recall",     c["metrics/recall(B)"],    ORANGE),
        ("mAP50",      c["metrics/mAP50(B)"],     AQUA),
        ("mAP50-95",   c["metrics/mAP50-95(B)"],  YELLOW),
    ]
    for _, ys, col in series:
        ax.plot(ep, ys, color=col, linewidth=2, solid_capstyle="round")
    ax.set_xlim(min(ep), max(ep) * 1.16)
    y_top = max(max(s[1]) for s in series) * 1.25
    ax.set_ylim(0, y_top)

    # 직접 라벨(relief rule). 끝값이 붙어 있으면 겹치므로 최소 간격으로 밀어낸다.
    gap = y_top * 0.052
    items = sorted(((s[1][-1], s[0], s[2]) for s in series), key=lambda t: t[0])
    placed: list[float] = []
    for y, name, col in items:
        y_lab = y if not placed else max(y, placed[-1] + gap)
        placed.append(y_lab)
        # 라벨을 밀어낸 경우 원래 선 끝과 이어주는 얇은 안내선
        if abs(y_lab - y) > 1e-9:
            ax.plot([ep[-1], max(ep) * 1.035], [y, y_lab], color=col,
                    linewidth=0.8, alpha=0.55, clip_on=False)
        ax.annotate(f"{name}  {y:.3f}", xy=(max(ep) * 1.04, y_lab),
                    va="center", fontsize=9.5, color=INK, fontweight="medium",
                    annotation_clip=False)
    ax.set_xlabel("epoch", color=INK_2, fontsize=9.5)
    ax.set_title("검증 성능 지표 (높을수록 좋음)", color=INK, fontsize=12,
                 fontweight="bold", loc="left", pad=10)

    # ── 하단: 손실 3종 (지표와 척도가 달라 별도 패널로 분리) ────────────────────
    for i, (key, label) in enumerate([("box", "box_loss (박스 위치)"),
                                      ("cls", "cls_loss (병해 분류)"),
                                      ("dfl", "dfl_loss (박스 경계)")]):
        axl = fig.add_subplot(gs[1, i])
        style(axl)
        axl.plot(ep, c[f"train/{key}_loss"], color=BLUE, linewidth=2, label="train")
        axl.plot(ep, c[f"val/{key}_loss"], color=ORANGE, linewidth=2, label="val")
        axl.set_title(label, color=INK, fontsize=10, loc="left", pad=6)
        axl.set_xlabel("epoch", color=INK_2, fontsize=9)
        if i == 0:
            axl.legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="upper right")

    fig.suptitle(args.title, color=INK, fontsize=14, fontweight="bold",
                 x=0.07, ha="left", y=0.965)
    fig.text(0.07, 0.925,
             f"YOLO11s · {int(max(ep))} epoch · 학습 {56911:,}장 / 검증 {8268:,}장 "
             f"· 손실은 낮을수록 좋음(범위 제한 없음)",
             color=INK_2, fontsize=9.5, ha="left")

    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"저장 완료: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
