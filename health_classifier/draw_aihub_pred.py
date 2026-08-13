#!/usr/bin/env python3
"""AI Hub 배포 모델(YOLOv3)의 추론 결과 json에 박스를 그리고, 우리 형식의 판정표를 만든다.

배포본 `YOLOv3_pred.py` 는 json 만 저장하고 **박스를 그려주지 않는다.** 게다가
검출이 0개인 이미지는 json 자체를 만들지 않아(원본 115행이 `if len(det):` 안에 있음),
결과 폴더만 봐서는 "검출이 없었던 것"과 "처리가 안 된 것"을 구분할 수 없다.

이 스크립트가 하는 일
  1. 원본 이미지 + json 을 짝지어 박스를 그린다
       유(병해) = 빨강 굵게 / 무(정상) = 회색 얇게
  2. 판정 결과에 따라 세 폴더로 나눠 저장한다
       유_있음 / 무_만있음 / 검출_없음
  3. `verdicts.csv` 를 우리 추론 스크립트(classify_strawberry.py)와 **같은 열**로 만든다
       → 모델끼리 바로 비교할 수 있다

json 형식 (배포본이 만드는 것)
  {"shapes": [{"boxes": [x1,y1,x2,y2], "labels": 0.0|1.0, "scores": 0.0~1.0}, ...]}
  labels 0 = 유(병해),  1 = 무(정상)

사용:
  python3 draw_aihub_pred.py \
      --images ~/pest_control_ws/quick_capture_data/session_20260526_160446/cam0/uploaded \
      --json   ~/pest_control_ws/health_classifier/classify_out_aihub_cam0
  python3 draw_aihub_pred.py --images ... --json ... --conf 0.4   # 임계값 다시 걸기
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

# labels 값 → (우리말 이름, 색 BGR, 선 굵기)
CLS = {
    0: ("유(병해)", (40, 40, 220), 3),
    1: ("무(정상)", (150, 150, 150), 1),
}
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]
IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp")


def load_font(size: int):
    """한글은 cv2.putText 로 못 그린다. PIL 폰트를 찾고, 없으면 None(영문 표기로 대체)."""
    try:
        from PIL import ImageFont
    except Exception:
        return None
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return None


def put_labels(im, items, font):
    """items = [(x, y, 글자, 색BGR)]. PIL 로 한 번에 그린다(한글)."""
    if not items:
        return im
    if font is None:
        for x, y, t, c in items:
            cv2.putText(im, t.split("(")[0], (int(x), max(14, int(y) - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2, cv2.LINE_AA)
        return im
    from PIL import Image, ImageDraw
    pil = Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    for x, y, t, c in items:
        rgb = (c[2], c[1], c[0])
        ty = max(0, int(y) - 24)
        l, t_, r, b = d.textbbox((int(x), ty), t, font=font)
        d.rectangle([l - 3, t_ - 2, r + 3, b + 2], fill=rgb)
        d.text((int(x), ty), t, font=font, fill=(255, 255, 255))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, help="원본 이미지 폴더")
    ap.add_argument("--json", required=True, help="YOLOv3_pred.py 가 만든 json 폴더")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본: <json폴더>/annotated)")
    ap.add_argument("--conf", type=float, default=0.0,
                    help="이 값 미만인 검출은 버린다 (추론 때와 다르게 다시 걸 수 있음)")
    ap.add_argument("--cam", default=None, help="verdicts.csv 의 cam 열 값 (기본: 이미지 폴더 이름에서 추출)")
    args = ap.parse_args()

    img_dir, js_dir = Path(args.images).expanduser(), Path(args.json).expanduser()
    out = Path(args.out).expanduser() if args.out else js_dir / "annotated"
    for sub in ("유_있음", "무_만있음", "검출_없음"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    # cam 이름: .../cam0/uploaded → cam0
    cam = args.cam
    if cam is None:
        cam = next((p for p in img_dir.parts[::-1] if p.startswith("cam")), "unknown")

    font = load_font(20)
    imgs = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in IMG_EXTS)
    if not imgs:
        print(f"[오류] 이미지 없음: {img_dir}")
        return 1

    rows, n_y, n_n, n_zero = [], 0, 0, 0
    for p in imgs:
        im = cv2.imread(str(p))
        if im is None:
            continue
        jf = js_dir / f"{p.stem}.json"
        shapes = []
        if jf.exists():
            try:
                shapes = json.loads(jf.read_text()).get("shapes", [])
            except Exception:
                shapes = []
        shapes = [s for s in shapes if float(s.get("scores", 0)) >= args.conf]

        labels, n_dis, max_conf = [], 0, 0.0
        for s in shapes:
            x1, y1, x2, y2 = (int(round(v)) for v in s["boxes"])
            c = int(s["labels"])
            name, color, lw = CLS.get(c, (f"?{c}", (0, 200, 200), 2))
            cv2.rectangle(im, (x1, y1), (x2, y2), color, lw)
            labels.append((x1, y1, f"{name} {float(s['scores']):.2f}", color))
            if c == 0:
                n_dis += 1
                max_conf = max(max_conf, float(s["scores"]))
        im = put_labels(im, labels, font)

        if n_dis > 0:
            sub, verdict = "유_있음", "abnormal"; n_y += 1
        elif shapes:
            sub, verdict = "무_만있음", "normal"; n_n += 1
        else:
            sub, verdict = "검출_없음", "no_detection"; n_zero += 1
            # 아무것도 못 찾은 사진임을 눈에 띄게 표시
            cv2.rectangle(im, (0, 0), (im.shape[1] - 1, im.shape[0] - 1), (0, 165, 255), 6)
            im = put_labels(im, [(12, 40, "검출 없음", (0, 165, 255))], font)

        cv2.imwrite(str(out / sub / p.name), im)
        rows.append([p.name, cam, verdict, n_dis, f"{max_conf:.3f}",
                     len(shapes) - n_dis])

    csv_path = out / "verdicts.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image", "cam", "verdict", "n_disease", "max_conf", "n_normal"])
        w.writerows(rows)

    tot = len(rows)
    print("=" * 52)
    print(f"  이미지        : {tot}장   (cam = {cam})")
    print(f"  유(병해) 있음 : {n_y}장  ({100*n_y/tot:.1f}%)")
    print(f"  무(정상)만    : {n_n}장  ({100*n_n/tot:.1f}%)")
    print(f"  검출 없음     : {n_zero}장  ({100*n_zero/tot:.1f}%)")
    print("=" * 52)
    print(f"  주석 이미지 : {out}")
    print(f"  판정표      : {csv_path}")
    print("\n  verdicts.csv 는 classify_strawberry.py 와 같은 열이라 모델끼리 바로 비교됩니다.")
    print("  (n_normal 열만 추가 — 이 모델은 정상도 박스를 치기 때문)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
