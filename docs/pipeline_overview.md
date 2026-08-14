# 무인방제 데이터 파이프라인 개요

Ranger mini 탑재 시스템의 데이터 흐름과 담당 영역 구분.

흐름도: [diagrams/pipeline_flow.png](../diagrams/pipeline_flow.png)

---

## 1. 데이터 흐름

```
Ranger mini
 ├─ [본체 파이프라인]
 │   다중 카메라 (RGB 4EA)
 │     → 시간 동기화 · 공간 정합          ← 별도 갈래가 아니라 취득의 앞단
 │       → 이미지 데이터 취득 시스템
 │         → raw_data
 │            ├→ 딸기 병해충 추론 모델 → labelled_data ┐
 │            │                                        ├→ API 업로드 → HK 솔루션즈 서버
 │            └────────────────────────────────────────┘   (raw_data도 직접 업로드)
 │
 └─ [SLAM — 선택 영역, 본체 구현 후 착수]
     LiDAR(Livox) + RGB-Depth(D455) + IMU
       → SLAM → Visual SLAM / LiDAR SLAM / Multi-modal(Vision+LiDAR+IMU)
```

**`raw_data`는 추론을 거치지 않고도 서버로 간다.** 취득과 추론이 분리되어 있어,
추론이 실패해도 원본 이미지는 업로드된다.

---

## 2. 담당 4영역

| # | 영역 | 주요 파일 |
|---|---|---|
| 1 | **시스템** — 시간 동기화, 공간 정합 | `src/multi_view_sensing/`, `calib_params/` |
| 2 | **다중 이미지 취득** | `quick_capture/field_capture/` |
| 3 | **딸기 병해충 추론 모델** | `~/pest_control_model/aihub_yolov3/` |
| 4 | **데이터 서버 업로드** | `quick_capture/uploader.py`, `hks_agrix_ext_client.py` |

---

## 3. 영역별 상세

### ① 시스템

4채널 카메라의 시간 정합(같은 시각에 찍힌 4장을 한 묶음으로 저장)과 공간 정합
(카메라 간 상대 자세). 물리 배치·기하 실측값은 [camera_rig_geometry.md](camera_rig_geometry.md) 참조.

### ② 다중 이미지 취득

촬영 트리거 방식에 따라 세 가지를 병행 유지한다. 서로 대체 가능한 전략이므로
브랜치가 아니라 **파일로 분리**해 같은 조건에서 비교한다.

| 플랜 | 방식 | 상태 |
|---|---|---|
| **A** | 주행 거리 기반 — 오도메트리로 일정 거리마다 촬영 | 미구현 (본선 후보) |
| **B** | 정지 → 촬영 → 이동 반복 | 미구현 (품질 기준선 용도) |
| **C** | 시간 주기 — 일정 시간마다 촬영 | `field_capture/recorder.py` |

**blur의 원인은 촬영 주기가 아니다.**

```
흐림 길이(픽셀) ≈ 로봇 속도(m/s) × 노출시간(s) ÷ 지상분해능(m/픽셀)
```

주기를 낮춰도 개별 이미지의 흐림은 그대로다. 플랜 A가 해결하는 것은 blur가 아니라
**촬영 간격 불균일에서 오는 중복·누락**이다. blur에는 노출 시간 고정과 선명도 게이트
(라플라시안 분산 기준 프레임 선택)가 직접적인 대책이다.

플랜 A의 전제 조건: Jetson에서 Ranger mini 드라이버가 실행되어 `/odom`이 발행되어야 하며,
바퀴 미끄러짐에 따른 오차를 실측으로 확인해야 한다.

### ③ 딸기 병해충 추론 모델

AI Hub 배포 모델을 사용한다. **자체 학습 모델은 실증 라벨 데이터 확보 전까지 보류한다.**

| 항목 | 내용 |
|---|---|
| 출처 | AI Hub「시설작물(딸기) 개체 이미지 및 시설작물(딸기) 질병 이미지」 |
| 아키텍처 | YOLOv3 (Ultralytics 2021년경 코드베이스) |
| 클래스 | 2개 — `유`(질병 있음) / `무`(질병 없음). **병명 구분 없음** |
| 가중치 | `~/pest_control_model/aihub_yolov3/weights/strawberry/best.pt` |

실증 이미지 라벨링은 타 기관에서 수행 예정이다. 라벨이 확보되면 이 모델을 출발점으로
미세조정(fine-tuning)이 가능하다.

### ④ 데이터 서버 업로드

HK 솔루션즈 Agrix 플랫폼. 규격·인증·오류 대응은 [agrix_api.md](agrix_api.md) 참조.

### SLAM (선택 영역)

본체 파이프라인 구현 후 착수. 자율주행(D455+IMU+Livox → Jetson Orin, 맵 기반 라인
진입·복귀, 장애물 회피)은 팀원 담당 영역이다.

---

## 4. 배치

| 기계 | 역할 |
|---|---|
| **NUC O** (`FIRANUC1`) | 학습·분석. AI Hub 원본 데이터셋(251GB), 학습 데이터셋(21GB) 보관 |
| **NUC R** (`FIRANUC`) | 로봇 탑재. 취득·추론·업로드 실행 |
| Jetson | 자율주행·SLAM (팀원 담당). Ranger mini와 CAN 연결 |

NUC R과 Jetson은 ipTIME 유선 랜(로봇망, 인터넷 없음)으로 연결된다. NUC R의 무선은
사무실 AP를 통해 인터넷에 연결된다. 두 인터페이스가 같은 `192.168.0.x` 대역이므로
외부에서 NUC R에 접속할 때는 Tailscale을 쓴다.
