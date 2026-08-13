#!/usr/bin/env python3
"""학습에 들어간 데이터 구성을 파일로 남긴다.

ultralytics 의 args.yaml 은 하이퍼파라미터(epochs, batch, lr 등)만 기록하고
**데이터가 어디서 왔고 클래스별로 몇 장인지는 남기지 않는다.**
나중에 "이 모델이 뭘 보고 배웠나"를 확인할 방법이 없어지므로 따로 기록한다.

사용:
  python3 dataset_report.py --run runs/detect/disease_v2
  python3 dataset_report.py --data datasets/yolo_v3/data.yaml --out 어디에.md

출력: <run>/dataset_report.md  (또는 --out 경로)
"""
from __future__ import annotations

import argparse
import collections
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# 파일 이름으로 원본 출처를 되찾는다. 데이터셋마다 이름 규칙이 다르다.
#   yolo_aihub   (v2)  : blight_train_000000.jpg      — 변환 시 새로 붙인 이름
#   yolo_aihub16 (모델B): 딸기_설향_역병_01_001_….jpg   — 원본 이름 그대로
#   yolo_jbnu7   (모델A): angular_leafspot100.jpg      — 원본 이름 그대로
#   배경 이미지          : bg_… 접두사
AIHUB_KEY = [("정상", "정상"), ("역병", "역병"), ("시들음", "시들음병"),
             ("잎끝마름", "잎끝마름"), ("황화", "황화")]
AIHUB_PRE = {"normal": "정상", "blight": "역병", "wilt": "시들음병",
             "tipburn": "잎끝마름", "yellowing": "황화"}
JBNU_KEY = [("angular_leafspot", "각반병"), ("leaf_spot", "점무늬병"),
            ("powdery_mildew_leaf", "흰가루병(잎)"), ("powdery_mildew_fruit", "흰가루병(과실)"),
            ("gray_mold", "잿빛곰팡이병"), ("blossom_blight", "꽃마름병"),
            ("anthracnose", "탄저병")]


def origin_of(stem: str) -> tuple[str, str]:
    """파일 이름 → (출처, 원본 클래스)"""
    if stem.startswith("bg_"):
        s = stem[3:]
        for k, kor in AIHUB_KEY:
            if k in s:
                return "AI Hub 허브1", f"{kor} (배경)"
        return "배경 샘플", "정상"
    if stem.startswith("jbnu_"):
        stem = stem[5:]
    for k, kor in AIHUB_KEY:
        if k in stem:
            return "AI Hub 허브1", kor
    pre = stem.split("_")[0]
    if pre in AIHUB_PRE:
        return "AI Hub 허브1", AIHUB_PRE[pre]
    low = stem.lower()
    for k, kor in sorted(JBNU_KEY, key=lambda x: -len(x[0])):
        if low.startswith(k):
            return "전북대 (Kaggle)", kor
    return "(알 수 없음)", stem.split("_")[0]


def scan(root: Path, split: str) -> tuple[collections.Counter, collections.Counter,
                                           collections.Counter]:
    """(출처별 이미지 수, 클래스별 박스 수, 출처별 박스 수)"""
    lab = root / "labels" / split
    imgs, boxes, by_origin = collections.Counter(), collections.Counter(), collections.Counter()
    if not lab.is_dir():
        return imgs, boxes, by_origin
    for f in lab.glob("*.txt"):
        key = origin_of(f.stem)
        imgs[key] += 1
        for ln in f.read_text().splitlines():
            if ln.strip():
                boxes[int(ln.split()[0])] += 1
                by_origin[key] += 1
    return imgs, boxes, by_origin


def read_yaml_names(data_yaml: Path) -> tuple[Path, list[str]]:
    """의존성 없이 data.yaml 의 path 와 names 만 읽는다."""
    root, names, in_names = None, [], False
    for ln in data_yaml.read_text().splitlines():
        s = ln.strip()
        if s.startswith("path:"):
            root = Path(s.split(":", 1)[1].strip())
        elif s.startswith("names:"):
            in_names = True
        elif in_names and s and s[0].isdigit():
            names.append(s.split(":", 1)[1].strip())
        elif in_names and s and not s[0].isdigit():
            in_names = False
    return (root or data_yaml.parent), names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="runs/detect/<이름> 폴더")
    ap.add_argument("--data", default=None, help="data.yaml 경로 (--run 없을 때)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.run:
        run = Path(args.run)
        line = next((l for l in (run / "args.yaml").read_text().splitlines()
                     if l.startswith("data:")), None)
        data_yaml = Path(line.split(":", 1)[1].strip())
        if not data_yaml.is_absolute():
            data_yaml = SCRIPT_DIR / data_yaml
        hyper = {k: v for k, v in (l.split(":", 1) for l in
                                   (run / "args.yaml").read_text().splitlines() if ":" in l)}
        out = Path(args.out) if args.out else run / "dataset_report.md"
        title = run.name
    else:
        data_yaml = Path(args.data)
        hyper, out, title = {}, Path(args.out or "dataset_report.md"), data_yaml.parent.name

    root, names = read_yaml_names(data_yaml)
    L = [f"# {title} — 학습 입력 기록", "",
         f"- data.yaml : `{data_yaml}`",
         f"- 데이터 위치 : `{root}`"]
    for k in ("model", "epochs", "imgsz", "batch", "patience", "optimizer", "lr0", "seed"):
        if k in hyper:
            L.append(f"- {k} : {hyper[k].strip()}")

    for split in ("train", "val", "test"):
        imgs, boxes, by_origin = scan(root, split)
        if not imgs:
            continue
        L += ["", f"## {split}  —  이미지 {sum(imgs.values()):,}장 / 박스 {sum(boxes.values()):,}개", "",
              "### 출처별", "", "| 출처 | 원본 클래스 | 이미지 | 박스 |", "|---|---|---|---|"]
        for (src, kor), n in imgs.most_common():
            L.append(f"| {src} | {kor} | {n:,} | {by_origin[(src, kor)]:,} |")
        L += ["", "### 학습 클래스별 박스", "", "| # | 클래스 | 박스 |", "|---|---|---|"]
        for i, nm in enumerate(names):
            L.append(f"| {i} | `{nm}` | {boxes.get(i, 0):,} |")
        n_empty = sum(1 for f in (root / "labels" / split).glob("*.txt")
                      if not f.read_text().strip())
        L.append("")
        L.append(f"- 박스 없는 이미지(배경 샘플) : {n_empty:,}장")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
