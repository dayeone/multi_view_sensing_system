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
import subprocess
import sys
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
    ap.add_argument("--patience", type=int, default=100,
                    help="이 횟수만큼 개선이 없으면 조기 종료 (기본 100 = 사실상 끄기)")
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
        patience=args.patience,
        project=str(SCRIPT_DIR / "runs" / "detect"),
        name=args.name,
    )

    # 결과 폴더에 **입력 기록**을 같이 남긴다.
    # ultralytics 의 args.yaml 은 하이퍼파라미터만 적고 데이터 구성(출처·클래스별 장수)은
    # 남기지 않아서, 나중에 "이 모델이 뭘 보고 배웠나"를 확인할 방법이 없어진다.
    save_dir = Path(getattr(model.trainer, "save_dir", SCRIPT_DIR / "runs" / "detect" / args.name))
    try:
        subprocess.run([sys.executable, str(SCRIPT_DIR / "dataset_report.py"),
                        "--run", str(save_dir)], check=True)
    except Exception as e:  # 기록 실패가 학습 결과를 버리게 하지는 않는다
        print(f"[경고] 입력 기록 생성 실패: {e}")

    print(f"\n완료. best.pt: {save_dir / 'weights' / 'best.pt'}")
    print(f"      입력 기록: {save_dir / 'dataset_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
