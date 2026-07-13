#!/usr/bin/env python3
"""
focus_finder.py - 카메라의 최적 고정 초점값(focus)을 찾는 도구

[목적]
  오토포커스를 끈 상태에서 focus 값(0~255)을 하나씩 바꿔가며,
  각 값에서 영상이 얼마나 '선명한지'를 숫자(선명도)로 재서
  가장 선명한 focus 값을 추천한다. (눈대중이 아니라 숫자로 객관 판단)

[준비]
  - 카메라 앞 '작업거리'에 체커보드(또는 무늬가 또렷한 대상)를 고정해 둔다.
  - 대상이 화면에 크게, 흔들리지 않게 둔다. (움직이면 선명도 측정이 흔들림)

[사용법]
  python3 quick_capture/focus_finder.py                      # /dev/cam1, 0~255 step5
  python3 quick_capture/focus_finder.py --device /dev/cam2   # 다른 카메라
  python3 quick_capture/focus_finder.py --step 10 --preview  # 더 빠르게 + 미리보기 창

[결과]
  - 콘솔에 focus값별 선명도 + 추천값 출력
  - focus_scan/ 폴더에 focus값별 샘플 이미지 저장(눈으로 교차확인용)
"""
import cv2
import os
import csv
import time
import argparse
import numpy as np


def sharpness(gray):
    """선명도 점수. 라플라시안 분산: 경계(엣지)가 뚜렷할수록 큰 값 → 선명할수록 큼."""
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def grab_stable(cap, warmup=8):
    """focus를 바꾼 직후 렌즈가 자리잡을 시간을 준다(앞 프레임 몇 장은 버림)."""
    frame = None
    for _ in range(warmup):
        ret, frame = cap.read()
        time.sleep(0.03)
    return frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="/dev/cam1", help="카메라 장치 (기본 /dev/cam1)")
    parser.add_argument("--start", type=int, default=0, help="focus 시작값 (기본 0)")
    parser.add_argument("--end", type=int, default=255, help="focus 끝값 (기본 255)")
    parser.add_argument("--step", type=int, default=5, help="focus 증가 간격 (기본 5)")
    parser.add_argument("--no-preview", action="store_true", help="미리보기 창 끄기(SSH 등 화면 없을 때)")
    parser.add_argument("--outdir", default=None, help="저장 폴더 (기본: focus_scan/<카메라명>)")
    args = parser.parse_args()
    show_preview = not args.no_preview   # 기본은 모니터에 창을 띄워 보면서 진행
    # 카메라별로 폴더를 나눠 저장(예: focus_scan/cam1) → 다른 카메라 결과를 덮어쓰지 않음
    if args.outdir is None:
        args.outdir = os.path.join("focus_scan", os.path.basename(args.device))

    cap = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"[ERROR] {args.device} 열기 실패")
        return
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    # 오토포커스 OFF: 이걸 꺼야 focus 값을 수동으로 고정할 수 있다.
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)

    os.makedirs(args.outdir, exist_ok=True)

    results = []  # (focus, 선명도) 목록
    print(f"장치 {args.device}  focus {args.start}~{args.end} (step {args.step}) 스윕 시작")
    print("준비: 작업거리에 체커보드를 고정해 두세요.\n")

    for focus in range(args.start, args.end + 1, args.step):
        cap.set(cv2.CAP_PROP_FOCUS, focus)       # 이번 focus 값으로 고정
        frame = grab_stable(cap)                 # 렌즈 안정 후 한 장 확보
        if frame is None:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        s = sharpness(gray)                       # 선명도 숫자 계산
        results.append((focus, s))
        # 샘플 이미지에 focus/선명도를 적어 저장 → 나중에 눈으로 교차확인
        cv2.putText(frame, f"focus={focus}  sharp={s:.0f}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.imwrite(os.path.join(args.outdir, f"focus_{focus:03d}.jpg"), frame)
        print(f"  focus={focus:3d}  선명도={s:10.0f}")
        if show_preview:   # 스윕하는 동안 모니터에 실시간 표시(눈으로 같이 봄)
            cv2.imshow("focus scan", frame)
            if cv2.waitKey(1) == ord('q'):
                break

    if results:
        # 선명도 표를 CSV로 저장 (나중에 그래프로 시각화하기 좋게)
        csv_path = os.path.join(args.outdir, "sharpness.csv")
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["focus", "sharpness"])
            for fo, s in results:
                w.writerow([fo, f"{s:.1f}"])
        print(f"선명도 표 저장: {csv_path}")

        best = max(results, key=lambda x: x[1])   # 선명도가 가장 큰 focus = 자동 추천값
        print(f"\n추천 초점값:  --focus {best[0]}   (선명도 {best[1]:.0f}로 가장 큼)")
        print(f"샘플 확인:    {args.outdir}/focus_{best[0]:03d}.jpg")
        if show_preview:
            # 추천 초점으로 고정해 실시간 화면을 띄워 '눈으로 최종 확인'. 창에서 아무 키나 누르면 종료.
            cap.set(cv2.CAP_PROP_FOCUS, best[0])
            print("추천 초점 적용 화면 표시 중 — 또렷한지 보고, 창에서 아무 키나 누르면 종료합니다.")
            while True:
                ret, frame = cap.read()
                if ret:
                    cv2.putText(frame, f"BEST focus={best[0]}  sharp={best[1]:.0f}", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
                    cv2.imshow("focus scan", frame)
                if cv2.waitKey(30) != -1:
                    break

    cap.release()
    if show_preview:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
