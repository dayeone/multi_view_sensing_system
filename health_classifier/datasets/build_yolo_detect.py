#!/usr/bin/env python3
"""
build_yolo_detect.py - 병해 데이터 → YOLO 검출 형식 변환 (구조 B, v1)

raw/jbnu_disease/{train,val,test}/ 의 <name>.jpg + <name>.json(labelme 폴리곤)을 읽어
YOLO 검출 학습용 구조로 변환한다. 선택적으로 raw/tipburn 의 건강 잎을 음성 샘플로 추가한다.

v1 정책 (로우레벨: 병해 유무만):
  - 7개 병해 클래스를 모두 단일 클래스 0 = "disease" 로 통합
  - 폴리곤 → 외접 사각형(bbox) 으로 변환
  - 건강(healthy) 이미지: 박스 없는 "음성 샘플"(빈 라벨 파일)로 포함 → 오탐 억제 학습
  - 라벨(json) 없는 이미지(예: Severity Level 세트)는 건너뜀

tipburn 통합 (--with-tipburn, raw/tipburn 존재 시 기본 활성):
  - healthy 폴더 → 음성 샘플(빈 라벨). 오탐 감소 목적. 박스 불필요.
  - Calciumdeficiency(팁번) 폴더 → 기본 제외. 박스 주석이 없어 검출 양성으로 자동 변환 불가.
      --tipburn-deficiency-positive 지정 시에만 "이미지 전체 박스"로 거칠게 양성 추가(근사, 권장 아님).

출력:
  datasets/yolo_disease/
    images/{train,val}/*.jpg   (원본으로의 심볼릭 링크)
    labels/{train,val}/*.txt   ("0 xc yc w h". 음성 샘플은 빈 파일)
    data.yaml

사용법:
  python3 build_yolo_detect.py                         # 전북대 + tipburn healthy(음성)
  python3 build_yolo_detect.py --no-tipburn            # 전북대만
  python3 build_yolo_detect.py --tipburn-deficiency-positive  # 팁번을 전체박스 양성으로도 추가
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_JBNU = SCRIPT_DIR / "raw" / "jbnu_disease"
RAW_TIPBURN = SCRIPT_DIR / "raw" / "tipburn"
OUT_DIR = SCRIPT_DIR / "yolo_disease"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
NORMAL_KEYWORDS = ("healthy", "health", "normal", "정상")


def is_normal(label: str) -> bool:
    low = label.lower()
    return any(k in low for k in NORMAL_KEYWORDS)


def hash_split(name: str, val_ratio: float) -> str:
    """파일명 해시로 결정적 train/val 분할."""
    frac = int(hashlib.md5(name.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if frac < val_ratio else "train"


def link_image(img: Path, split: str, name: str) -> Path:
    """이미지를 images/<split>/<name> 로 심볼릭 링크하고 라벨 경로 stem 반환."""
    img_out = OUT_DIR / "images" / split
    img_out.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)
    link = img_out / name
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(img.resolve())
    return OUT_DIR / "labels" / split / f"{Path(name).stem}.txt"


def poly_to_bbox(points: list[list[float]], w: int, h: int) -> tuple[float, float, float, float]:
    """폴리곤 점들 → YOLO 정규화 bbox (xc, yc, bw, bh). 이미지 경계로 clip."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x1, x2 = max(0.0, min(xs)), min(float(w), max(xs))
    y1, y2 = max(0.0, min(ys)), min(float(h), max(ys))
    return (x1 + x2) / 2 / w, (y1 + y2) / 2 / h, (x2 - x1) / w, (y2 - y1) / h


def convert_jbnu(src_split: Path, dst_split: str, counts: dict) -> None:
    """전북대 한 split 폴더의 이미지+json 을 YOLO 형식으로 변환."""
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
        for shape in data.get("shapes", []):
            if is_normal(shape.get("label", "")) or len(shape.get("points", [])) < 3:
                continue
            xc, yc, bw, bh = poly_to_bbox(shape["points"], w, h)
            if bw > 0 and bh > 0:
                lines.append(f"0 {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")

        lbl = link_image(img, dst_split, img.name)
        lbl.write_text("\n".join(lines))
        counts["disease_img" if lines else "normal_img"] = \
            counts.get("disease_img" if lines else "normal_img", 0) + 1
        counts["boxes"] = counts.get("boxes", 0) + len(lines)


def process_tipburn(counts: dict, deficiency_as_positive: bool, val_ratio: float) -> None:
    """tipburn: healthy → 음성 샘플, deficiency → 기본 제외(옵션 시 전체박스 양성)."""
    imgs = [p for p in RAW_TIPBURN.rglob("*") if p.suffix.lower() in IMG_EXTS]
    for img in imgs:
        name = f"tipburn__{img.name}"
        split = hash_split(img.name, val_ratio)
        if is_normal(img.parent.name):
            lbl = link_image(img, split, name)
            lbl.write_text("")  # 음성 샘플(빈 라벨)
            counts["tipburn_normal"] = counts.get("tipburn_normal", 0) + 1
        elif deficiency_as_positive:
            lbl = link_image(img, split, name)
            lbl.write_text("0 0.500000 0.500000 0.980000 0.980000\n")  # 전체박스 근사
            counts["tipburn_pos"] = counts.get("tipburn_pos", 0) + 1
        else:
            counts["tipburn_defic_skip"] = counts.get("tipburn_defic_skip", 0) + 1


def process_neg_dir(neg_dir: str, counts: dict, val_ratio: float) -> None:
    """외부 폴더의 이미지를 음성(빈 라벨) 배경 샘플로 추가."""
    imgs = sorted(p for p in Path(neg_dir).rglob("*") if p.suffix.lower() in IMG_EXTS)
    for i, img in enumerate(imgs):
        name = f"neg{i:05d}__{img.name}"  # 파일명 충돌 방지
        split = hash_split(name, val_ratio)
        lbl = link_image(img, split, name)
        lbl.write_text("")  # 빈 라벨 = 배경(음성)
        counts["extneg"] = counts.get("extneg", 0) + 1


def main() -> int:
    ap = argparse.ArgumentParser(description="병해 → YOLO 검출 형식(구조 B)")
    ap.add_argument("--keep-test", action="store_true", help="test 를 별도 split 로 유지")
    ap.add_argument("--no-tipburn", action="store_true", help="tipburn 통합 비활성")
    ap.add_argument("--tipburn-deficiency-positive", action="store_true",
                    help="팁번(칼슘부족)을 이미지 전체박스 양성으로 추가(근사, 권장 아님)")
    ap.add_argument("--neg-dir", type=str, default=None,
                    help="추가 음성(정상) 이미지 폴더. 빈 라벨 배경 샘플로 추가(예: 실증 건강 사진)")
    ap.add_argument("--val-ratio", type=float, default=0.2, help="tipburn/음성 split의 val 비율")
    args = ap.parse_args()

    if not RAW_JBNU.exists():
        print(f"[오류] {RAW_JBNU} 없음. 먼저 download_datasets.py --only jbnu_disease 실행")
        return 1

    # 전북대 변환 (test→val 로 합침이 기본)
    mapping = {"train": "train", "val": "val",
               "test": ("test" if args.keep_test else "val")}
    counts: dict = {}
    for src_name, dst in mapping.items():
        src = RAW_JBNU / src_name
        if src.exists():
            print(f"[변환] jbnu {src_name} → {dst}")
            convert_jbnu(src, dst, counts)
        else:
            print(f"[스킵] jbnu {src_name} 폴더 없음")

    # tipburn 통합
    if not args.no_tipburn and RAW_TIPBURN.exists():
        print(f"[통합] tipburn (deficiency_positive={args.tipburn_deficiency_positive})")
        process_tipburn(counts, args.tipburn_deficiency_positive, args.val_ratio)
    elif not args.no_tipburn:
        print("[정보] raw/tipburn 없음 → 전북대만 사용. (download_datasets.py --only tipburn)")

    if args.neg_dir:
        if Path(args.neg_dir).exists():
            print(f"[통합] 외부 음성 폴더: {args.neg_dir}")
            process_neg_dir(args.neg_dir, counts, args.val_ratio)
        else:
            print(f"[경고] --neg-dir 경로 없음: {args.neg_dir}")

    # data.yaml
    splits = {"train": "images/train", "val": "images/val"}
    if args.keep_test:
        splits["test"] = "images/test"
    yaml_lines = [f"path: {OUT_DIR}"] + [f"{k}: {v}" for k, v in splits.items()]
    yaml_lines += ["nc: 1", "names:", "  0: disease"]
    (OUT_DIR / "data.yaml").write_text("\n".join(yaml_lines) + "\n")

    # 리포트
    print("=" * 52)
    print(f"병해 이미지(박스 有)      : {counts.get('disease_img', 0)}")
    print(f"전북대 정상(음성)         : {counts.get('normal_img', 0)}")
    print(f"tipburn 건강(음성 추가)   : {counts.get('tipburn_normal', 0)}")
    print(f"tipburn 팁번(전체박스 양성): {counts.get('tipburn_pos', 0)}")
    print(f"tipburn 팁번 제외         : {counts.get('tipburn_defic_skip', 0)}")
    print(f"외부 음성(빈 라벨)        : {counts.get('extneg', 0)}")
    print(f"총 박스 수                : {counts.get('boxes', 0)}")
    print(f"라벨없어 스킵/파싱실패    : {counts.get('no_label_skip', 0)}/{counts.get('parse_fail', 0)}")
    print("=" * 52)
    print(f"출력: {OUT_DIR}")
    return 0 if counts.get("disease_img", 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
