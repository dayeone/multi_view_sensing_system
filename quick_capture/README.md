# Quick Capture — 4채널 멀티뷰 캡처 + 서버 업로드 (MVP)

무인방제 로봇 실증 농가 데이터 취득용 최소 기능 구현.
4채널 Logitech BRIO 동시 캡처 → 디스크 저장 → HKS Agrix 서버 업로드.

작성: 2026-05-26

---

## 폴더 구조

```
quick_capture/
├── recorder.py              # 4채널 캡처 + 토글 + 저장
├── uploader.py              # 명시한 세션만 서버 업로드
├── hks_agrix_ext_client.py  # HKS Agrix API 클라이언트 (업체 제공, 재사용)
├── .env                     # 인증키 (git 제외)
└── README.md

../quick_capture_data/        # 캡처 데이터 (git 제외)
└── session_YYYYMMDD_HHMMSS/
    ├── sync_log.csv          # 세트별 sync gap(ms)·카메라별 age·stale 기록
    ├── cam1/                 # 물리 위치 기준(cam1=좌하 … cam4=우상, /dev/cam1~4)
    │   ├── set000000_cam1_<timestamp>.jpg
    │   ├── uploaded/        # 업로드 성공 후 이동
    │   └── failed/          # 업로드 실패 격리
    ├── cam2/
    ├── cam3/
    └── cam4/
```

> 폴더명은 이제 **물리 위치 기준 cam1~4**이다. 예전의 `cam0/4/8/12`(비디오 인덱스 기준)에서
> udev 심볼릭 링크(`/dev/cam1~4`) 기반으로 전환됨.

---

## 사용법

### 1. 카메라 캡처 (recorder.py)

기본 실행 (2 Hz):
```bash
cd ~/pest_control_ws
python3 quick_capture/recorder.py
```

캡처 주기 변경:
```bash
python3 recorder.py --hz 1      # 1 Hz
python3 recorder.py --hz 0.5    # 2초당 1장
```

실행 중 명령어:
- `s` : 새 세션 시작 (`session_<timestamp>/` 자동 생성)
- `t` : 캡처 중지 (저장된 프레임 수 출력)
- `q` : 프로그램 종료

### 2. 서버 업로드 (uploader.py)

명시한 세션 폴더만 업로드:
```bash
python3 uploader.py ~/pest_control_ws/quick_capture_data/session_20260526_103000
```

- 시작 전 `yes` 입력 확인 (오업로드 방지)
- 자동 폴더 감시 기능 **없음** (의도치 않은 업로드 방지 목적)
- 성공 시 `uploaded/` 하위로 이동
- 3회 재시도 실패 시 `failed/` 하위로 격리

---

## 시스템 구성

- **카메라**: Logitech BRIO × 4 (`/dev/cam1~4`, udev 시리얼 심볼릭 링크, 1280×720 MJPG)
- **API**: HKS Agrix HMAC-SHA256, 2단계 업로드 (file → imageset)
- **인증**: `.env` 파일의 `ACCESS_KEY`, `SECRET_KEY`, `AIDATASET_ID`

---

## 주의사항

- **`.env` 파일은 절대 git에 commit 금지** (`.gitignore` 등록됨)
- USB 포트 순서가 바뀌면 `/dev/videoN`과 물리 카메라 매핑이 어긋날 수 있음
  - 확인: `v4l2-ctl --list-devices`
- 핫스팟 사용 시 데이터 사용량 주의 (1280×720 JPG 1장 ≈ 100~300KB)
- 본 폴더는 기존 `src/`, `captured_images/` 등과 완전 분리됨 (의도적)

---

## 미구현 / 차후 작업

- 실시간 4채널 미리보기 (cv2.imshow 2×2 그리드)
- 데이터 검증 메타데이터 (블러 분산, 밝기 통계)
- 공간 정합 (캘리브 파라미터 활용 후처리)
- MQTT 텔레메트리 (`../data_server_upload_system/mqtt_test.py` 참고)
- ROS 2 노드화 (기존 `pest_control_ws` 통합)