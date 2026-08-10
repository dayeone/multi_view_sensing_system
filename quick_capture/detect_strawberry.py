#!/usr/bin/env python3
"""
detect_strawberry.py - 캡처된 세션 이미지에서 딸기(익음/덜익음) 검출

기존 학습 가중치(HuggingFace shivamjha98/yolo11s-strawberry-detection, MIT)를
가져와 GPU 추론한다. 클래스: Ripe / Unripe.

사용법:
  python3 detect_strawberry.py --session ../quick_capture_data/session_20260526_160446
  python3 detect_strawberry.py --input <폴더 또는 이미지> --conf 0.3

출력:
  <out>/                       # 기본: 입력 세션명 기반 detect_out_<name>/
    cam{N}/*.jpg               # 검출 박스가 그려진 주석 이미지 (원본 구조 보존)
    detections.csv             # image,cam,class,conf,x1,y1,x2,y2 (검출 1건당 1행)
    summary.txt                # 전체/클래스별 집계
"""
import argparse
import csv
import os
import sys
from pathlib import Path

from ultralytics import YOLO

# 기본 경로
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WEIGHTS = SCRIPT_DIR / "models" / "strawberry_yolo11s.pt"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def collect_images(input_path: Path) -> list[Path]:
    """입력 경로 하위(uploaded/ 등 포함)의 모든 이미지를 수집한다."""
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in IMG_EXTS else []
    return sorted(
        p for p in input_path.rglob("*") if p.suffix.lower() in IMG_EXTS
    )


def cam_label(img_path: Path, input_root: Path) -> str:
    """경로에서 cam{N} 세그먼트를 추출한다. 없으면 'unknown'."""
    for part in img_path.relative_to(input_root).parts:
        if part.startswith("cam"):
            return part
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="딸기 익음/덜익음 검출")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--session", type=str, help="세션 폴더 경로")
    src.add_argument("--input", type=str, help="임의의 폴더 또는 단일 이미지")
    parser.add_argument("--weights", type=str, default=str(DEFAULT_WEIGHTS),
                        help=f"가중치 .pt (기본 {DEFAULT_WEIGHTS.name})")
    parser.add_argument("--conf", type=float, default=0.25,
                        help="신뢰도 임계값 (기본 0.25)")
    parser.add_argument("--device", type=str, default=None,
                        help="cuda / cpu (기본: 자동)")
    parser.add_argument("--imgsz", type=int, default=640, help="추론 입력 크기")
    parser.add_argument("--out", type=str, default=None, help="출력 폴더")
    args = parser.parse_args()

    input_root = Path(args.session or args.input).resolve()
    if not input_root.exists():
        print(f"[ERROR] 입력 경로 없음: {input_root}")
        return 1

    weights = Path(args.weights)
    if not weights.exists():
        print(f"[ERROR] 가중치 없음: {weights}")
        return 1

    images = collect_images(input_root)
    if not images:
        print(f"[ERROR] 이미지를 찾지 못함: {input_root}")
        return 1

    out_dir = Path(args.out) if args.out else (
        SCRIPT_DIR / f"detect_out_{input_root.name}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 56)
    print(f"가중치   : {weights}")
    print(f"입력     : {input_root}  ({len(images)}장)")
    print(f"출력     : {out_dir}")
    print(f"conf/임계: {args.conf}  imgsz: {args.imgsz}")
    print("=" * 56)

    model = YOLO(str(weights))
    names = model.names  # {0: 'Ripe', 1: 'Unripe'} 형태
    print(f"클래스   : {names}")
    print(f"디바이스 : {args.device or 'auto'}\n")

    csv_path = out_dir / "detections.csv"
    class_counts: dict[str, int] = {}
    images_with_det = 0
    total_det = 0

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["image", "cam", "class", "conf", "x1", "y1", "x2", "y2"])

        # stream=True 로 1장씩 처리 → 메모리 절약 (503장+ 대응)
        results = model.predict(
            source=[str(p) for p in images],
            conf=args.conf,
            imgsz=args.imgsz,
            device=args.device,
            stream=True,
            verbose=False,
        )

        for img_path, res in zip(images, results):
            cam = cam_label(img_path, input_root)
            boxes = res.boxes
            n = 0 if boxes is None else len(boxes)
            if n > 0:
                images_with_det += 1
                total_det += n
                for b in boxes:
                    cls_id = int(b.cls.item())
                    cls_name = names.get(cls_id, str(cls_id))
                    conf = float(b.conf.item())
                    x1, y1, x2, y2 = (round(v, 1) for v in b.xyxy[0].tolist())
                    class_counts[cls_name] = class_counts.get(cls_name, 0) + 1
                    writer.writerow([img_path.name, cam, cls_name,
                                     f"{conf:.3f}", x1, y1, x2, y2])

            # 주석 이미지 저장 (원본 cam 구조 보존)
            cam_out = out_dir / cam
            cam_out.mkdir(parents=True, exist_ok=True)
            res.save(filename=str(cam_out / img_path.name))

    # 집계 출력
    summary = [
        "=" * 56,
        f"처리 이미지       : {len(images)}",
        f"딸기 검출된 이미지: {images_with_det} "
        f"({100 * images_with_det / len(images):.1f}%)",
        f"총 검출 박스      : {total_det}",
        "클래스별 검출      :",
    ]
    for cls_name, cnt in sorted(class_counts.items(), key=lambda x: -x[1]):
        summary.append(f"  - {cls_name:<10}: {cnt}")
    summary += [
        "=" * 56,
        f"주석 이미지 : {out_dir}",
        f"검출 CSV    : {csv_path}",
    ]
    text = "\n".join(summary)
    print("\n" + text)
    (out_dir / "summary.txt").write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
