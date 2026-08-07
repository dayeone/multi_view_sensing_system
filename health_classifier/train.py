#!/usr/bin/env python3
"""
train.py - 딸기 병해 검출기 학습 (구조 B, v1)

COCO 사전학습 YOLO11 을 전북대 병해 데이터(단일 'disease' 클래스)로 미세조정한다.
학습 스택은 conda `strawberry` 환경(ultralytics, torch+CUDA)을 사용한다.

준비:
  python3 datasets/download_datasets.py --only jbnu_disease
  python3 datasets/build_yolo_detect.py        # datasets/yolo_disease/data.yaml 생성

학습:
  conda activate strawberry
  python3 train.py                             # 기본값으로 학습
  python3 train.py --epochs 50 --model yolo11n.pt --batch 8

결과:
  runs/detect/<name>/weights/best.pt           # 최종 검출기
"""
from __future__ import annotations

import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA = SCRIPT_DIR / "datasets" / "yolo_disease" / "data.yaml"


def main() -> int:
    ap = argparse.ArgumentParser(description="딸기 병해 검출기 학습(구조 B)")
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="data.yaml 경로")
    ap.add_argument("--model", default="yolo11s.pt",
                    help="사전학습 가중치 (yolo11n/s/m.pt). 최초 1회 자동 다운로드")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default=None, help="0 / cpu (기본: 자동)")
    ap.add_argument("--name", default="disease_b_v1", help="실행 이름")
    args = ap.parse_args()

    if not Path(args.data).exists():
        print(f"[오류] {args.data} 없음. 먼저 build_yolo_detect.py 실행")
        return 1

    from ultralytics import YOLO

    print(f"모델   : {args.model}")
    print(f"데이터 : {args.data}")
    print(f"epochs={args.epochs} imgsz={args.imgsz} batch={args.batch} device={args.device or 'auto'}")

    model = YOLO(args.model)
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=str(SCRIPT_DIR / "runs" / "detect"),
        name=args.name,
    )
    print(f"\n완료. best.pt: {SCRIPT_DIR / 'runs' / 'detect' / args.name / 'weights' / 'best.pt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
