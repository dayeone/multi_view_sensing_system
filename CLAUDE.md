# CLAUDE.md

본 문서는 Claude Code가 매 세션 시작 시 자동 로드하는 프로젝트 컨텍스트이다. 본 문서의 규칙을 다른 모든 지시보다 우선 준수한다. git에 commit되어 공유되므로 비밀 정보를 절대 포함하지 않는다.

## 프로젝트 개요

ROS 2 Humble (Python / ament_python) 워크스페이스. 4채널 Logitech BRIO 카메라(`/dev/video0`, `/dev/video4`, `/dev/video8`, `/dev/video12`)를 사용한 다중 시점 병해충 방제 센싱 시스템. 환경: Ubuntu 22.04, Python 3.10. 단일 패키지 `multi_view_sensing` (`src/multi_view_sensing/`).

## 보안 규칙

다음 작업은 사용자의 명시적 승인 없이 수행하지 않는다.

- `.env`, `.env.*`, `*.key`, `*.pem`, `*.crt`, `id_rsa*`, `id_ed25519*` 파일을 읽거나 commit하지 않는다.
- API 키, 비밀번호, 토큰, Tailscale auth key, GitHub PAT를 코드·주석·로그·stdout에 노출하지 않는다.
- 비밀 패턴(`sk-`, `ghp_`, `xoxb-`, `tskey-`, `AKIA[0-9A-Z]{16}`)을 commit하지 않는다.
- `sudo`, `rm -rf`, `git push --force`, `git reset --hard`는 직접 실행하지 않고 사용자에게 명령어만 제시한다.
- `main` 브랜치에 직접 commit하거나 push하지 않는다.
- 검증되지 않은 외부 패키지(pip/npm/apt)를 자동 설치하지 않는다. 이름·버전·출처를 보고하고 승인을 대기한다.
- `curl ... | bash` 같은 파이프 실행 패턴을 사용하지 않는다.
- 외부 API에 코드·데이터·로그를 사전 동의 없이 전송하지 않는다.

매 commit 전 `git diff --staged`로 위 항목 노출 여부를 확인한다.

## 보호 경로

다음 경로는 수정 시 사용자 승인이 필요하다.

`.git/`, `.ssh/`, `~/.config/tailscale/`, `secrets/`, `credentials/`, `private/`, `node_modules/`, `__pycache__/`, `venv/`, `.venv/`, `build/`, `install/`, `log/`, `*.lock`

## 수정 금지 코드

- `calib_data_collector.py`: SubPix 영역 일체. 0.5× downscale → `findChessboardCorners` → full-res `cornerSubPix` 파이프라인 baseline 검증 완료.
- `calib_calc.py`, `calib_viewer.py`: 현재 안정 상태. 변경 사유가 명시되지 않으면 수정하지 않는다.

수정 가능: `camera_streamer.py` (namedWindow 중복 및 win_name overwrite 버그 수정 작업 중).

## 응급 확인 키워드

사용자 메시지에 "배포", "deploy", "production", "삭제", "drop", "공개", "public", "force", "강제", "전체", "all files" 중 하나가 포함되면 작업 전 의도를 재확인한다.

## 빌드 및 실행 명령어

```bash
# ROS 2 환경 source
source /opt/ros/humble/setup.bash

# 빌드
cd ~/pest_control_ws
colcon build --packages-select multi_view_sensing

# 워크스페이스 overlay source
source install/setup.bash

# 개별 노드 실행
ros2 run multi_view_sensing streamer
ros2 run multi_view_sensing calib_collector --ros-args -p device_path:=/dev/video0 -p display_mode:=local
ros2 run multi_view_sensing multi_view_remote_publisher --ros-args -p display_mode:=local

# 4채널 캘리브레이션 collector 일괄 실행
ros2 launch multi_view_sensing multi_cam.launch.py
ros2 launch multi_view_sensing multi_cam.launch.py enable_metrics_log:=true

# Multi-view remote publisher (2x2 그리드)
ros2 launch multi_view_sensing multi_view_remote.launch.py display_mode:=local
ros2 launch multi_view_sensing multi_view_remote.launch.py display_mode:=remote

# 캘리브레이션 계산 (스탠드얼론 스크립트, 파일 내 cam_idx 수정)
python3 src/multi_view_sensing/multi_view_sensing/calib_calc.py

# 테스트
colcon test --packages-select multi_view_sensing
colcon test-result --verbose
```

## 아키텍처

### 노드 (`setup.py` 진입점 정의)

- **`streamer`** → `camera_streamer.py:MultiCameraLite`: 4채널 단순 뷰어. 인덱스 0,4,8,12로 카메라 오픈, OpenCV로 2x2 그리드 표시. `s` 키로 스냅샷 저장.
- **`calib_collector`** → `calib_data_collector.py:SingleCalibCollector`: 채널별 캘리브레이션 이미지 수집기. 7x10 체커보드 실시간 검출. `local` (OpenCV 윈도우) / `remote` (`{device}/image_compressed` 토픽 발행) 두 모드 지원. GStreamer/NVDEC GPU 모드 지원. 백그라운드 캡처 스레드 + 100Hz 타이머 콜백 검출. `c` 키 또는 `{device}/capture_cmd` 토픽으로 캡처 트리거.
- **`multi_view_remote_publisher`** → `multi_view_remote_publisher.py:MultiViewRemotePublisher`: 4채널 멀티스레드 publisher. 카메라당 3-tier 스레드(capture → detect → 메인 타이머 15Hz 합성). `/multi_view/image_compressed` 발행. 스레드별 FPS(capture/detect/publish), latency, 카메라 간 sync gap 추적.

### 스탠드얼론 스크립트

- **`calib_calc.py`**: 오프라인 캘리브레이션 계산기. `calib_data/cam{N}/`의 체커보드 이미지를 읽어 `cv2.calibrateCamera()` 실행. 이미지별 reprojection error 출력 후 `calib_params/cam{N}_params.yaml`에 카메라 매트릭스·왜곡 계수 저장.
- **`calib_viewer.py:CalibViewer`**: 저장된 캘리브레이션 파라미터 기반 원본·undistorted 비교 뷰.

### 데이터 디렉토리

- `calib_data/`: 채널별 원본 캘리브레이션 이미지 (`cam0/`–`cam3/`, `video0/`–`video12/`)
- `calib_params/`: YAML 캘리브레이션 결과 (`cam{N}_params.yaml`, 키: `camera_matrix`, `dist_coeff`, `rms_error`)
- `captured_images/`: streamer 노드 스냅샷
- `metrics_logs/`: CSV 성능 로그 (cap/det/pub FPS, latency, sync gap)

### 스레딩 모델

`SingleCalibCollector`와 `MultiViewRemotePublisher`는 producer-consumer 패턴 사용. `queue.Queue(maxsize=1)`로 카메라 캡처와 처리를 분리. 각 스레드는 1초 윈도우로 자체 FPS 계산, `fps_lock` 하에 공유 변수에 기록.

### 주요 파라미터

| 파라미터 | 노드 | 기본값 | 설명 |
|---|---|---|---|
| `device_path` / `device_paths` | calib_collector / multi_view | `/dev/video0` / `[0,4,8,12]` | 카메라 디바이스 |
| `display_mode` | both | `remote` / `local` | `local` = OpenCV 윈도우, `remote` = ROS 토픽 |
| `jpeg_quality` | multi_view | 70 | JPEG 압축 품질 |
| `enable_metrics_log` | both | false | CSV 성능 로그 활성화 |
| `use_gpu` | calib_collector | false | GStreamer/NVDEC 파이프라인 사용 |

## 컨벤션

- 코드 주석과 로그 메시지는 한국어 우선
- 체커보드: 7x10 internal corner, 15mm square
- 카메라 해상도: 1280x720, MJPG 코덱
- 체커보드 검출은 0.5× downscale 후 좌표 역스케일 (수정 금지 영역 참고)
- 디스플레이 합성: 카메라당 480x270, 전체 그리드 960x540

## Git 워크플로우

- 모든 작업은 feature 브랜치에서 진행한다: `feature/<설명>`, `fix/<설명>`, `docs/<설명>`, `refactor/<설명>`.
- Commit 형식: `<type>(<scope>): <설명>`. type은 feat, fix, docs, refactor, test, chore 중 하나.
- main 브랜치 머지 및 push는 사용자 명시 승인 후에만 진행한다.

## 기술 스택

Python 3.10 (PEP 8, type hint 사용), ROS 2 Humble (ament_python), OpenCV. 워크스페이스 빌드는 `colcon build --symlink-install` 권장 (개발 시).

## 응답 스타일

- 한국어 존댓말로 응답한다.
- 개조식(bullet point) 형식으로 출력한다.
- Claude Code가 필요한 경우 VS Code 확장과 터미널 CLI 중 더 적합한 쪽을 사전에 안내한다.
- 코드 변경 시 commit이 필요하면 사용자에게 명시적으로 제안한다.
- 다중 대안보다 단일 actionable 추천을 우선한다.
- IPC, serialization, 대역폭 등 근본 원인 설명을 선호한다. 표면적 코딩 가이드는 피한다.
- 이모티콘과 불필요한 장식 요소를 사용하지 않는다.

## 모호한 경우

- 의도가 불분명하면 추측하지 않고 질문한다.
- 보안 관련 의사결정은 보수적인 쪽(더 제한적)을 선택한다.
- 다중 파일 대규모 변경 전 계획을 보고하고 승인을 대기한다.
- 외부 라이브러리 추가 전 이름·버전·출처·라이선스를 보고한다.
