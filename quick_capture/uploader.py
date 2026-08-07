#!/usr/bin/env python3
"""
uploader.py - 명시한 세션 폴더의 이미지만 서버에 업로드

사용법:
  python3 uploader.py <세션_폴더_경로>

예시:
  python3 uploader.py /home/jay/pest_control_ws/quick_capture_data/session_20260526_103000

동작:
  - 명시한 폴더의 cam*/*.jpg만 업로드
  - 시작 전 "yes" 입력 확인 단계 (오업로드 방지)
  - 성공: uploaded/ 하위로 이동
  - 실패(3회 재시도): failed/ 하위로 이동
  - 자동 폴더 감시 기능 없음 (의도치 않은 업로드 방지)
"""
import os
import sys
import glob
import shutil
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hks_agrix_ext_client import upload_and_register

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2


def list_files(session_dir):
    pattern = os.path.join(session_dir, "cam*", "*.jpg")
    files = glob.glob(pattern)
    return sorted([f for f in files
                   if "/uploaded/" not in f and "/failed/" not in f])


def move_to_subfolder(filepath, subfolder):
    cam_dir = os.path.dirname(filepath)
    target_dir = os.path.join(cam_dir, subfolder)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, os.path.basename(filepath))
    shutil.move(filepath, target)


def upload_one(filepath):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = upload_and_register(filepath)
            return True, result
        except Exception as e:
            wait = RETRY_BACKOFF_BASE ** attempt
            print(f"  [시도 {attempt}/{MAX_RETRIES}] 실패: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(wait)
    return False, None


def main():
    parser = argparse.ArgumentParser(description="명시한 세션 폴더만 업로드")
    parser.add_argument("session_dir", help="업로드할 세션 폴더 절대경로")
    args = parser.parse_args()

    session_dir = os.path.abspath(args.session_dir)
    if not os.path.isdir(session_dir):
        print(f"[ERROR] 폴더 없음: {session_dir}")
        sys.exit(1)

    files = list_files(session_dir)
    if not files:
        print("[정보] 업로드 대상 .jpg 없음 (이미 처리됐거나 비어있음)")
        sys.exit(0)

    print("=" * 50)
    print("Quick Uploader - 명시적 세션 업로드")
    print(f"대상 폴더: {session_dir}")
    print(f"업로드 대상: {len(files)}개")
    print("=" * 50)

    confirm = input(f"\n위 {len(files)}개 파일을 서버에 업로드합니다. "
                    f"진행하시겠습니까? [yes/no]: ").strip().lower()
    if confirm != "yes":
        print("취소됨.")
        sys.exit(0)

    print()
    success_cnt = 0
    fail_cnt = 0

    for i, fp in enumerate(files, 1):
        rel = os.path.relpath(fp, session_dir)
        print(f"[{i}/{len(files)}] {rel}")
        ok, result = upload_one(fp)
        if ok:
            move_to_subfolder(fp, "uploaded")
            success_cnt += 1
            print(f"  [성공] id={result.get('id', 'N/A')}")
        else:
            move_to_subfolder(fp, "failed")
            fail_cnt += 1
            print(f"  [실패] failed/로 이동")

    print()
    print("=" * 50)
    print(f"완료: 성공 {success_cnt} / 실패 {fail_cnt}")
    print("=" * 50)


if __name__ == "__main__":
    main()