import cv2
import numpy as np
import glob
import os
import yaml

# 1. 설정 (재환님의 체커보드 정보)
CHECKERBOARD = (7, 10)  # 내부 코너 개수
SQUARE_SIZE = 15.0      # mm 단위
cam_idx = 0            # 테스트할 카메라 번호

# 3D 실제 좌표 설정 (0,0,0), (15,0,0), (30,0,0) ...
objp = np.zeros((CHECKERBOARD[0] * CHECKERBOARD[1], 3), np.float32)
objp[:, :2] = np.mgrid[0:CHECKERBOARD[0], 0:CHECKERBOARD[1]].T.reshape(-1, 2)
objp *= SQUARE_SIZE

objpoints = [] # 3D 실제 공간의 점들
imgpoints = [] # 2D 이미지 평면의 점들

# 2. 이미지 불러오기
images = glob.glob(os.path.expanduser(f'~/pest_control_ws/calib_data/cam{cam_idx}/*.jpg'))

if not images:
    print(f"이미지를 찾을 수 없습니다: cam{cam_idx} 폴더를 확인하세요.")
    exit()

print(f"{len(images)}장의 이미지를 분석합니다...")

for fname in images:
    img = cv2.imread(fname)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 코너 찾기
    ret, corners = cv2.findChessboardCorners(gray, CHECKERBOARD, None)

    if ret:
        objpoints.append(objp)
        # 서브픽셀 정밀도로 코너 위치 정교화
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        corners2 = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        imgpoints.append(corners2)
        print(f"인식 성공: {os.path.basename(fname)}")
    else:
        print(f"인식 실패: {os.path.basename(fname)}")

# 3. 캘리브레이션 계산 (마법의 함수)
print("계산 중... 잠시만 기다려주세요.")
ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(objpoints, imgpoints, gray.shape[::-1], None, None)

if ret:
    # 4. 결과 출력 및 저장
    print("\n[카메라 보정 완료]")
    print(f"재투영 오차(RMS Error): {ret:.4f}") # 1.0 미만이면 아주 훌륭합니다.
    
    # 결과를 dict 형태로 정리
    calib_data = {
        'camera_matrix': mtx.tolist(),
        'dist_coeff': dist.tolist(),
        'rms_error': float(ret)
    }

    # YAML 파일로 저장
    save_file = os.path.expanduser(f'~/pest_control_ws/cam{cam_idx}_params.yaml')
    with open(save_file, 'w') as f:
        yaml.dump(calib_data, f)
    
    print(f"결과가 저장되었습니다: {save_file}")