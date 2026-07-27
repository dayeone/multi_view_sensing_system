#!/usr/bin/env python3
"""
classify_strawberry.py - 학습된 병해 검출기로 딸기 병해 "유무" 판정 (구조 B 추론)

train.py 로 만든 검출 모델(best.pt)을 실증 사진에 적용한다. 사진을 한 장씩 훑어
병든 부위에 박스를 치고, 박스가 하나라도 있으면 "이상(병해)", 없으면 "정상"으로 판정한다.

배포 대상: NUC2(Ranger mini). 상대경로 + device 자동이라 NUC1/NUC2 어디서도 그대로 실행.

사용법:
  # NUC1(학습 직후 검증)
  python3 classify_strawberry.py --input <딸기사진폴더>
  # NUC2(배포)
  python3 classify_strawberry.py --weights models/disease_b_v1.pt --input <폴더> --conf 0.3

출력:
  <out>/
    <cam>/*.jpg        # 병든 부위 박스가 그려진 주석 이미지(원본 cam 구조 보존)
    verdicts.csv       # image,cam,verdict,n_disease,max_conf (이미지 1장당 1행)
    summary.txt        # 전체/정상/이상 집계
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from ultralytics import YOLO

SCRIPT_DIR = Path(__file__).resolve().parent
# 기본 가중치: NUC1 학습 산출물 위치. NUC2에서는 --weights 로 지정.
DEFAULT_WEIGHTS = SCRIPT_DIR / "runs" / "detect" / "disease_b_v1" / "weights" / "best.pt"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def collect_images(input_path: Path) -> list[Path]:
    """입력 경로 하위의 모든 이미지를 수집한다."""
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in IMG_EXTS else []
    return sorted(p for p in input_path.rglob("*") if p.suffix.lower() in IMG_EXTS)


def cam_label(img_path: Path, input_root: Path) -> str:
    """경로에서 cam{N} 세그먼트를 추출한다. 없으면 'unknown'."""
    for part in img_path.relative_to(input_root).parts:
        if part.startswith("cam"):
            return part
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="딸기 병해 유무 판정(구조 B 추론)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--session", type=str, help="세션 폴더 경로")
    src.add_argument("--input", type=str, help="임의의 폴더 또는 단일 이미지")
    parser.add_argument("--weights", type=str, default=str(DEFAULT_WEIGHTS),
                        help=f"검출 가중치 .pt (기본 {DEFAULT_WEIGHTS})")
    parser.add_argument("--conf", type=float, default=0.25,
                        help="병해로 판정할 신뢰도 임계값 (기본 0.25). 오탐 많으면 올릴 것")
    parser.add_argument("--device", type=str, default=None, help="cuda / cpu (기본: 자동)")
    parser.add_argument("--imgsz", type=int, default=640, help="추론 입력 크기")
    parser.add_argument("--out", type=str, default=None, help="출력 폴더")
    args = parser.parse_args()

    input_root = Path(args.session or args.input).resolve()
    if not input_root.exists():
        print(f"[ERROR] 입력 경로 없음: {input_root}")
        return 1

    weights = Path(args.weights)
    if not weights.exists():
        print(f"[ERROR] 가중치 없음: {weights}\n  학습(train.py) 후 생성되거나, NUC2에선 --weights 로 지정")
        return 1

    images = collect_images(input_root)
    if not images:
        print(f"[ERROR] 이미지를 찾지 못함: {input_root}")
        return 1

    out_dir = Path(args.out) if args.out else (SCRIPT_DIR / f"classify_out_{input_root.name}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 56)
    print(f"가중치   : {weights}")
    print(f"입력     : {input_root}  ({len(images)}장)")
    print(f"출력     : {out_dir}")
    print(f"conf임계 : {args.conf}  imgsz: {args.imgsz}  device: {args.device or 'auto'}")
    print("=" * 56)

    model = YOLO(str(weights))

    csv_path = out_dir / "verdicts.csv"
    abnormal = 0
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["image", "cam", "verdict", "n_disease", "max_conf"])

        # stream=True 로 1장씩 처리(대량 세션 대응)
        results = model.predict(
            source=[str(p) for p in images],
            conf=args.conf, imgsz=args.imgsz, device=args.device,
            stream=True, verbose=False,
        )
        for img_path, res in zip(images, results):
            cam = cam_label(img_path, input_root)
            boxes = res.boxes
            n = 0 if boxes is None else len(boxes)
            verdict = "abnormal" if n > 0 else "normal"
            max_conf = float(boxes.conf.max().item()) if n > 0 else 0.0
            if n > 0:
                abnormal += 1
            writer.writerow([img_path.name, cam, verdict, n, f"{max_conf:.3f}"])

            cam_out = out_dir / cam
            cam_out.mkdir(parents=True, exist_ok=True)
            res.save(filename=str(cam_out / img_path.name))

    normal = len(images) - abnormal
    text = "\n".join([
        "=" * 56,
        f"처리 이미지 : {len(images)}",
        f"이상(병해)  : {abnormal} ({100 * abnormal / len(images):.1f}%)",
        f"정상        : {normal} ({100 * normal / len(images):.1f}%)",
        "=" * 56,
        f"판정 CSV    : {csv_path}",
        f"주석 이미지 : {out_dir}",
    ])
    print("\n" + text)
    (out_dir / "summary.txt").write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
