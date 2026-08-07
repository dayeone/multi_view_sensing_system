#!/usr/bin/env python3
"""
build_binary.py - 원본 데이터셋 → 정상/이상(normal/abnormal) 이진 YOLO-cls 구조 생성

datasets/raw/<key>/ 의 원본을 읽어 각 이미지를 normal/abnormal 로 재라벨하고
datasets/binary/{split}/{normal,abnormal}/ 로 복사한다. (ultralytics YOLO11-cls 입력 형식)

라벨 결정(원본 레이아웃 자동 감지):
  - labelme 모드: 이미지 옆 <name>.json 의 shapes[].label 을 읽음
      · 라벨이 전부 정상 키워드(healthy/normal/health)이거나 shapes 가 비면 → normal
      · 그 외 병해/이상 라벨이 하나라도 있으면 → abnormal
  - folder  모드: 이미지의 상위 폴더명으로 판정 (정상 키워드 포함 → normal, 그 외 abnormal)
  - 두 형식이 섞이면 이미지별로 각각 처리

split:
  - 원본에 train/val/test 폴더가 있으면 보존 (test 는 val 로 합침: 베이스라인 단순화)
  - 없으면 파일명 해시로 결정적(80/20) 분할 → 재현 가능

사용법:
  python3 build_binary.py                       # raw 전체 → binary
  python3 build_binary.py --only jbnu_disease
  python3 build_binary.py --val-ratio 0.2 --clean
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_DIR = SCRIPT_DIR / "raw"
OUT_DIR = SCRIPT_DIR / "binary"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
SPLIT_DIRS = {"train", "val", "valid", "test"}

# 정상으로 볼 키워드(소문자 부분일치). 그 외 모든 라벨/폴더는 이상으로 간주.
NORMAL_KEYWORDS = ("healthy", "health", "normal", "정상")

# raw 하위에서 제외할 데이터셋 폴더(자체 검증셋 등은 학습에 섞지 않음)
SKIP_KEYS = {"_zips", "own_val"}


def is_normal_label(label: str) -> bool:
    low = label.lower()
    return any(k in low for k in NORMAL_KEYWORDS)


def label_from_labelme(json_path: Path) -> str | None:
    """labelme json → 'normal'/'abnormal'. 파싱 실패 시 None."""
    try:
        data = json.loads(json_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    shapes = data.get("shapes", [])
    labels = [s.get("label", "") for s in shapes]
    if not labels:
        return "normal"  # 주석 없는 이미지 = 병징 없음으로 간주
    return "normal" if all(is_normal_label(l) for l in labels) else "abnormal"


def split_of(img_path: Path, raw_root: Path, val_ratio: float) -> str:
    """경로에 train/val/test 가 있으면 사용, 없으면 파일명 해시로 결정적 분할."""
    parts = {p.lower() for p in img_path.relative_to(raw_root).parts}
    if "train" in parts:
        return "train"
    if parts & {"val", "valid", "test"}:
        return "val"
    # 결정적 분할: 파일명 md5 → [0,1) 버킷
    h = hashlib.md5(img_path.name.encode()).hexdigest()
    frac = int(h[:8], 16) / 0xFFFFFFFF
    return "val" if frac < val_ratio else "train"


def process_key(key: str, val_ratio: float, counts: Counter) -> None:
    src = RAW_DIR / key
    if not src.exists():
        print(f"[스킵] raw/{key} 없음")
        return

    imgs = [p for p in src.rglob("*") if p.suffix.lower() in IMG_EXTS]
    if not imgs:
        print(f"[스킵] raw/{key} 이미지 없음")
        return

    print(f"[처리] {key}: 이미지 {len(imgs)}장")
    for img in imgs:
        # 라벨 결정: 옆에 json 있으면 labelme, 없으면 폴더명
        sidecar = img.with_suffix(".json")
        if sidecar.exists():
            label = label_from_labelme(sidecar)
        else:
            label = "normal" if is_normal_label(img.parent.name) else "abnormal"
        if label is None:
            counts[(key, "parse_fail")] += 1
            continue

        split = split_of(img, src, val_ratio)
        dest_dir = OUT_DIR / split / label
        dest_dir.mkdir(parents=True, exist_ok=True)
        # 데이터셋 접두어로 파일명 충돌 방지
        shutil.copy2(img, dest_dir / f"{key}__{img.name}")
        counts[(split, label)] += 1


def main() -> int:
    ap = argparse.ArgumentParser(description="정상/이상 이진 YOLO-cls 구조 빌드")
    ap.add_argument("--only", help="특정 raw/<key> 만 처리")
    ap.add_argument("--val-ratio", type=float, default=0.2,
                    help="split 없는 데이터셋의 val 비율 (기본 0.2)")
    ap.add_argument("--clean", action="store_true", help="기존 binary/ 삭제 후 재생성")
    args = ap.parse_args()

    if args.clean and OUT_DIR.exists():
        print(f"[정리] {OUT_DIR} 삭제")
        shutil.rmtree(OUT_DIR)

    if args.only:
        keys = [args.only]
    else:
        keys = [p.name for p in RAW_DIR.iterdir()
                if p.is_dir() and p.name not in SKIP_KEYS] if RAW_DIR.exists() else []
    if not keys:
        print(f"[오류] 처리할 raw 데이터셋 없음. 먼저 download_datasets.py 실행.")
        return 1

    counts: Counter = Counter()
    for key in keys:
        process_key(key, args.val_ratio, counts)

    # 리포트
    print("=" * 56)
    print("클래스 분포 (split / label : 장수)")
    total = 0
    for split in ("train", "val"):
        for label in ("normal", "abnormal"):
            n = counts[(split, label)]
            total += n
            print(f"  {split:<6} {label:<9}: {n:>6}")
    fails = sum(v for (k, tag), v in counts.items() if tag == "parse_fail")
    if fails:
        print(f"  파싱 실패        : {fails}")
    print(f"  총합             : {total}")
    print("=" * 56)
    print(f"출력: {OUT_DIR}")
    if total == 0:
        print("[경고] 생성된 샘플 0. raw 레이아웃을 확인하라(labelme json / 클래스 폴더).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
