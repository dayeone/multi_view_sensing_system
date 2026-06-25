import rclpy
from rclpy.node import Node
import cv2
import csv
import os
import time
from datetime import datetime
import threading
import queue

# ROS 2 통신용 메시지 임포트
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Empty

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
        # cam0의 깜빡임 문제를 해결하기 위해 기본 장치를 /dev/video0로 변경
        self.declare_parameter('device_path', '/dev/video0')
        self.declare_parameter('use_gpu', False)
        # 기본 실행 모드를 remote로 설정하여 별도 옵션 없이도 원격 송출되도록 함
        self.declare_parameter('display_mode', 'remote')
        self.declare_parameter('enable_metrics_log', False)

        self.device_path = self.get_parameter('device_path').get_parameter_value().string_value
        self.use_gpu = self.get_parameter('use_gpu').get_parameter_value().bool_value
        self.display_mode = self.get_parameter('display_mode').get_parameter_value().string_value
        self.enable_metrics_log = (
            self.get_parameter('enable_metrics_log')
            .get_parameter_value()
            .bool_value
        )

        # 저장 폴더 경로 생성
        folder_name = self.device_path.split('/')[-1]
        self.save_path = os.path.expanduser(f'~/pest_control_ws/calib_data/{folder_name}')
        os.makedirs(self.save_path, exist_ok=True)

        # 실제 장치 경로 확인 (/dev/cam0 -> /dev/videoX)
        real_device_path = os.path.realpath(self.device_path)

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
                # 오토포커스 OFF + 초점 고정 (intrinsic 안정화, 공간 정합용).
                # 초점값은 recorder.py의 --focus 값과 반드시 동일하게 유지할 것.
                self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                self.cap.set(cv2.CAP_PROP_FOCUS, 0)
        
        if not self.cap.isOpened():
            self.get_logger().error(f'Failed to open camera: {self.device_path}')
            return

        # 모드별 초기화 세팅
        if self.display_mode == 'local':
            # [local] 모드일 때만 OpenCV 윈도우 생성
            self.win_name = f'{folder_name} Calib (C: Capture, Q: Quit)'
            cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.win_name, 960, 540)
        elif self.display_mode == 'remote':
            # [remote] 모드일 때는 창을 생성하지 않으며, 혹시 모를 기존 창을 닫음
            cv2.destroyAllWindows()
            # 원격 전송을 위한 퍼블리셔 설정
            topic_name = f'{folder_name}/image_compressed'
            self.image_pub = self.create_publisher(CompressedImage, topic_name, 10)
            self.get_logger().info(f'Starting Remote Mode: Publishing to {topic_name}')

        # 원격 캡처 명령용 Subscriber (화면이 없는 remote 모드에서 유용)
        self.capture_sub = self.create_subscription(Empty, f'{folder_name}/capture_cmd', self.remote_capture_cb, 10)
        self.capture_requested = False

        # 비동기 캡처 쓰레드 및 큐 설정 (60FPS 방어 핵심)
        self.frame_queue = queue.Queue(maxsize=1)
        self.is_running = True

        # ── 스레드별 독립 FPS 측정 ──
        # 각 스레드가 자신의 카운터/기준시각을 들고 1초 단위로 자기 FPS를 계산한 후
        # 공유 변수(self.cap_fps / self.det_fps)에 기록한다.
        self.fps_lock = threading.Lock()
        self.cap_fps = 0.0
        self.det_fps = 0.0

        # 스레드 로컬 상태 (해당 스레드에서만 읽고 쓴다 → 락 불필요)
        now = time.time()
        self._cap_count = 0
        self._cap_last_time = now
        self._det_count = 0
        self._det_last_time = now

        # ── CSV 메트릭 로깅 ──
        self.csv_file = None
        self.csv_writer = None
        if self.enable_metrics_log:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            csv_path = os.path.join(
                os.getcwd(), f'calib_metrics_{folder_name}_{timestamp}.csv'
            )
            self.csv_file = open(csv_path, 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(
                ['time', 'cap_fps', 'det_fps', 'latency_ms']
            )
            self.csv_file.flush()
            self.get_logger().info(f'Metrics logging enabled: {csv_path}')

        self.capture_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.capture_thread.start()

        # 메인 루프 타이머 실행 (100Hz로 데이터 확인)
        self.timer = self.create_timer(0.01, self.timer_callback)

    def remote_capture_cb(self, msg):
        """원격으로 토픽 명령 수신 시 캡처 플래그 활성화"""
        self.get_logger().info('Remote capture command received!')
        self.capture_requested = True

    def capture_loop(self):
        """백그라운드 쓰레드: 카메라로부터 실시간 프레임을 읽어 큐를 최신화함"""
        while self.is_running and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                if self.frame_queue.full():
                    try:
                        self.frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                # 캡처 시간과 프레임을 함께 큐에 저장
                self.frame_queue.put((time.time(), frame))

                # 이 스레드 내부에서 독립적으로 Cap FPS 산출
                self._cap_count += 1
                now = time.time()
                elapsed = now - self._cap_last_time
                if elapsed >= 1.0:
                    fps = self._cap_count / elapsed
                    with self.fps_lock:
                        self.cap_fps = fps
                    self._cap_count = 0
                    self._cap_last_time = now

    def draw_grid(self, frame):
        """화면에 9등분 가이드 라인 그리기 (모니터링 편의성)"""
        h, w = frame.shape[:2]
        # [수정] 얇은 회색 격자선으로 변경 (B, G, R 형식)
        color = (128, 128, 128) # Gray
        thickness = 1           # 얇게 (기존 2 -> 1)
        cv2.line(frame, (int(w/3), 0), (int(w/3), h), color, thickness)
        cv2.line(frame, (int(2*w/3), 0), (int(2*w/3), h), color, thickness)
        cv2.line(frame, (0, int(h/3)), (w, int(h/3)), color, thickness)
        cv2.line(frame, (0, int(2*h/3)), (w, int(2*h/3)), color, thickness)   

    def timer_callback(self):
        """메인 쓰레드: 큐에서 프레임을 가져와 연산, 로컬 출력 또는 원격 송출 수행"""
        try:
            start_decode, frame = self.frame_queue.get_nowait()
        except queue.Empty:
            return

        # 지연 시간 측정 (큐 대기 시간 포함)
        end_decode = time.time()
        decode_latency_ms = (end_decode - start_decode) * 1000

        # FPS 측정 및 이동 평균 계산
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

        # 시각화용 프레임 복사 및 연산용 흑백 변환
        display_frame = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 가이드라인 그리기
        self.draw_grid(display_frame)
        
        # 다운스케일링(1/2)을 통한 연산 부하 최적화 (체커보드 검출 속도 향상)
        small_gray = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
        flags = cv2.CALIB_CB_FAST_CHECK | cv2.CALIB_CB_ADAPTIVE_THRESH
        ret_corners, small_corners = cv2.findChessboardCorners(small_gray, self.checkerboard, flags)

        if ret_corners:
            corners = small_corners * 2.0 # 축소된 좌표를 원본 크기로 복구
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            # 서브픽셀 정밀도로 코너 좌표 보정
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            # 화면에 검출된 코너 표시
            cv2.drawChessboardCorners(display_frame, self.checkerboard, corners, ret_corners)

        # 검출 스레드(=타이머 콜백) 내부에서 독립적으로 Det FPS 산출
        # 성공/실패 관계없이 findChessboardCorners 호출 완료마다 카운트
        self._det_count += 1
        det_done_time = time.time()
        det_elapsed = det_done_time - self._det_last_time
        if det_elapsed >= 1.0:
            det_fps_now = self._det_count / det_elapsed
            with self.fps_lock:
                self.det_fps = det_fps_now
            self._det_count = 0
            self._det_last_time = det_done_time

        # 캡처 시점 → 검출 완료 시점까지의 지연 (ms) — CSV 전용
        detect_latency_ms = (det_done_time - start_decode) * 1000

        # 매 타이머 반복마다 CSV 1행 기록
        if self.csv_writer is not None:
            with self.fps_lock:
                cap_fps_now = self.cap_fps
                det_fps_snap = self.det_fps
            self.csv_writer.writerow([
                f'{det_done_time:.6f}',
                f'{cap_fps_now:.2f}',
                f'{det_fps_snap:.2f}',
                f'{detect_latency_ms:.2f}',
            ])
            self.csv_file.flush()
        
        # 화면에 상태 정보 출력 (FPS, 지연시간, 현재 모드)
        cv2.putText(display_frame, f"FPS: {fps:.1f}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.putText(display_frame, f"Latency: {decode_latency_ms:.1f} ms", (20, 90), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
        
        mode_text = f"MODE: {self.display_mode.upper()} ({'GPU' if self.use_gpu else 'CPU'})"
        cv2.putText(display_frame, mode_text, (20, 130), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        
        # 캡처 명령 처리 및 키 입력 분기
        # local 모드일 때만 waitKey로 키보드를 감시함
        key = cv2.waitKey(1) & 0xFF if self.display_mode == 'local' else 0xFF
        
        # 'c' 키 입력 또는 원격 명령 플래그가 True인 경우 실행
        if key == ord('c') or self.capture_requested:
            self.capture_requested = False
            ts = datetime.now().strftime('%H%M%S')
            filename = os.path.join(self.save_path, f'calib_{ts}.jpg')
            cv2.imwrite(filename, frame) # 가이드라인이 없는 순수 원본 저장
            self.get_logger().info(f'Captured: {filename}')
            
        elif key == ord('q') and self.display_mode == 'local':
            # local 모드에서 'q' 입력 시 안전하게 노드 종료
            rclpy.shutdown()

        # 최종 디스플레이/송출 분기 처리
        if self.display_mode == 'local':
            # local 모드일 때만 로컬 모니터에 창을 띄움
            cv2.imshow(self.win_name, display_frame)
            
        elif self.display_mode == 'remote':
            # remote 모드일 때는 화면 송출 대신 ROS 토픽으로 전송
            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.format = "jpeg"
            # JPEG 품질을 70으로 압축하여 네트워크 대역폭 및 전송 속도 최적화
            ret_enc, encoded_img = cv2.imencode('.jpg', display_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ret_enc:
                msg.data = encoded_img.tobytes()
                self.image_pub.publish(msg)

    def _shutdown(self):
        """쓰레드 종료 + 카메라/CSV 자원 해제 (멱등)"""
        if not getattr(self, 'is_running', False):
            return
        self.is_running = False
        if hasattr(self, 'capture_thread') and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=1.0)
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()
        cv2.destroyAllWindows()
        if getattr(self, 'csv_file', None) is not None:
            try:
                self.csv_file.close()
            except Exception:
                pass
            self.csv_file = None
            self.csv_writer = None

    def destroy_node(self):
        self._shutdown()
        super().destroy_node()

    def __del__(self):
        self._shutdown()

def main(args=None):
    rclpy.init(args=args)
    node = SingleCalibCollector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # 노드 종료 시 자원 정리
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()