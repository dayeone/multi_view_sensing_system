#!/usr/bin/env python3
"""학습 진행 상황을 한눈에 보여준다.

ultralytics 의 results.csv 는 열이 20개라 그대로는 읽기 어렵다. 여기서는
숫자를 나열하는 대신 **얼마나 남았는지 / 오르고 있는지**를 먼저 보여준다.

사용:
  python3 watch_train.py                    # 최신 학습
  python3 watch_train.py --name model_A_jbnu7
  python3 watch_train.py --full             # 상세 표(정밀도·재현율·손실까지)
  python3 watch_train.py --cols             # 지표 뜻 설명
  watch -n 60 python3 watch_train.py        # 1분마다 갱신
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import time
import unicodedata
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RUNS = SCRIPT_DIR / "runs" / "detect"


def w(s: str) -> int:
    """화면상 폭. 한글·한자는 두 칸을 차지한다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, n: int, right: bool = False) -> str:
    gap = " " * max(0, n - w(s))
    return gap + s if right else s + gap


def hms(sec: float) -> str:
    h, m = int(sec // 3600), int(sec % 3600 // 60)
    if h:
        return f"{h}시간 {m}분"
    return f"{m}분" if m else f"{int(sec)}초"


def bar(v: float, lo: float, hi: float, width: int = 22) -> str:
    if hi <= lo:
        return "░" * width
    n = round((v - lo) / (hi - lo) * width)
    return "█" * n + "░" * (width - n)


def finished(run: Path) -> str | None:
    """학습이 끝났으면 이유를 돌려준다. 아직이면 None.

    판단 근거 두 가지.
      1) results.csv 의 epoch 수가 args.yaml 의 목표치에 도달
      2) weights/last.pt 가 한동안 갱신되지 않음 (조기 종료 또는 중단)
         → epoch 하나 도는 시간의 3배를 넘게 조용하면 끝난 것으로 본다.
    """
    csv_path = run / "results.csv"
    if not csv_path.exists():
        return None
    rows = list(csv.DictReader(csv_path.open()))
    if not rows:
        return None
    done = int(float(rows[-1]["epoch"]))
    per = float(rows[-1]["time"]) / done

    a = run / "args.yaml"
    if a.exists():
        for ln in a.read_text().splitlines():
            if ln.startswith("epochs:") and done >= int(ln.split(":")[1].strip()):
                return "목표 epoch 도달"

    last = run / "weights" / "last.pt"
    if last.exists() and time.time() - last.stat().st_mtime > max(per * 3, 180):
        return "가중치가 갱신되지 않음 (조기 종료 또는 중단)"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=None, help="학습 이름 (기본: 가장 최근)")
    ap.add_argument("--last", type=int, default=10, help="최근 몇 epoch")
    ap.add_argument("--full", action="store_true", help="정밀도·재현율·손실까지 표로")
    ap.add_argument("--cols", action="store_true", help="지표 뜻 설명")
    ap.add_argument("--follow", "-f", nargs="?", type=int, const=60, default=None,
                    metavar="초", help="자동 갱신. 학습이 끝나면 스스로 종료 (기본 60초)")
    args = ap.parse_args()

    if args.cols:
        print("""
  mAP50      종합 점수. 박스가 정답과 절반 이상 겹치면 맞다고 침. 0~1
  mAP50-95   더 엄격한 종합 점수. 박스가 정확히 맞아야 점수를 줌
  정밀도     병해라고 판정한 것 중 실제로 병해였던 비율 (오탐이 적을수록 높음)
  재현율     실제 병해 중 모델이 찾아낸 비율 (놓침이 적을수록 높음)
  위치오차   박스 위치가 얼마나 틀렸는지. 낮을수록 좋음
  분류오차   종류를 얼마나 틀렸는지. 낮을수록 좋음
""")
        return 0

    if not RUNS.is_dir():
        print("학습 기록이 없습니다.")
        return 1
    if args.name:
        run = RUNS / args.name
    else:
        cands = [d for d in RUNS.iterdir() if (d / "results.csv").exists()]
        if not cands:
            print("학습 기록이 없습니다.")
            return 1
        run = max(cands, key=lambda d: (d / "results.csv").stat().st_mtime)

    if args.follow:
        while True:
            subprocess.run(["clear"], check=False)
            render(run, args)
            why = finished(run)
            if why:
                print(f"\n  ■ 학습 종료 — {why}")
                print(f"  결과: {run}")
                return 0
            print(f"\n  {args.follow}초마다 갱신 중… (Ctrl+C 로 중단)")
            time.sleep(args.follow)
    return render(run, args)


def render(run: Path, args) -> int:
    csv_path = run / "results.csv"
    if not csv_path.exists():
        print(f"■ {run.name}\n  아직 1 epoch이 끝나지 않았습니다. 잠시 후 다시 보세요.")
        return 0
    rows = list(csv.DictReader(csv_path.open()))
    if not rows:
        print("아직 기록이 없습니다.")
        return 0

    def col(key: str) -> str:
        return next(c for c in rows[0] if key in c)

    kmap = col("mAP50(B)")
    done = int(float(rows[-1]["epoch"]))
    elapsed = float(rows[-1]["time"])
    per = elapsed / done

    # 목표 epoch 수는 args.yaml 에 적혀 있다
    total = None
    a = run / "args.yaml"
    if a.exists():
        for ln in a.read_text().splitlines():
            if ln.startswith("epochs:"):
                total = int(ln.split(":")[1].strip())

    best = max(rows, key=lambda r: float(r[kmap]))
    best_e = int(float(best["epoch"]))

    # ── 머리말 ──────────────────────────────────────────────
    head = f"■ {run.name}"
    if total:
        pct = done / total * 100
        left = (total - done) * per
        print(f"{head}     epoch {done}/{total}  ({pct:.0f}%)")
        print(f"  경과 {hms(elapsed)}   ·   남은 시간 약 {hms(left)}   ·   epoch당 {per:.0f}초")
    else:
        print(f"{head}     epoch {done} 완료")
        print(f"  경과 {hms(elapsed)}   ·   epoch당 {per:.0f}초")

    trend = ""
    if len(rows) >= 6:
        d = float(rows[-1][kmap]) - float(rows[-6][kmap])
        trend = ("오르는 중" if d > 0.002 else "정체" if d > -0.002 else "내려가는 중")
        trend = f"   ·   최근 5회 {d:+.3f} ({trend})"
    print(f"  최고 mAP50 {float(best[kmap]):.3f} (epoch {best_e}){trend}")
    print()

    view = rows[-args.last:]
    # 막대는 **보이는 구간** 기준으로 그린다. 전 구간 기준으로 그리면 후반부가
    # 전부 꽉 찬 막대가 되어 차이가 안 보인다. 눈금에 실제 값을 적어 두므로
    # 구간이 좁다는 것은 눈금으로 알 수 있다.
    vals = [float(r[kmap]) for r in view]
    lo, hi = min(vals), max(vals)

    if args.full:
        kmap95, kp, kr = col("mAP50-95(B)"), col("precision"), col("recall")
        kbox, kcls = col("train/box_loss"), col("train/cls_loss")
        hdr = ["epoch", "mAP50", "mAP50-95", "정밀도", "재현율", "위치오차", "분류오차"]
        widths = [7, 9, 10, 9, 9, 10, 10]
        print("  " + "".join(pad(h, n, True) for h, n in zip(hdr, widths)))
        print("  " + "─" * sum(widths))
        for r in view:
            e = int(float(r["epoch"]))
            cells = [str(e), f"{float(r[kmap]):.3f}", f"{float(r[kmap95]):.3f}",
                     f"{float(r[kp]):.3f}", f"{float(r[kr]):.3f}",
                     f"{float(r[kbox]):.3f}", f"{float(r[kcls]):.3f}"]
            mark = "  ← 최고" if e == best_e else ""
            print("  " + "".join(pad(c, n, True) for c, n in zip(cells, widths)) + mark)
    else:
        span = "  (변화 없음)" if hi - lo < 1e-6 else ""
        print(f"  epoch    mAP50   {lo:.3f} {'─' * 14} {hi:.3f}{span}")
        print("  " + "─" * 48)
        for r in view:
            e = int(float(r["epoch"]))
            v = float(r[kmap])
            mark = "  ← 최고" if e == best_e else ""
            print(f"  {e:>5}    {v:>5.3f}   {bar(v, lo, hi)}{mark}")
        print()
        print("  (--full 로 정밀도·재현율까지,  --cols 로 지표 설명)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
