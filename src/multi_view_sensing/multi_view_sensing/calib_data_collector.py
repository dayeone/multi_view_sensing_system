import rclpy
from rclpy.node import Node
import cv2
import os
import time
from datetime import datetime
import threading
import queue

class SingleCalibCollector(Node):
    def __init__(self):
        super().__init__('single_calib_collector')
        
        # 체커보드 내부 코너 개수 설정 (가로 7, 세로 10)
        self.checkerboard = (7, 10) 
        self.prev_time = 0 

        # FPS 계산을 위한 이동 평균용 변수
        self.frame_times = []
        self.window_size = 30 
        
        # ROS 2 파라미터 선언
        self.declare_parameter('device_path', '/dev/cam0')
        self.declare_parameter('use_gpu', False) 
        
        self.device_path = self.get_parameter('device_path').get_parameter_value().string_value
        self.use_gpu = self.get_parameter('use_gpu').get_parameter_value().bool_value

        # 저장 폴더 경로 생성
        folder_name = self.device_path.split('/')[-1]
        self.save_path = os.path.expanduser(f'~/pest_control_ws/calib_data/{folder_name}')
        os.makedirs(self.save_path, exist_ok=True)

        # 실제 장치 경로 확인 (/dev/cam0 -> /dev/videoX)
        real_device_path = os.path.realpath(self.device_path)

        try:
            device_index = int(''.join(filter(str.isdigit, real_device_path)))
        except ValueError:
            self.get_logger().error(f'Could not extract index from {real_device_path}')
            return

        # 카메라 캡처 객체 생성
        if self.use_gpu:
            self.get_logger().info(f'[GPU Mode] {self.device_path} -> {real_device_path} (NVDEC)')
            gstreamer_pipeline = (
                f"v4l2src device={real_device_path} ! "
                f"image/jpeg, width=1280, height=720, framerate=60/1 ! "
                f"jpegparse ! nvjpegdec ! "
                f"video/x-raw ! videoconvert ! appsink drop=true sync=false"
            )
            self.cap = cv2.VideoCapture(gstreamer_pipeline, cv2.CAP_GSTREAMER)
        else:
            self.get_logger().info(f'[CPU Mode] {self.device_path} -> {real_device_path} (Auto Backend)')
            self.cap = cv2.VideoCapture(real_device_path)
    
            if self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.cap.set(cv2.CAP_PROP_FPS, 60)
        
        if not self.cap.isOpened():
            self.get_logger().error(f'Failed to open camera: {self.device_path}')
            return

        # UI 창 설정: 960x540 크기로 조정
        self.win_name = f'{folder_name} Calib (C: Capture, Q: Quit)'
        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.win_name, 960, 540)

        # 비동기 캡처 쓰레드 및 큐 설정 (60FPS 방어 핵심)
        self.frame_queue = queue.Queue(maxsize=1)
        self.is_running = True
        self.capture_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.capture_thread.start()

        # 메인 루프 타이머 실행
        self.timer = self.create_timer(0.01, self.timer_callback) 

    def capture_loop(self):
        """백그라운드에서 프레임을 읽어 큐에 넣는 루프"""
        while self.is_running and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                if self.frame_queue.full():
                    try:
                        self.frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                self.frame_queue.put((time.time(), frame))

    def draw_grid(self, frame):
        """화면에 9등분 가이드 라인 그리기"""
        h, w = frame.shape[:2]
        color = (0, 0, 255) # Red
        thickness = 2
        cv2.line(frame, (int(w/3), 0), (int(w/3), h), color, thickness)
        cv2.line(frame, (int(2*w/3), 0), (int(2*w/3), h), color, thickness)
        cv2.line(frame, (0, int(h/3)), (w, int(h/3)), color, thickness)
        cv2.line(frame, (0, int(2*h/3)), (w, int(2*h/3)), color, thickness)   

    def timer_callback(self):
        """메인 처리 및 화면 송출 루프"""
        try:
            start_decode, frame = self.frame_queue.get_nowait()
        except queue.Empty:
            return

        # 지연 시간 측정
        end_decode = time.time()
        decode_latency_ms = (end_decode - start_decode) * 1000

        # FPS 측정
        curr_time = time.time()
        if self.prev_time > 0:
            sec = curr_time - self.prev_time
            self.frame_times.append(sec)
            if len(self.frame_times) > self.window_size:
                self.frame_times.pop(0)
            avg_sec = sum(self.frame_times) / len(self.frame_times)
            fps = 1 / avg_sec if avg_sec > 0 else 0
        else:
            fps = 0
        self.prev_time = curr_time

        display_frame = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        self.draw_grid(display_frame)
        
        # 다운스케일링(1/2)을 통한 연산 최적화
        small_gray = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
        flags = cv2.CALIB_CB_FAST_CHECK | cv2.CALIB_CB_ADAPTIVE_THRESH
        ret_corners, small_corners = cv2.findChessboardCorners(small_gray, self.checkerboard, flags)
        
        if ret_corners:
            corners = small_corners * 2.0 # 좌표 복구
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            cv2.drawChessboardCorners(display_frame, self.checkerboard, corners, ret_corners)
        
        # 정보 출력 (FPS, 지연시간 등)
        cv2.putText(display_frame, f"FPS: {fps:.1f}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.putText(display_frame, f"Latency: {decode_latency_ms:.1f} ms", (20, 90), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
        
        mode_text = "MODE: GPU" if self.use_gpu else "MODE: CPU"
        cv2.putText(display_frame, mode_text, (20, 130), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        
        cv2.imshow(self.win_name, display_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('c'):
            ts = datetime.now().strftime('%H%M%S')
            filename = os.path.join(self.save_path, f'calib_{ts}.jpg')
            cv2.imwrite(filename, frame)
            self.get_logger().info(f'Captured: {filename}')
        elif key == ord('q'):
            rclpy.shutdown()

    def __del__(self):        
        self.is_running = False
        if hasattr(self, 'capture_thread') and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=1.0)
        if hasattr(self, 'cap') and self.cap.isOpened(): 
            self.cap.release()
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

if __name__ == '__main__':
    main()