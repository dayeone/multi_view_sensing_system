# health_classifier — 딸기 정상/이상 이진 판정 (병해충·생리장해 유무)

무인방제 과제의 이미지 판정 파트. 취득 이미지에서 딸기에 **병해충 또는 생리장해가 있는지 없는지**만
판정하는 로우레벨 베이스라인이다. 세부 10종(병해충 5 + 생리장해 5) 분류는 후순위이며, 본 모듈은
정상(normal) vs 이상(abnormal) **이진 분류**만 다룬다.

작성: 2026-07-16

---

## 접근 (v1 = 구조 B: 병해 검출)

실증 사진은 라인주행 광각(잎·열매 혼재)이라, 사진을 통째로 분류하는 방식(구조 A)은
부적합하다. 대신 **병든 부위를 직접 찾는 검출 모델**을 쓴다.

- 사진 전체를 훑어 **병든 부위에 박스**를 친다. 하나라도 찾으면 "이상 있음"(유무 판정).
- 모델: COCO 사전학습 **YOLO11(detect)** 를 전북대 병해 데이터로 미세조정. 단일 클래스 `disease`.
- 낱개 자르기(부위 검출) 불필요 → 검출기가 위치까지 스스로 찾음.
- 학습 스택은 conda `strawberry` 환경(ultralytics 8.4.64, torch 2.12+cu130)에 이미 존재.

파이프라인: `download_datasets.py --only jbnu_disease` → `datasets/build_yolo_detect.py` → `train.py`

### v1 한계 (기록)

- **정상(건강) 이미지 0장**: 전북대 데이터는 7개 병해뿐이라 음성 샘플이 없다. 헛경보(오탐)가
  늘 수 있다. → v1.1에서 실증 정상 사진(도메인 일치)을 음성 샘플로 추가 권장.
- **생리장해 미포함**: 결핍류(붕소·칼륨·철)는 잎 전체 변색이라 검출로 표현 불가. 별도 분류 트랙 필요.

### 구조 A (참고, 현재 미사용)

`build_binary.py`는 초기 구조 A(정상/이상 이진 분류) 산출물이며 v1에서는 사용하지 않는다.

## 데이터 현실 (근본 제약)

- **병해충**: 오픈소스 충분 (JBNU 데이터셋, 7병해 + healthy)
- **생리장해**: 오픈소스 거의 없음. tipburn(칼슘결핍) 1종만 공개 → 나머지 4종은 지도학습으로 못 채움
- **도메인 갭**: 오픈소스 이미지 ≠ BRIO 1280×720 온실 촬영본. 실사용 정확도는 벤치마크보다 낮게 나옴이 정상
  → 자체 rig 촬영본 50~100장을 라벨링해 별도 검증셋(`datasets/raw/own_val/`)으로 실측할 것

## 사용 데이터셋

| key | 출처 | 규모 | 라이선스 |
|---|---|---|---|
| `jbnu_disease` | Kaggle `usmanafzaal/strawberry-disease-detection-dataset` (JBNU) | 2,500장, 8클래스(7병해+healthy), segmentation | 관대(수정·병합 허용) |
| `tipburn` | Kaggle `ercanavsar/images-of-strawberry-leaves-for-tipburn-detection` (Mendeley 미러) | 1,431장, healthy vs 칼슘결핍 | Mendeley Data, 인용: Hariri & Avşar (2022) |

## 폴더 구조

```
health_classifier/
├── README.md
├── .gitignore
├── requirements.txt                # 추가 필요 패키지 (kagglehub 뿐)
├── datasets/
│   ├── download_datasets.py        # 오픈소스 취득 (kagglehub 또는 수동 zip)
│   ├── build_binary.py             # 원본 → normal/abnormal 이진 재라벨 + YOLO-cls 구조
│   ├── raw/                        # 다운로드 원본 (git 제외)
│   │   ├── jbnu_disease/
│   │   ├── tipburn/
│   │   └── own_val/                # (권장) 자체 rig 검증셋 수동 배치
│   └── binary/                     # train/val/{normal,abnormal} (git 제외)
├── train.py                        # (다음 단계) YOLO11-cls 전이학습
└── classify_strawberry.py          # (다음 단계) 2-스테이지 추론
```

## 진행 순서

### 1) 데이터 취득 (승인 필요: 외부 다운로드 + pip 설치)

```bash
conda activate strawberry

# kagglehub 설치 (승인 후) — Apache-2.0, PyPI(Kaggle/Google 배포)
pip install kagglehub

# Kaggle 인증 토큰 배치: kaggle.com 계정 > Settings > API > "Create New Token"
#   → 내려받은 kaggle.json 을 ~/.config/kaggle/kaggle.json 에 저장 (chmod 600)

# 두 데이터셋 취득 → datasets/raw/<key>/ 에 연결
python3 datasets/download_datasets.py --all
```

인증 없이 진행하려면 브라우저로 각 데이터셋 zip을 받아 `datasets/raw/_zips/`에 넣고:

```bash
python3 datasets/download_datasets.py --manual
```

### 2) 이진 데이터셋 빌드 (오프라인, 승인 불필요)

```bash
python3 datasets/build_binary.py
# datasets/binary/train,val/{normal,abnormal}/ 생성. 클래스 분포 리포트 출력
```

### 3) 학습·추론 (다음 단계에서 스크립트 작성)

```bash
python3 train.py                 # YOLO11-cls 전이학습
python3 classify_strawberry.py --session <세션폴더>   # 2-스테이지 판정
```

## 주의

- `datasets/raw/`, `datasets/binary/`, `models/`, 학습 산출물은 `.gitignore`로 제외 (용량·저작권)
- 데이터셋 라이선스·인용 요건은 논문/보고서에 반드시 명시
- 실사용 배포 전 자체 rig 검증셋으로 정확도 실측 (도메인 갭)
