# health_classifier — 딸기 정상/이상 이진 판정 (병해충·생리장해 유무)

무인방제 과제의 이미지 판정 파트. 취득 이미지에서 딸기에 **병해충 또는 생리장해가 있는지 없는지**만
판정하는 로우레벨 베이스라인이다. 세부 10종(병해충 5 + 생리장해 5) 분류는 후순위이며, 본 모듈은
정상(normal) vs 이상(abnormal) **이진 분류**만 다룬다.

작성: 2026-07-16

---

## 접근 (2-스테이지)

1. **검출(기존 자산 재활용)**: `../quick_capture/models/strawberry_yolo11s.pt`로 과실/잎 ROI 검출 → crop
2. **분류(본 모듈)**: crop을 `normal / abnormal` 이진 분류. ultralytics **YOLO11-cls** 전이학습
   - 학습 스택은 conda `strawberry` 환경(ultralytics 8.4.64, torch 2.12+cu130)에 이미 존재 → 신규 패키지 불필요
   - 데이터 취득에만 `kagglehub` 필요

향후 분류 헤드를 10종으로 확장할 수 있도록 이진은 "1단계"로만 취급한다.

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
