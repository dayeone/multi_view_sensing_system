import rclpy
from rclpy.node import Node
import cv2
import numpy as np
import yaml
import os

class CalibViewer(Node):
    def __init__(self):
        super().__init__('calib_viewer')
        
        # 1. 파라미터 로드
        yaml_path = os.path.expanduser('~/pest_control_ws/cam0_params.yaml')
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
            self.mtx = np.array(data['camera_matrix'])
            self.dist = np.array(data['dist_coeff'])

        # 2. 카메라 설정
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        self.timer = self.create_timer(0.03, self.timer_callback)
        
        # [핵심 수정] 마우스로 크기 조절 가능하게 설정
        self.win_name = 'Calibration Check (Resizeable)'
        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL) 

        cv2.resizeWindow(self.win_name, 1280, 360)

    def timer_callback(self):
        ret, frame = self.cap.read()
        if not ret: return

        h, w = frame.shape[:2]
        
        # 왜곡 보정 수행
        new_mtx, roi = cv2.getOptimalNewCameraMatrix(self.mtx, self.dist, (w, h), 1, (w, h))
        undistorted = cv2.undistort(frame, self.mtx, self.dist, None, new_mtx)

        # 원본과 보정본을 가로로 결합 (2560x720)
        combined = np.hstack((frame, undistorted))

        # 가이드라인 그리기 (원본 해상도 기준 중앙)
        line_y = h // 2
        cv2.line(combined, (0, line_y), (w * 2, line_y), (0, 0, 255), 2)
        
        cv2.putText(combined, "ORIGINAL", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
        cv2.putText(combined, "CORRECTED", (w + 50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)

        # 최종 출력 (cv2.WINDOW_NORMAL 덕분에 마우스로 늘리고 줄일 수 있습니다)
        cv2.imshow(self.win_name, combined)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            rclpy.shutdown()

    def __del__(self):
        if hasattr(self, 'cap') and self.cap.isOpened(): self.cap.release()
        cv2.destroyAllWindows()

def main(args=None):
    rclpy.init(args=args)
    node = CalibViewer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()