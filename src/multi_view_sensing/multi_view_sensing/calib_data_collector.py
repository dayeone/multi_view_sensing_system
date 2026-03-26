import rclpy
from rclpy.node import Node
import cv2
import os
import time
from datetime import datetime

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
        self.declare_parameter('use_gpu', False) # 기본값은 CPU(False)
        
        self.device_path = self.get_parameter('device_path').get_parameter_value().string_value
        self.use_gpu = self.get_parameter('use_gpu').get_parameter_value().bool_value

        # 2. 저장 폴더 설정 (예: cam0, cam1)
        folder_name = self.device_path.split('/')[-1]
        self.save_path = os.path.expanduser(f'~/pest_control_ws/calib_data/{folder_name}')
        os.makedirs(self.save_path, exist_ok=True)

       # 3. 심볼릭 링크(/dev/cam0)를 실제 경로(/dev/video3)로 변환
        real_device_path = os.path.realpath(self.device_path)

        # 4. 경로에서 숫자 인덱스만 추출 (예: /dev/video3 -> 3)
        try:
            # 문자열에서 숫자만 걸러내서 정수로 변환합니다.
            device_index = int(''.join(filter(str.isdigit, real_device_path)))
        except ValueError:
            self.get_logger().error(f'Could not extract index from {real_device_path}')
            return

        # 5. GPU 스위치에 따른 카메라 연결 방식 분기
        if self.use_gpu:
            self.get_logger().info(f'[GPU Mode] {self.device_path} -> {real_device_path} (NVDEC)')
            # GStreamer는 '문자열 경로'가 필요합니다.
            gstreamer_pipeline = (
                f"v4l2src device={real_device_path} ! "
                f"image/jpeg, width=1280, height=720, framerate=60/1 ! "
                f"jpegparse ! nvjpegdec ! "
                f"video/x-raw ! videoconvert ! appsink drop=true sync=false"
            )
            self.cap = cv2.VideoCapture(gstreamer_pipeline, cv2.CAP_GSTREAMER)
        else:
                self.get_logger().info(f'[CPU Mode] {self.device_path} -> {real_device_path} (Auto Backend)')
                # CAP_V4L2 옵션을 완전히 빼버리고, 실제 경로(/dev/video3)를 통째로 던져줍니다.
                self.cap = cv2.VideoCapture(real_device_path)
        
                if self.cap.isOpened():
                    self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                    self.cap.set(cv2.CAP_PROP_FPS, 60)
        
        # 카메라 오픈 실패 시 에러 로깅
        if not self.cap.isOpened():
            self.get_logger().error(f'Failed to open camera: {self.device_path}')
            return

        self.timer = self.create_timer(0.01, self.timer_callback) # 최대한 빠르게 루프
        self.win_name = f'{folder_name} Calib (C: Capture, Q: Quit)'
        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)

    def draw_grid(self, frame):
        # 9등분 격자 그리기
        h, w = frame.shape[:2]
        color = (0, 0, 255) # 빨간색 선
        thickness = 2
        # 세로선
        cv2.line(frame, (int(w/3), 0), (int(w/3), h), color, thickness)
        cv2.line(frame, (int(2*w/3), 0), (int(2*w/3), h), color, thickness)
        # 가로선
        cv2.line(frame, (0, int(h/3)), (w, int(h/3)), color, thickness)
        cv2.line(frame, (0, int(2*h/3)), (w, int(2*h/3)), color, thickness)   

    def timer_callback(self):
        # [성능 측정 1] 압축 해제(Decoding)에 걸리는 순수 지연 시간(Latency) 측정
        start_decode = time.time()
        ret, frame = self.cap.read()  # 하드웨어 디코딩 성능의 핵심 지점
        end_decode = time.time()
        
        if not ret:
            # self.get_logger().warn('Frame grab failed') # 로그 폭발 방지를 위해 주석 처리
            return
            
        decode_latency_ms = (end_decode - start_decode) * 1000

        # [성능 측정 2] 시스템 전체 FPS 계산 (이동 평균)
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

        # 격자 가이드 그리기
        self.draw_grid(display_frame)
        
    
       # --- [연산 최적화 구역: 다운스케일링 적용] ---
        # 1. 연산 속도를 높이기 위해 이미지를 가로세로 절반(면적 1/4)으로 축소합니다.
        small_gray = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
        
        flags = cv2.CALIB_CB_FAST_CHECK | cv2.CALIB_CB_ADAPTIVE_THRESH
        
        # 2. 축소된 이미지에서 체커보드를 찾습니다. (최악의 시나리오에서도 연산량 4배 감소)
        ret_corners, small_corners = cv2.findChessboardCorners(small_gray, self.checkerboard, flags)
        
        if ret_corners:
            # 3. 찾은 좌표를 원본 해상도 비율에 맞춰 다시 2배로 늘립니다.
            corners = small_corners * 2.0
            
            # 4. 캘리브레이션 정밀도를 위해 원본 해상도(gray)에서 코너 위치를 서브픽셀 단위로 깎습니다.
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            
            cv2.drawChessboardCorners(display_frame, self.checkerboard, corners, ret_corners)
        # -----------------------------------------
        
        # 화면에 FPS와 지연 시간(Latency) 동시 출력 (영문 텍스트 사용)
        cv2.putText(display_frame, f"FPS: {fps:.1f}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.putText(display_frame, f"Decode Latency: {decode_latency_ms:.1f} ms", (20, 90), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
        
        # GPU 모드 유무 시각적 표시
        mode_text = "MODE: GPU (GStreamer)" if self.use_gpu else "MODE: CPU (V4L2)"
        mode_color = (255, 0, 0) if self.use_gpu else (0, 255, 0) # 파랑(GPU), 초록(CPU)
        cv2.putText(display_frame, mode_text, (20, 130), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, mode_color, 2)
        
        cv2.imshow(self.win_name, display_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('c'):
            # 현재 시간을 파일명으로 하여 이미지 저장
            ts = datetime.now().strftime('%H%M%S')
            filename = os.path.join(self.save_path, f'calib_{ts}.jpg')
            cv2.imwrite(filename, frame)
            self.get_logger().info(f'Image Captured: {filename} (FPS: {fps:.1f}, Latency: {decode_latency_ms:.1f}ms)')
        elif key == ord('q'):
            self.get_logger().info('Quitting application')
            rclpy.shutdown()

    def __del__(self):        # 자원 해제
        if hasattr(self, 'cap') and self.cap.isOpened(): 
            self.cap.release()
        cv2.destroyAllWindows()

def main(args=None):
    rclpy.init(args=args)
    node = SingleCalibCollector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        # Ctrl+C 예외 처리
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()