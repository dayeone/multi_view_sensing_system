import rclpy
from rclpy.node import Node
import cv2
import os
import time
from datetime import datetime
import threading
import queue
import sys

class SingleCalibCollector(Node):
    def __init__(self):
        super().__init__('single_calib_collector')
        
        self.checkerboard = (7, 10) 
        self.prev_time = 0 

        # FPS 안정화를 위한 이동 평균 변수
        self.frame_times = []
        self.window_size = 30 
        
        # 1. 파라미터 선언: 장치 경로와 GPU 사용 여부 스위치
        self.declare_parameter('device_path', '/dev/cam0')
        self.declare_parameter('use_gpu', False)
        
        self.device_path = self.get_parameter('device_path').get_parameter_value().string_value
        self.use_gpu = self.get_parameter('use_gpu').get_parameter_value().bool_value

        # 2. 저장 폴더 설정
        folder_name = self.device_path.split('/')[-1]
        self.save_path = os.path.expanduser(f'~/pest_control_ws/calib_data/{folder_name}')
        os.makedirs(self.save_path, exist_ok=True)

        # 3. 심볼릭 링크를 실제 경로로 변환
        real_device_path = os.path.realpath(self.device_path)

        # 4. 경로에서 숫자 인덱스 추출
        try:
            device_index = int(''.join(filter(str.isdigit, real_device_path)))
        except ValueError:
            self.get_logger().error(f'Could not extract index from {real_device_path}')
            return

        # 5. GPU 스위치에 따른 카메라 연결 방식 분기
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
            sys.exit(1)

        # 6. UI 윈도우 초기화 및 4분할 화면 배치 (3번 모니터 타겟)
        self.win_name = f'{folder_name} Calib (C: Capture, Q: Quit)'
        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.win_name, 960, 540)
        
        # 3번 모니터 시작 좌표 (1,2번 모니터 가로 해상도 합. 필요시 수정)
        offset_x = 3840 
        offset_y = 0

        if "0" in self.device_path:     # cam0 또는 video0
            cv2.moveWindow(self.win_name, offset_x + 0, offset_y + 0)
        elif "1" in self.device_path or "4" in self.device_path: # cam1 또는 video4
            cv2.moveWindow(self.win_name, offset_x + 960, offset_y + 0)
        elif "2" in self.device_path or "8" in self.device_path: # cam2 또는 video8
            cv2.moveWindow(self.win_name, offset_x + 0, offset_y + 540)
        elif "3" in self.device_path or "12" in self.device_path: # cam3 또는 video12
            cv2.moveWindow(self.win_name, offset_x + 960, offset_y + 540)

        # 7. 비동기 쓰레드용 큐(Queue) 및 상태 변수 세팅
        self.frame_queue = queue.Queue(maxsize=1)
        self.result_queue = queue.Queue(maxsize=1)
        self.latest_ret = False
        self.latest_corners = None 
        self.is_running = True     

        # 8. 배경에서 연산만 전담할 '서브 쓰레드' 고용 및 실행
        self.detect_thread = threading.Thread(target=self.process_checkerboard, daemon=True)
        self.detect_thread.start()

        # 9. ROS 2 메인 타이머 (화면 송출 전담)
        self.timer = self.create_timer(0.01, self.timer_callback)


    def process_checkerboard(self):
        """[서브 쓰레드] 메인 화면 송출과 완전히 독립적으로 무거운 연산만 수행합니다."""
        while self.is_running:
            try:
                # 1. 큐에서 가장 최신 흑백 프레임을 꺼내옵니다.
                gray = self.frame_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            # --- [연산 최적화 구역: 다운스케일링 적용] ---
            small_gray = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
            flags = cv2.CALIB_CB_FAST_CHECK | cv2.CALIB_CB_ADAPTIVE_THRESH
            
            # 축소된 이미지에서 체커보드 찾기 (GIL 잠시 해제됨)
            ret_corners, small_corners = cv2.findChessboardCorners(small_gray, self.checkerboard, flags)
            corners = None

            if ret_corners:
                corners = small_corners * 2.0
                criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
                corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            # -----------------------------------------

            # 3. 연산 결과를 결과용 큐에 밀어 넣기 (밀려있으면 옛날 거 빼버림)
            if self.result_queue.full():
                try: self.result_queue.get_nowait()
                except queue.Empty: pass
            
            self.result_queue.put((ret_corners, corners))


    def draw_grid(self, frame):
        h, w = frame.shape[:2]
        color = (0, 0, 255) 
        thickness = 2
        cv2.line(frame, (int(w/3), 0), (int(w/3), h), color, thickness)
        cv2.line(frame, (int(2*w/3), 0), (int(2*w/3), h), color, thickness)
        cv2.line(frame, (0, int(h/3)), (w, int(h/3)), color, thickness)
        cv2.line(frame, (0, int(2*h/3)), (w, int(2*h/3)), color, thickness)   


    def timer_callback(self):
        """[메인 쓰레드] 프레임 읽기, 화면 그리기, UI 조작만 60FPS로 처리합니다."""
        start_decode = time.time()
        ret, frame = self.cap.read()  
        end_decode = time.time()
        
        if not ret:
            return
            
        decode_latency_ms = (end_decode - start_decode) * 1000

        # FPS 계산
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

        # 1. 방금 찍은 사진을 서브 쓰레드가 가져가게 큐에 던져줍니다 (비동기)
        if self.frame_queue.full():
            try: self.frame_queue.get_nowait()
            except queue.Empty: pass
        self.frame_queue.put(gray.copy())

        # 2. 서브 쓰레드가 체커보드 찾은 결과가 있나 우체통 확인 (비동기)
        try:
            ret_cb, corners = self.result_queue.get_nowait()
            self.latest_ret = ret_cb
            self.latest_corners = corners
        except queue.Empty:
            pass # 새 결과가 안 왔으면 과거 좌표 그대로 사용

        # 격자 및 체커보드 그리기
        self.draw_grid(display_frame)
        if self.latest_ret and self.latest_corners is not None:
            cv2.drawChessboardCorners(display_frame, self.checkerboard, self.latest_corners, self.latest_ret)
        
        # 텍스트 오버레이
        cv2.putText(display_frame, f"FPS: {fps:.1f}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.putText(display_frame, f"Decode Latency: {decode_latency_ms:.1f} ms", (20, 90), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
        
        mode_text = "MODE: GPU (GStreamer)" if self.use_gpu else "MODE: CPU (V4L2)"
        mode_color = (255, 0, 0) if self.use_gpu else (0, 255, 0)
        cv2.putText(display_frame, mode_text, (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.0, mode_color, 2)
        
        cv2.imshow(self.win_name, display_frame)

        # 키보드 입력 및 종료 로직
        key = cv2.waitKey(1) & 0xFF
        if key == ord('c'):
            ts = datetime.now().strftime('%H%M%S')
            filename = os.path.join(self.save_path, f'calib_{ts}.jpg')
            cv2.imwrite(filename, frame)
            self.get_logger().info(f'Image Captured: {filename} (FPS: {fps:.1f})')
        elif key == ord('q'):
            self.get_logger().info('Quitting application safely...')
            self.is_running = False
            self.cap.release()
            cv2.destroyAllWindows()
            sys.exit(0) # 완벽한 프로세스 킬

def main(args=None):
    rclpy.init(args=args)
    node = SingleCalibCollector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.is_running = False
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()