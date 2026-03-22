import rclpy
from rclpy.node import Node
import cv2
import numpy as np
import os
import time  # 시간 측정을 위해 추가
from datetime import datetime

class SingleCalibCollector(Node):
    def __init__(self):
        super().__init__('single_calib_collector')
        
        self.checkerboard = (7, 10) 
        self.prev_time = 0 

        # [기존 기능 유지] FPS 계산을 위한 프레임 저장소
        self.frame_times = []
        self.window_size = 30 
        
        # --- [교정 포인트 1] 파라미터로 카메라 경로 받기 ---
        # 이제 숫자 0이 아니라 '/dev/cam0' 같은 이름을 사용합니다.
        self.declare_parameter('device_path', '/dev/cam0')
        self.device_path = self.get_parameter('device_path').get_parameter_value().string_value
        # -----------------------------------------------

        # [교정 포인트 2] 저장 경로 자동 설정
        # /dev/cam0 에서 마지막 'cam0'만 잘라내서 폴더 이름으로 씁니다.
        folder_name = self.device_path.split('/')[-1]
        self.save_path = os.path.expanduser(f'~/pest_control_ws/calib_data/{folder_name}')
        os.makedirs(self.save_path, exist_ok=True)

        # [교정 포인트 3] 카메라 열기 및 설정
        # 장치 경로(self.device_path)를 사용하여 카메라를 켭니다.
        self.cap = cv2.VideoCapture(self.device_path, cv2.CAP_V4L2)
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        self.timer = self.create_timer(0.01, self.timer_callback) 
        
        # [교정 포인트 4] 윈도우 이름 변경
        self.win_name = f'{folder_name} Calib (C: Capture, Q: Quit)'
        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)

        self.get_logger().info(f'>>> 현재 [{self.device_path}] 카메라가 준비되었습니다!')


    def draw_grid(self, frame):
        # 9등분 격자 그리기 (화면 높이/너비의 1/3, 2/3 지점)
        h, w = frame.shape[:2]
        color = (100, 100, 100) # 회색 선
        thickness = 1

        # 세로선
        cv2.line(frame, (int(w/3), 0), (int(w/3), h), color, thickness)
        cv2.line(frame, (int(2*w/3), 0), (int(2*w/3), h), color, thickness)
        
        # 가로선
        cv2.line(frame, (0, int(h/3)), (w, int(h/3)), color, thickness)
        cv2.line(frame, (0, int(2*h/3)), (w, int(2*h/3)), color, thickness)   

    def timer_callback(self):
        ret, frame = self.cap.read()
        if not ret: return

       # 1. 정밀 FPS 계산 (이동 평균 방식)
        curr_time = time.time()
        
        # 첫 프레임이 아닐 때만 계산
        if self.prev_time > 0:
            sec = curr_time - self.prev_time
            self.frame_times.append(sec)
            
            # 바구니 크기를 30개로 유지 (오래된 데이터는 버림)
            if len(self.frame_times) > self.window_size:
                self.frame_times.pop(0)
            
            # 평균 시간 계산 및 FPS 산출
            avg_sec = sum(self.frame_times) / len(self.frame_times)
            fps = 1 / avg_sec if avg_sec > 0 else 0
        else:
            fps = 0

        self.prev_time = curr_time

        display_frame = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        self.draw_grid(display_frame)  # 격자 그리기 (성능 영향 미비)
        
        # 2. 체커보드 인식 (여기가 부하의 중심!)
        ret_corners, corners = cv2.findChessboardCorners(gray, self.checkerboard, None)
        if ret_corners:
            cv2.drawChessboardCorners(display_frame, self.checkerboard, corners, ret_corners)
        
        # 3. FPS 화면 출력 (성능 영향 미비)
        cv2.putText(display_frame, f"FPS: {fps:.1f}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 2)
        
        cv2.imshow(self.win_name, display_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('c'):
            ts = datetime.now().strftime('%H%M%S')
            cv2.imwrite(os.path.join(self.save_path, f'calib_{ts}.jpg'), frame)
            self.get_logger().info(f'Captured! FPS was {fps:.1f}')
        elif key == ord('q'):
            rclpy.shutdown()

    def __del__(self):
        if self.cap.isOpened(): self.cap.release()
        cv2.destroyAllWindows()

def main(args=None):
    rclpy.init(args=args)
    node = SingleCalibCollector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()