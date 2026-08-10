#!/usr/bin/env python3
"""
make_gallery.py - detect_strawberry.py 결과를 브라우저용 갤러리 HTML로 묶는다.

사용법:
  python3 make_gallery.py detect_out_session_20260526_160446
  -> 해당 폴더에 gallery.html 생성 (브라우저로 열면 됨)

특징:
  - 카메라별 그룹, 검출 박스 수(ripe/unripe) 라벨 표시
  - "검출 있는 것만" / 카메라 필터 토글
  - 외부 의존성 없음(오프라인 동작), 이미지 lazy-load
"""
import csv
import html
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("사용법: python3 make_gallery.py <detect_out_폴더>")
        return 1
    out_dir = Path(sys.argv[1]).resolve()
    if not out_dir.is_dir():
        print(f"[ERROR] 폴더 없음: {out_dir}")
        return 1

    csv_path = out_dir / "detections.csv"
    # 이미지별 클래스 카운트 집계 (cam+파일명으로 키 → 카메라 간 동명 파일 충돌 방지)
    per_img = defaultdict(lambda: {"strawberry-ripe": 0, "strawberry-unripe": 0})
    if csv_path.exists():
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                per_img[(row["cam"], row["image"])][row["class"]] += 1

    cams = sorted(d.name for d in out_dir.iterdir()
                  if d.is_dir() and d.name.startswith("cam"))

    cards = []
    n_total = n_with = 0
    for cam in cams:
        for img in sorted((out_dir / cam).glob("*.jpg")):
            n_total += 1
            c = per_img.get((cam, img.name),
                            {"strawberry-ripe": 0, "strawberry-unripe": 0})
            ripe, unripe = c["strawberry-ripe"], c["strawberry-unripe"]
            ndet = ripe + unripe
            if ndet:
                n_with += 1
            rel = f"{cam}/{img.name}"
            badge = (f'<span class="r">ripe {ripe}</span>'
                     f'<span class="u">unripe {unripe}</span>') if ndet else \
                    '<span class="none">검출 없음</span>'
            cards.append(
                f'<figure class="card" data-cam="{cam}" data-det="{ndet}" '
                f'data-n="{ndet}">'
                f'<img loading="lazy" src="{html.escape(rel)}" alt="{img.name}">'
                f'<figcaption><b>{cam}</b> · {html.escape(img.name)}<br>{badge}'
                f'</figcaption></figure>'
            )

    cam_btns = "".join(
        f'<button onclick="filterCam(\'{c}\')">{c}</button>' for c in cams
    )
    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>딸기 검출 갤러리 - {html.escape(out_dir.name)}</title>
<style>
  body{{font-family:system-ui,'Noto Sans KR',sans-serif;margin:0;background:#111;color:#eee}}
  header{{position:sticky;top:0;background:#1b1b1b;padding:12px 16px;border-bottom:1px solid #333;z-index:10}}
  h1{{font-size:16px;margin:0 0 8px}}
  .stat{{font-size:13px;color:#aaa;margin-bottom:8px}}
  button{{background:#2a2a2a;color:#eee;border:1px solid #444;border-radius:6px;
    padding:5px 10px;margin:2px;cursor:pointer;font-size:13px}}
  button:hover{{background:#383838}}
  button.active{{background:#c0392b;border-color:#c0392b}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
    gap:10px;padding:12px}}
  .card{{margin:0;background:#1b1b1b;border-radius:8px;overflow:hidden;border:1px solid #2a2a2a}}
  .card img{{width:100%;display:block}}
  figcaption{{padding:6px 8px;font-size:12px;color:#bbb;line-height:1.5}}
  .r{{background:#2741c0;color:#fff;padding:1px 6px;border-radius:4px;margin-right:4px}}
  .u{{background:#16a0c0;color:#fff;padding:1px 6px;border-radius:4px}}
  .none{{color:#666}}
  .hidden{{display:none}}
</style></head><body>
<header>
  <h1>딸기 검출 갤러리 — {html.escape(out_dir.name)}</h1>
  <div class="stat">총 {n_total}장 · 검출된 이미지 {n_with}장
    ({100*n_with/max(n_total,1):.1f}%) ·
    <span class="r">ripe</span> <span class="u">unripe</span></div>
  <div>
    <button onclick="filterCam('all')" class="active" id="b-all">전체</button>
    {cam_btns}
    <button onclick="toggleDet()" id="b-det">검출 있는 것만</button>
  </div>
</header>
<div class="grid" id="grid">
{chr(10).join(cards)}
</div>
<script>
let curCam='all', onlyDet=false;
function apply(){{
  document.querySelectorAll('.card').forEach(c=>{{
    const okCam = curCam==='all' || c.dataset.cam===curCam;
    const okDet = !onlyDet || parseInt(c.dataset.det)>0;
    c.classList.toggle('hidden', !(okCam && okDet));
  }});
}}
function filterCam(cam){{
  curCam=cam;
  document.querySelectorAll('header button').forEach(b=>b.classList.remove('active'));
  (document.getElementById('b-'+(cam==='all'?'all':cam))||
   [...document.querySelectorAll('header button')].find(b=>b.textContent===cam)
  ).classList.add('active');
  apply();
}}
function toggleDet(){{
  onlyDet=!onlyDet;
  document.getElementById('b-det').classList.toggle('active', onlyDet);
  apply();
}}
</script>
</body></html>"""

    gallery = out_dir / "gallery.html"
    gallery.write_text(doc, encoding="utf-8")
    print(f"[완료] {gallery}")
    print(f"  총 {n_total}장, 검출된 이미지 {n_with}장")
    print(f"  브라우저로 열기:  xdg-open {gallery}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
