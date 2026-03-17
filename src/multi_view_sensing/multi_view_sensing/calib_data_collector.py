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
        self.target_cam_idx = 0 
        self.prev_time = 0  # FPS 계산용 이전 시간
        
        self.save_path = os.path.expanduser(f'~/pest_control_ws/calib_data/cam{self.target_cam_idx}')
        os.makedirs(self.save_path, exist_ok=True)

        self.cap = cv2.VideoCapture(self.target_cam_idx, cv2.CAP_V4L2)
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        self.timer = self.create_timer(0.01, self.timer_callback) # 최대한 빠르게 루프
        self.win_name = f'Cam {self.target_cam_idx} Calib (C: Capture, Q: Quit)'
        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)


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

        # 1. FPS 계산
        curr_time = time.time()
        sec = curr_time - self.prev_time
        self.prev_time = curr_time
        fps = 1 / sec if sec > 0 else 0

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