# NUC2 환경 구축 · 배포 계획서 (딸기 병해 검출 v1)

목적: NUC1에서 만든 병해 검출 모델(`best.pt`)과 추론 코드를 **NUC2(Ranger mini)** 에서 실행.
전제: NUC2 = RTX 5070(Blackwell), **드라이버 595 설치됨**(570+ 요구 충족, CUDA 13 지원). NUC1은 추후 포맷.

목표 환경(NUC1 `strawberry`와 동일):
- python 3.10, torch 2.12.0+cu130, torchvision 0.27.0+cu130, ultralytics 8.4.64, opencv

---

## 0. NUC1 자산 보존 (포맷 전 반드시)

NUC1을 포맷하면 아래는 사라진다. 먼저 옮긴다.

- **코드**: git 원격에 push. (best.pt·데이터는 git 미포함)
  ```bash
  # NUC1
  cd ~/pest_control_ws
  git push -u origin feature/health-classifier
  git push origin main   # 필요 시
  ```
- **모델 파일 best.pt**: git 미추적이므로 별도 복사. (택1)
  - NUC2로 직접 복사: `scp ~/pest_control_ws/health_classifier/runs/detect/disease_b_v1/weights/best.pt <NUC2계정>@<NUC2IP>:~/`
  - 또는 외장하드에 복사 보관.
- **데이터셋**: 보존 불필요(오픈소스라 NUC2에서 재다운로드 가능).

---

## 1. NUC2 현재 상태 파악

```bash
# NUC2 터미널
bash nuc2_manifest.sh          # 전체 인벤토리 → ~/nuc2_manifest/

# 빠른 개별 확인
nvidia-smi                     # 드라이버 595 / RTX 5070 인식 확인
python3 --version              # 시스템 파이썬
which conda && conda --version # conda 설치 여부
conda env list                 # strawberry 환경 존재 여부(대개 없음 → 2단계에서 생성)
dpkg -l | grep -i ros          # ROS 설치 여부
```

예상: NUC2는 납품 상태라 conda/torch/ultralytics는 **없을 가능성이 큼** → 2단계에서 구축.

---

## 2. NUC2 환경 구축

### 2-1. GPU 드라이버
- 이미 595 설치됨. `nvidia-smi`가 GPU를 보여주면 통과. (재설치 불필요)

### 2-2. conda 설치 (없을 경우)
```bash
# Miniforge 설치 파일 다운로드 후 실행 (curl|bash 파이프 금지)
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh
# 셸 재시작 후 conda 사용 가능
```

### 2-3. strawberry 환경 생성 + 라이브러리 설치
```bash
conda create -n strawberry python=3.10 -y
conda activate strawberry

# torch(Blackwell/CUDA13 대응) — NUC1과 동일 버전
pip install torch==2.12.0 torchvision==0.27.0 --index-url https://download.pytorch.org/whl/cu130

# 추론/학습 라이브러리
pip install ultralytics==8.4.64
```

### 2-4. 설치 검증 (가장 중요)
```bash
python -c "import torch; print('cuda:', torch.cuda.is_available()); print('gpu:', torch.cuda.get_device_name(0))"
# 기대: cuda: True / gpu: NVIDIA GeForce RTX 5070 ...
python -c "import ultralytics; print('ultralytics', ultralytics.__version__)"
```
- `cuda: True`가 안 나오면 torch 버전과 드라이버 조합 문제 → torch 재설치(위 index-url 확인).
- 정확한 버전 대조가 필요하면 저장소의 `setup/nuc1_strawberry_env.txt`(NUC1 pip freeze) 참고.

---

## 3. 코드·모델 이식

```bash
# NUC2
git clone git@github.com:HANGANG12/multi_view_sensing_system.git ~/pest_control_ws
cd ~/pest_control_ws
git checkout feature/health-classifier

# best.pt 배치 (0단계에서 복사해 둔 파일)
mkdir -p health_classifier/models
cp ~/best.pt health_classifier/models/disease_b_v1.pt
```

---

## 4. 추론 재현 검증

```bash
conda activate strawberry
cd ~/pest_control_ws/health_classifier
# (classify_strawberry.py 는 NUC1에서 작성 후 커밋 예정)
python classify_strawberry.py --weights models/disease_b_v1.pt --input <딸기사진폴더>
```
- 실증 사진 몇 장으로 "병해 유무/위치"가 출력되면 배포 성공.

---

## 선택: NUC2에서 재학습 (스펙이 더 좋음)

NUC2 환경이 갖춰지면 학습도 NUC2에서 가능(RTX 5070이 더 빠름). 향후 실증 데이터로 재학습 시:
```bash
cd ~/pest_control_ws/health_classifier
python datasets/download_datasets.py --only jbnu_disease
python datasets/build_yolo_detect.py
python train.py
```
즉 이 계획서대로 하면 NUC2가 **추론과 학습을 모두** 할 수 있어, NUC1 포맷 후에도 문제없다.

---

## 요약 체크리스트

- [ ] NUC1: `git push` (feature/health-classifier) + best.pt 복사
- [ ] NUC2: `nuc2_manifest.sh`로 상태 파악, `nvidia-smi` 확인
- [ ] NUC2: conda 설치 → strawberry 환경 생성 → torch/ultralytics 설치
- [ ] NUC2: `cuda: True` 검증
- [ ] NUC2: 코드 clone + best.pt 배치
- [ ] NUC2: 실증 사진으로 추론 재현 확인
