# 시간 동기화 통제 A/B 로그 (논문 결과 원본 수치)

`figures/sync_gap_comparison.png`와 논문 3.2 표3의 근거가 되는 로그다.
recorder.py 통제 비교 모드(같은 버퍼로 latest·nearest를 함께 계산)로 기록한
4개 세션(총 497 묶음)의 세트별 sync gap이다. 원본 이미지 데이터(quick_capture_data)는
용량 때문에 git에 포함하지 않고, 결과 수치(CSV)만 여기에 둔다.

## 파일
- `session_YYYYMMDD_HHMMSS.csv` × 4 (2026-07-21 리그, 로봇 정지, 2Hz)

## 열(column) 설명
- `set`: 묶음 번호
- `gap_saved_ms`: 실제 저장된 방식(match_mode)의 동기화 오차
- `gap_latest_ms`: 최신 프레임 선택(baseline) 방식의 gap
- `gap_nearest_ms`: 최근접 시각 정합(제안) 방식의 gap
- `cam1_age_ms`~`cam4_age_ms`: 저장된 프레임의 나이(집은 순간 기준)
- `match_mode`: 저장에 사용한 방식(latest/nearest)
- `stale_warn`: age>100ms 프레임 포함 여부(1/0)

## 요약 (4세션 통합, n=497)
- latest: 평균 23.4 / 최대 67.2 / p95 30.0 ms
- nearest: 평균 19.0 / 최대 33.4 / p95 22.6 ms  (평균 약 19% 감소, 전 묶음 nearest≤latest, stale 0)

재생성: `python3 quick_capture/plot_sync_gap.py` (단, 스크립트는 기본적으로
`quick_capture_data/session_*/sync_log.csv`를 읽으므로, 이 폴더의 CSV로 분석하려면 경로를 맞춰야 함)
