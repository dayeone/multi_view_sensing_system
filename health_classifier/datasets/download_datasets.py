#!/usr/bin/env python3
"""
download_datasets.py - 딸기 정상/이상 판정용 오픈소스 데이터셋 취득

두 가지 경로를 지원한다.
  1) 자동: kagglehub 로 Kaggle 데이터셋 다운로드 → datasets/raw/<key>/ 로 심볼릭 링크
  2) 수동: 브라우저로 받은 zip 을 datasets/raw/_zips/<key>.zip 에 두고 --manual 로 추출

kagglehub 설치·Kaggle 인증은 CLAUDE.md 보안 규칙상 사용자 승인 후 진행한다.
본 스크립트는 미설치/미인증 시 실행 방법을 안내하고 종료한다(자동 설치하지 않음).

사용법:
  python3 download_datasets.py --all                 # 자동 취득(전체)
  python3 download_datasets.py --only jbnu_disease   # 특정 데이터셋만
  python3 download_datasets.py --manual              # raw/_zips/*.zip 추출
  python3 download_datasets.py --status              # 취득 현황만 출력
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_DIR = SCRIPT_DIR / "raw"
ZIP_DIR = RAW_DIR / "_zips"

# 데이터셋 메타 (Kaggle slug, 설명, 라이선스/인용)
DATASETS: dict[str, dict[str, str]] = {
    "jbnu_disease": {
        "kaggle": "usmanafzaal/strawberry-disease-detection-dataset",
        "desc": "JBNU 딸기 병해 2,500장, 8클래스(7병해+healthy), labelme segmentation",
        "license": "관대(수정·병합 허용)",
    },
    "tipburn": {
        "kaggle": "ercanavsar/images-of-strawberry-leaves-for-tipburn-detection",
        "desc": "딸기 잎 tipburn 1,431장, healthy vs 칼슘결핍(생리장해)",
        "license": "Mendeley Data / 인용: Hariri & Avsar (2022)",
    },
}


def link_from_cache(cache_path: Path, dest: Path) -> None:
    """kagglehub 캐시 경로를 raw/<key> 로 심볼릭 링크(용량 중복 방지)."""
    if dest.is_symlink() or dest.exists():
        dest.unlink() if dest.is_symlink() else shutil.rmtree(dest)
    dest.symlink_to(cache_path, target_is_directory=True)


def download_auto(keys: list[str]) -> int:
    try:
        import kagglehub  # noqa: F401
    except ModuleNotFoundError:
        print(
            "[안내] kagglehub 미설치. 자동 다운로드 불가.\n"
            "  설치(승인 후): conda activate strawberry && pip install kagglehub\n"
            "  인증 토큰    : kaggle.com > Settings > API > Create New Token\n"
            "                 → kaggle.json 을 ~/.config/kaggle/kaggle.json (chmod 600)\n"
            "  또는 --manual 경로 사용(브라우저 다운로드 zip 추출)."
        )
        return 2

    import kagglehub

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for key in keys:
        slug = DATASETS[key]["kaggle"]
        print(f"[다운로드] {key} ← kaggle:{slug}")
        try:
            cache = Path(kagglehub.dataset_download(slug))
        except Exception as e:  # 인증/네트워크 등
            print(f"  [실패] {e}\n  → 인증 토큰 확인 또는 --manual 사용")
            return 3
        link_from_cache(cache, RAW_DIR / key)
        print(f"  [완료] raw/{key} → {cache}")
    return 0


def extract_manual(keys: list[str]) -> int:
    if not ZIP_DIR.exists():
        ZIP_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[안내] {ZIP_DIR} 생성. 각 데이터셋 zip 을 <key>.zip 이름으로 배치 후 재실행.")
        for key in keys:
            print(f"  - {key}.zip  ← https://www.kaggle.com/datasets/{DATASETS[key]['kaggle']}")
        return 2

    rc = 2
    for key in keys:
        zip_path = ZIP_DIR / f"{key}.zip"
        if not zip_path.exists():
            print(f"[스킵] {zip_path} 없음")
            continue
        dest = RAW_DIR / key
        dest.mkdir(parents=True, exist_ok=True)
        print(f"[추출] {zip_path.name} → raw/{key}")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest)
        print(f"  [완료] {sum(1 for _ in dest.rglob('*') if _.is_file())} 파일")
        rc = 0
    return rc


def print_status() -> None:
    print("=" * 60)
    for key, meta in DATASETS.items():
        dest = RAW_DIR / key
        n = sum(1 for _ in dest.rglob("*") if _.is_file()) if dest.exists() else 0
        mark = "O" if n else "-"
        print(f"[{mark}] {key:<14} 파일 {n:>5}  | {meta['desc']}")
        print(f"     라이선스: {meta['license']}")
    print("=" * 60)


def main() -> int:
    ap = argparse.ArgumentParser(description="딸기 정상/이상 데이터셋 취득")
    ap.add_argument("--all", action="store_true", help="전체 데이터셋 자동 취득")
    ap.add_argument("--only", choices=list(DATASETS), help="특정 데이터셋만")
    ap.add_argument("--manual", action="store_true", help="raw/_zips/*.zip 추출")
    ap.add_argument("--status", action="store_true", help="취득 현황만 출력")
    args = ap.parse_args()

    keys = [args.only] if args.only else list(DATASETS)

    if args.status:
        print_status()
        return 0
    if args.manual:
        rc = extract_manual(keys)
        print_status()
        return rc
    if args.all or args.only:
        rc = download_auto(keys)
        print_status()
        return rc

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
