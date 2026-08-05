#!/usr/bin/env python3
"""
build_yolo_aihub.py - AI Hub 딸기(설향) 질병 데이터 → YOLO 검출 형식 변환 (v2)

AI Hub "305.시설작물개체이미지 및 시설작물질병이미지" 데이터를 병해 유무 판별용
YOLO 검출 학습 데이터로 변환한다. 이미지는 zip 안에 있으므로 **필요한 것만 선별 추출**하고,
장변을 축소해 디스크를 절약한다(YOLO 정규화 좌표는 리사이즈에 영향받지 않음).

라벨 구조 (전북대 labelme와 완전히 다름 → 별도 변환기가 필요한 이유):
  - annotations[].bbox        : [x, y, w, h] 절대 픽셀
  - annotations[].category_id : 부위(잎/줄기/화방/과실) — 병명이 아님
  - annotations[].disease_status : "Y"(병징 있음) / "N"(정상) / "E"(불명)
  - images.disease_class      : 이미지 단위 병명(정상/역병/시들음병/잎끝마름/황화)

변환 정책 (목표: 병해 "유무"만 판별):
  - 양성: disease_status == "Y" 박스가 1개 이상인 이미지 → 그 Y 박스만 클래스 0(disease)로 기록
  - 음성: "정상" 클래스 이미지 → 박스 없는 빈 라벨(배경 샘플)
  - 제외: 병해 클래스인데 Y 박스가 없는 이미지 (병징 미주석 가능 → 음성으로 쓰면 위험)
  - 음성 선별 시 **과실(fruit) 박스가 있는 이미지를 우선** 채택 → v1의 건강 과실 오탐 억제

사용법:
  python3 build_yolo_aihub.py                          # 기본값으로 변환
  python3 build_yolo_aihub.py --max-normal-train 15000 --max-normal-val 3000
  python3 build_yolo_aihub.py --imgsz-max 1280 --jobs 8
  python3 build_yolo_aihub.py --max-pos-per-class 5000 # 빠른 시험용 소규모

출력:
  datasets/yolo_aihub/
    images/{train,val}/*.jpg   (선별 추출 + 축소된 실제 이미지)
    labels/{train,val}/*.txt   ("0 xc yc w h" / 음성은 빈 파일)
    data.yaml                  (ultralytics 학습 입력)
    manifest.csv               (출력파일 ↔ 원본파일 대응, 추적용)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_AIHUB = Path.home() / "aihub_strawberry"
DEFAULT_OUT = SCRIPT_DIR / "yolo_aihub"

# 클래스 폴더명 ↔ ASCII 코드 (한글 경로로 인한 인코딩 문제 회피)
CLASSES = {
    "01.정상":    "normal",
    "02.역병":    "blight",
    "03.시들음병": "wilt",
    "04.잎끝마름": "tipburn",
    "05.황화":    "yellowing",
}
SPLITS = {"Training": ("TS", "TL", "train"), "Validation": ("VS", "VL", "val")}

# ── zip 핸들 캐시 (프로세스별로 유지: zipfile은 프로세스 간 공유 불가) ──────────
_ZIP_CACHE: dict[str, zipfile.ZipFile] = {}


def _zip(path: str) -> zipfile.ZipFile:
    z = _ZIP_CACHE.get(path)
    if z is None:
        z = _ZIP_CACHE[path] = zipfile.ZipFile(path)
    return z


def extract_labels(aihub: Path) -> Path:
    """라벨 zip을 한 번만 해제한다(작음). 해제 경로 반환."""
    dest_root = aihub / "labels_extracted"
    for split, (_, lpre, _) in SPLITS.items():
        for cls in CLASSES:
            zpath = aihub / split / "02.라벨링데이터" / f"{lpre}_01.딸기_001.설향_{cls}.zip"
            dest = dest_root / split / cls
            if not zpath.exists():
                print(f"  [경고] 라벨 zip 없음: {zpath.name}")
                continue
            if dest.exists() and any(dest.iterdir()):
                continue  # 이미 해제됨
            dest.mkdir(parents=True, exist_ok=True)
            print(f"  라벨 해제: {split}/{cls}")
            with zipfile.ZipFile(zpath) as z:
                z.extractall(dest)
    return dest_root


def build_image_index(aihub: Path) -> dict[tuple[str, str], tuple[str, dict[str, str]]]:
    """(split, cls) → (이미지 zip 경로, {파일명: zip 내부 멤버명}) 색인."""
    index = {}
    for split, (spre, _, _) in SPLITS.items():
        for cls in CLASSES:
            zpath = aihub / split / "01.원천데이터" / f"{spre}_01.딸기_001.설향_{cls}.zip"
            if not zpath.exists():
                print(f"  [경고] 이미지 zip 없음: {zpath.name}")
                continue
            with zipfile.ZipFile(zpath) as z:
                members = {Path(n).name: n for n in z.namelist() if not n.endswith("/")}
            index[(split, cls)] = (str(zpath), members)
            print(f"  이미지 색인: {split}/{cls}  {len(members):,}장")
    return index


def scan_labels(label_root: Path, split: str, cls: str) -> tuple[list, list]:
    """라벨 JSON을 훑어 (양성 목록, 음성 목록) 반환.

    양성 항목: (파일명, [YOLO 라벨 문자열...])
    음성 항목: (파일명, 과실박스 포함 여부)  ← 정상 클래스만
    """
    folder = label_root / split / cls
    positives, negatives = [], []
    if not folder.exists():
        return positives, negatives

    for js in sorted(folder.rglob("*.json")):
        try:
            d = json.loads(js.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue

        img = d.get("images", {})
        fname = img.get("fname") or (js.stem + ".jpg")
        try:
            W, H = int(img.get("width", 0)), int(img.get("height", 0))
        except (TypeError, ValueError):
            continue
        if W <= 0 or H <= 0:
            continue

        cats = {c.get("id"): c.get("name") for c in d.get("categories", [])}
        lines, has_fruit = [], False
        for a in d.get("annotations", []):
            if cats.get(a.get("category_id")) == "과실":
                has_fruit = True
            if a.get("disease_status") != "Y":
                continue
            bb = a.get("bbox")
            if not bb or len(bb) < 4:
                continue
            x, y, w, h = (float(v) for v in bb[:4])
            # 이미지 경계로 clip 후 YOLO 정규화 (리사이즈와 무관하게 유효)
            x1, y1 = max(0.0, x), max(0.0, y)
            x2, y2 = min(float(W), x + w), min(float(H), y + h)
            if x2 <= x1 or y2 <= y1:
                continue
            lines.append(f"0 {(x1+x2)/2/W:.6f} {(y1+y2)/2/H:.6f} "
                         f"{(x2-x1)/W:.6f} {(y2-y1)/H:.6f}")

        if lines:
            positives.append((fname, lines))
        elif cls == "01.정상":
            negatives.append((fname, has_fruit))
        # 병해 클래스인데 Y 없음 → 제외(병징 미주석 가능성)
    return positives, negatives


def convert_one(task: tuple) -> tuple[bool, str]:
    """이미지 1장을 zip에서 추출 → 축소 → 저장하고 라벨 txt를 쓴다."""
    zpath, member, out_img, out_lbl, lines, max_side = task
    import cv2
    import numpy as np
    try:
        buf = _zip(zpath).read(member)
        im = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            return False, member
        h, w = im.shape[:2]
        if max_side and max(h, w) > max_side:      # 장변 기준 축소
            s = max_side / max(h, w)
            im = cv2.resize(im, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        ok, enc = cv2.imencode(".jpg", im, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            return False, member
        # 한글 경로 문제 회피: cv2.imwrite 대신 바이트 직접 기록
        Path(out_img).write_bytes(enc.tobytes())
        Path(out_lbl).write_text("\n".join(lines))
        return True, member
    except Exception:
        return False, member


def main() -> int:
    ap = argparse.ArgumentParser(description="AI Hub 딸기 질병 → YOLO 검출 형식(v2)")
    ap.add_argument("--aihub-dir", default=str(DEFAULT_AIHUB), help="AI Hub zip 폴더")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="출력 폴더")
    ap.add_argument("--max-normal-train", type=int, default=15000, help="train 음성(정상) 최대 장수")
    ap.add_argument("--max-normal-val", type=int, default=3000, help="val 음성(정상) 최대 장수")
    ap.add_argument("--max-pos-per-class", type=int, default=0,
                    help="병해 클래스별 양성 최대 장수 (0=제한 없음)")
    ap.add_argument("--imgsz-max", type=int, default=1280, help="장변 최대 픽셀(0=원본 유지)")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 2),
                    help="병렬 워커 수")
    ap.add_argument("--dry-run", action="store_true", help="집계만 하고 이미지는 추출하지 않음")
    args = ap.parse_args()

    aihub, out = Path(args.aihub_dir), Path(args.out)
    if not aihub.exists():
        print(f"[오류] AI Hub 폴더 없음: {aihub}")
        return 1

    print("=" * 60)
    print(f"입력   : {aihub}")
    print(f"출력   : {out}")
    print(f"축소   : 장변 {args.imgsz_max or '원본'}  | 워커 {args.jobs}")
    print("=" * 60)

    print("\n[1/4] 라벨 zip 해제")
    label_root = extract_labels(aihub)

    print("\n[2/4] 이미지 zip 색인")
    img_index = build_image_index(aihub)

    print("\n[3/4] 라벨 분석 및 대상 선별")
    tasks, manifest = [], []
    counts: dict[str, int] = {}
    for split, (_, _, dst) in SPLITS.items():
        (out / "images" / dst).mkdir(parents=True, exist_ok=True)
        (out / "labels" / dst).mkdir(parents=True, exist_ok=True)
        max_normal = args.max_normal_train if dst == "train" else args.max_normal_val

        for cls, code in CLASSES.items():
            if (split, cls) not in img_index:
                continue
            zpath, members = img_index[(split, cls)]
            pos, neg = scan_labels(label_root, split, cls)

            if cls == "01.정상":
                # 과실 박스 포함 이미지를 우선 채택(건강 과실 오탐 억제 목적)
                neg.sort(key=lambda t: not t[1])
                chosen = [(f, []) for f, _ in neg[:max_normal]]
                n_fruit = sum(1 for f, hf in neg[:max_normal] if hf)
                counts[f"{dst}/{code}(음성)"] = len(chosen)
                counts[f"{dst}/{code}(음성-과실포함)"] = n_fruit
            else:
                chosen = pos[:args.max_pos_per_class] if args.max_pos_per_class else pos
                counts[f"{dst}/{code}(양성)"] = len(chosen)

            for i, (fname, lines) in enumerate(chosen):
                member = members.get(fname)
                if member is None:
                    continue
                stem = f"{code}_{dst}_{i:06d}"
                tasks.append((zpath, member,
                              str(out / "images" / dst / f"{stem}.jpg"),
                              str(out / "labels" / dst / f"{stem}.txt"),
                              lines, args.imgsz_max))
                manifest.append([f"{stem}.jpg", fname, dst, code, len(lines)])

    print("\n  선별 결과")
    for k in sorted(counts):
        if counts[k]:
            print(f"    {k:<34}: {counts[k]:>7,}")
    print(f"    {'추출 대상 총계':<34}: {len(tasks):>7,}")

    if args.dry_run:
        print("\n[dry-run] 이미지 추출 생략.")
        return 0

    print(f"\n[4/4] 이미지 추출·축소 (워커 {args.jobs})")
    done = fail = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(convert_one, t) for t in tasks]
        for fu in as_completed(futs):
            ok, _ = fu.result()
            done += ok
            fail += (not ok)
            if (done + fail) % 500 == 0 or (done + fail) == len(tasks):
                print(f"\r  진행 {done+fail:,}/{len(tasks):,}  (성공 {done:,} / 실패 {fail:,})",
                      end="", flush=True)
    print()

    # manifest + data.yaml
    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["out_name", "orig_name", "split", "class", "n_boxes"])
        w.writerows(manifest)
    (out / "data.yaml").write_text(
        f"path: {out}\ntrain: images/train\nval: images/val\n"
        "nc: 1\nnames:\n  0: disease\n", encoding="utf-8")

    # 최종 집계
    print("=" * 60)
    for dst in ("train", "val"):
        n_img = len(list((out / "images" / dst).glob("*.jpg")))
        lbls = list((out / "labels" / dst).glob("*.txt"))
        n_pos = sum(1 for p in lbls if p.stat().st_size > 0)
        print(f"  {dst:<6}: 이미지 {n_img:>7,}  | 양성 {n_pos:>7,}  음성 {n_img-n_pos:>7,}")
    sz = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1e9
    print(f"  용량  : {sz:.1f}GB")
    print(f"  실패  : {fail:,}")
    print("=" * 60)
    print(f"data.yaml: {out / 'data.yaml'}")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
