# 새 플랫폼 이전 체크리스트 (Ranger mini + 알루미늄 프로파일)

이 워크스페이스를 새 미니PC(동일 기종이나 다른 개체 + 다른 카메라)로 옮길 때 따라간다.
원칙: **코드/도구는 git으로 그대로 이전**, **하드웨어에 묶인 값(시리얼·초점·intrinsic)만 새로 측정**.

## A. 코드 가져오기 (git)
- [ ] (옛 PC) 최신 커밋 push: `git push origin feature/spatial-registration`
- [ ] (새 PC) 클론: `git clone git@github.com:HANGANG12/multi_view_sensing_system.git ~/pest_control_ws`
- [ ] (새 PC) 브랜치 체크아웃: `cd ~/pest_control_ws && git checkout feature/spatial-registration`
- [ ] 파이썬 의존성 확인/설치: opencv(cv2), numpy, pyyaml

## B. 클로드 코드 맥락(메모리) 이전
- [ ] (옛 PC→새 PC) 메모리 복사:
      `scp -r ~/.claude/projects/-home-jay-pest-control-ws/memory <새PC>:~/.claude/projects/-home-jay-pest-control-ws/memory`
- [ ] 새 PC에서 클로드 코드 실행 → `MEMORY.md` 로드로 맥락 이어지는지 확인
- [ ] (선택) 전체 대화 transcript까지 원하면 상위 폴더 `-home-jay-pest-control-ws` 통째 복사 (단, 다른 기계라 세션 resume은 보장 안 됨)

## C. 하드웨어값 재생성 (만들어둔 도구로 빠르게)

### C-1. 카메라 식별 (udev 시리얼)
- [ ] 새 카메라 시리얼 확인:
      `for n in /dev/video*; do echo -n "$n "; udevadm info -a -n $n | grep -m1 serial; done`
- [ ] `setup/udev/99-usb-cameras.rules`의 serial 4개를 새 값으로 교체 (cam1~4 ↔ 물리 위치 매핑 확인)
- [ ] 설치 + 적용:
      `sudo cp setup/udev/99-usb-cameras.rules /etc/udev/rules.d/`
      `sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=video4linux --action=add`
- [ ] `ls -l /dev/cam*` 로 cam1~4가 index0 캡처 노드를 가리키는지 + 영상 컬러·무깜빡임 확인

### C-2. 초점 재측정 (작업거리 변경됨)
- [ ] 보드를 작업거리에 고정 (평판, 안 휘게)
- [ ] cam1~4 각각: `python3 quick_capture/focus_finder.py --device /dev/camN`
- [ ] `config/camera_focus.yaml`을 새 추천값으로 갱신

### C-3. intrinsic 재캘리브레이션
- [ ] (필요시) 옛 calib_data 백업/비우기
- [ ] cam1~4 촬영: `python3 quick_capture/calib_capture.py --device /dev/camN`
      (평판 보드 / 전체 보임 / **모서리·가장자리까지 커버** / 적당한 각도 / 선명)
- [ ] 계산: `python3 src/multi_view_sensing/multi_view_sensing/calib_calc.py`
- [ ] RMS 확인 (목표 <1.0px, 가능하면 <0.8px)

## D. 다음 단계 (리그 본작업 — extrinsic = 공간 정합)
- [ ] extrinsic 측정: 면별(좌/우 2대)이 같은 평면 보드를 **동시에** 보게 → `stereoCalibrate` 등으로 상대 자세 계산
- [ ] 정합 검증 (재투영 오차 / 오버레이)
- [ ] recorder.py가 카메라별 초점(YAML)을 읽도록 보강

## 메모
- 시리얼·초점·intrinsic은 **새 개체/거리 기준**이라 옛 값 재사용 불가 → 위 C 단계 필수.
- 보드는 **평판에 단단히 부착**해 휘지 않게 (이전 cam2 오차의 주원인이 보드 휨).
