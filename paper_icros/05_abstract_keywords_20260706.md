# 요약 및 키워드

## 국문 요약

스마트팜 딸기 재배에서는 잎과 과실의 겹침으로 단일 시점 영상만으로 병해충 및 생리장해를 안정적으로 관측하기 어렵다. 본 연구는 저가 RGB 카메라 4대를 수직 지주에 좌·우 2대씩 배치한 다중 시점 이미지 취득 시스템을 제안한다. 각 카메라는 생산자-소비자 구조로 최신 프레임을 공유하고, 단일 매처가 동일 묶음 번호로 영상을 저장하여 시간 동기화를 수행한다. 또한 체커보드 기반 내부 보정과 같은 면의 스테레오 보정을 통해 공간 정합을 수행한다. 실험 결과 카메라별 내부 보정 RMS는 [측정 후 기재] px 수준이며, 외부 보정을 통해 같은 재배 라인을 관측하는 상·하 시점을 공통 좌표계로 정렬한다. 제안 시스템은 딸기 재배 라인의 다중 시점을 일관되게 결합하여 가림을 완화하는 작물 관측 기반을 제공한다.

**키워드:** 스마트팜, 다중 시점 영상, 시간 동기화, 공간 정합, 딸기 병해충 진단

## English Abstract

In smart farm strawberry cultivation, leaves and fruits often overlap, and a single-view image cannot observe disease, pest, or physiological disorder symptoms in a stable manner. This study proposes a multi-view RGB image acquisition system for crop observation using four low-cost cameras. The cameras are mounted on a vertical support, with two cameras assigned to the left cultivation line and two cameras assigned to the right cultivation line. On each side, the upper and lower cameras observe the same line from different vertical angles, so that one view can complement regions occluded in another view. To acquire consistent multi-camera data, the system applies a producer-consumer structure. Each camera thread continuously captures frames and updates its latest frame with a timestamp, while a single matcher reads the four latest frames at a fixed interval and saves them with the same set number. This structure keeps the four camera images grouped as one acquisition set. For spatial registration, the system estimates intrinsic parameters using checkerboard images with fixed focus and performs stereo calibration for the two cameras on the same side. The intrinsic calibration RMS error of each camera is [to be measured] px, and the extrinsic calibration aligns the upper and lower views observing the same cultivation line into a common coordinate system. These results indicate that the proposed system provides a practical basis for combining multiple RGB views of strawberry cultivation lines and reducing occlusion in crop observation.

**Keywords:** Smart Farm, Multi-View Image, Time Synchronization, Spatial Registration, Strawberry Disease and Pest Diagnosis
