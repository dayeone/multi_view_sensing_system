#!/usr/bin/env python3
"""
build_yolo_detect.py - 전북대 병해 데이터(labelme) → YOLO 검출 형식 변환 (구조 B, v1)

raw/jbnu_disease/{train,val,test}/ 의 <name>.jpg + <name>.json(labelme 폴리곤)을 읽어
YOLO 검출 학습용 구조로 변환한다.

v1 정책 (로우레벨: 병해 유무만):
  - 7개 병해 클래스를 모두 단일 클래스 0 = "disease" 로 통합
  - 폴리곤 → 외접 사각형(bbox) 으로 변환
  - 건강(healthy) 이미지: 박스 없는 "음성 샘플"(빈 라벨 파일)로 포함 → 오탐 억제 학습
  - 라벨(json) 없는 이미지(예: Severity Level 세트)는 건너뜀

출력:
  datasets/yolo_disease/
    images/{train,val}/*.jpg   (원본으로의 심볼릭 링크)
    labels/{train,val}/*.txt   ("0 xc yc w h", 정규화 좌표. 건강샘플은 빈 파일)
    data.yaml                  (ultralytics 학습 입력)

사용법:
  python3 build_yolo_detect.py                # test 셋은 val 로 합침(기본)
  python3 build_yolo_detect.py --keep-test    # test 를 별도 split 로 유지
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_JBNU = SCRIPT_DIR / "raw" / "jbnu_disease"
OUT_DIR = SCRIPT_DIR / "yolo_disease"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
NORMAL_KEYWORDS = ("healthy", "health", "normal", "정상")


def is_normal(label: str) -> bool:
    low = label.lower()
    return any(k in low for k in NORMAL_KEYWORDS)


def poly_to_bbox(points: list[list[float]], w: int, h: int) -> tuple[float, float, float, float]:
    """폴리곤 점들 → YOLO 정규화 bbox (xc, yc, bw, bh). 이미지 경계로 clip."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x1, x2 = max(0.0, min(xs)), min(float(w), max(xs))
    y1, y2 = max(0.0, min(ys)), min(float(h), max(ys))
    xc = (x1 + x2) / 2 / w
    yc = (y1 + y2) / 2 / h
    bw = (x2 - x1) / w
    bh = (y2 - y1) / h
    return xc, yc, bw, bh


def convert_split(src_split: Path, dst_split: str, counts: dict) -> None:
    """한 split 폴더의 이미지+json 을 YOLO 형식으로 변환."""
    img_out = OUT_DIR / "images" / dst_split
    lbl_out = OUT_DIR / "labels" / dst_split
    img_out.mkdir(parents=True, exist_ok=True)
    lbl_out.mkdir(parents=True, exist_ok=True)

    for img in sorted(p for p in src_split.rglob("*") if p.suffix.lower() in IMG_EXTS):
        js = img.with_suffix(".json")
        if not js.exists():
            counts["no_label_skip"] = counts.get("no_label_skip", 0) + 1
            continue
        try:
            data = json.loads(js.read_text())
        except (json.JSONDecodeError, OSError):
            counts["parse_fail"] = counts.get("parse_fail", 0) + 1
            continue

        w = int(data.get("imageWidth", 0)) or 1
        h = int(data.get("imageHeight", 0)) or 1
        lines: list[str] = []
        has_disease = False
        for shape in data.get("shapes", []):
            label = shape.get("label", "")
            pts = shape.get("points", [])
            if is_normal(label) or len(pts) < 3:
                continue  # 건강 라벨/무효 폴리곤은 박스로 넣지 않음
            xc, yc, bw, bh = poly_to_bbox(pts, w, h)
            if bw <= 0 or bh <= 0:
                continue
            lines.append(f"0 {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")
            has_disease = True

        # 이미지 심볼릭 링크(원본 중복 저장 방지) + 라벨 기록
        link = img_out / img.name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(img.resolve())
        (lbl_out / f"{img.stem}.txt").write_text("\n".join(lines))
        counts["disease_img" if has_disease else "normal_img"] = \
            counts.get("disease_img" if has_disease else "normal_img", 0) + 1
        counts["boxes"] = counts.get("boxes", 0) + len(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="전북대 병해 → YOLO 검출 형식(구조 B)")
    ap.add_argument("--keep-test", action="store_true", help="test 를 별도 split 로 유지")
    args = ap.parse_args()

    if not RAW_JBNU.exists():
        print(f"[오류] {RAW_JBNU} 없음. 먼저 download_datasets.py --only jbnu_disease 실행")
        return 1

    # split 매핑: 기본은 test→val 로 합쳐 평가셋 강화
    mapping = {"train": "train", "val": "val",
               "test": ("test" if args.keep_test else "val")}
    counts: dict = {}
    for src_name, dst in mapping.items():
        src = RAW_JBNU / src_name
        if src.exists():
            print(f"[변환] {src_name} → {dst}")
            convert_split(src, dst, counts)
        else:
            print(f"[스킵] {src_name} 폴더 없음")

    # data.yaml (ultralytics 입력)
    splits = {"train": "images/train", "val": "images/val"}
    if args.keep_test:
        splits["test"] = "images/test"
    yaml_lines = [f"path: {OUT_DIR}"]
    for k, v in splits.items():
        yaml_lines.append(f"{k}: {v}")
    yaml_lines += ["nc: 1", "names:", "  0: disease"]
    (OUT_DIR / "data.yaml").write_text("\n".join(yaml_lines) + "\n")

    # 리포트
    print("=" * 52)
    print(f"병해 이미지(박스 有) : {counts.get('disease_img', 0)}")
    print(f"정상 이미지(음성)    : {counts.get('normal_img', 0)}")
    print(f"총 박스 수           : {counts.get('boxes', 0)}")
    print(f"라벨없어 스킵        : {counts.get('no_label_skip', 0)}")
    print(f"파싱 실패            : {counts.get('parse_fail', 0)}")
    print("=" * 52)
    print(f"출력: {OUT_DIR}")
    print(f"data.yaml: {OUT_DIR / 'data.yaml'}")
    return 0 if counts.get("disease_img", 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
