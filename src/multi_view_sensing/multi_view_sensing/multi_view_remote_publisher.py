import rclpy
from rclpy.node import Node
import cv2
import csv
import os
import time
import threading
import queue
from datetime import datetime
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CompressedImage


class MultiViewRemotePublisher(Node):
    def __init__(self):
        super().__init__('multi_view_remote_publisher')

        # ROS 2 파라미터 선언
        self.declare_parameter(
            'device_paths',
            ['/dev/video0', '/dev/video4', '/dev/video8', '/dev/video12'],
        )
        self.declare_parameter('jpeg_quality', 70)
        self.declare_parameter('enable_metrics_log', False)
        self.declare_parameter('display_mode', 'local')

        self.device_paths = (
            self.get_parameter('device_paths')
            .get_parameter_value()
            .string_array_value
        )
        self.jpeg_quality = (
            self.get_parameter('jpeg_quality')
            .get_parameter_value()
            .integer_value
        )
        self.enable_metrics_log = (
            self.get_parameter('enable_metrics_log')
            .get_parameter_value()
            .bool_value
        )
        self.display_mode = (
            self.get_parameter('display_mode')
            .get_parameter_value()
            .string_value
        )

        self.is_running = True
        self.num_cams = len(self.device_paths)

        # ── 1단계: 캡처 스레드 (카메라당 1개) ──
        self.caps = []
        self.capture_queues = []
        self.capture_threads = []

        for dev in self.device_paths:
            real_path = os.path.realpath(dev)
            self.get_logger().info(f'Opening camera: {dev} -> {real_path}')

            cap = cv2.VideoCapture(real_path)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                cap.set(cv2.CAP_PROP_FPS, 60)
                self.get_logger().info(f'Camera opened: {real_path}')
            else:
                self.get_logger().error(f'Failed to open camera: {dev}')

            self.caps.append(cap)

            q = queue.Queue(maxsize=1)
            self.capture_queues.append(q)

            t = threading.Thread(
                target=self._capture_loop,
                args=(cap, q, len(self.capture_threads)),
                daemon=True,
            )
            t.start()
            self.capture_threads.append(t)

        # ── 검출 결과 공유 (lock 보호) ──
        # detect_overlays[i] = 검출된 corners가 그려진 480x270 이미지 or None
        self.detect_overlays = [None] * self.num_cams
        self.detect_lock = threading.Lock()

        # 검출 스레드에 프레임을 전달할 큐 (카메라당 1개, maxsize=1)
        self.detect_queues = []
        for _ in range(self.num_cams):
            self.detect_queues.append(queue.Queue(maxsize=1))

        # ── 2단계: 검출 스레드 (카메라당 1개, 독립적으로 체커보드 검출) ──
        self.checkerboard = (7, 10)
        self.detect_threads = []
        for i in range(self.num_cams):
            t = threading.Thread(
                target=self._detect_loop, args=(i,), daemon=True
            )
            t.start()
            self.detect_threads.append(t)

        # ── 3단계: 모드별 출력 설정 ──
        if self.display_mode == 'local':
            self.win_name = 'MultiView 2x2 (Q: Quit)'
            cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.win_name, 960, 540)
            self.image_pub = None
            self.get_logger().info('Starting Local Mode: OpenCV display')
        elif self.display_mode == 'remote':
            qos_profile = QoSProfile(
                reliability=ReliabilityPolicy.BEST_EFFORT,
                durability=DurabilityPolicy.VOLATILE,
                history=HistoryPolicy.KEEP_LAST,
                depth=1,
            )
            self.image_pub = self.create_publisher(
                CompressedImage, '/multi_view/image_compressed', qos_profile
            )
            self.get_logger().info('Starting Remote Mode: Publishing to /multi_view/image_compressed')

        # 카메라별 마지막 수신 프레임 캐시 (480x270)
        self.last_frames = [None] * self.num_cams

        # ── 스레드별 독립 FPS 측정 ──
        # 각 스레드가 자신의 카운터/기준시각을 들고 1초 단위로 자기 FPS를 계산한 후
        # 공유 변수(self.cap_fps_per_cam / det_fps_per_cam / pub_fps)에 기록한다.
        self.fps_lock = threading.Lock()
        self.cap_fps_per_cam = [0.0] * self.num_cams
        self.det_fps_per_cam = [0.0] * self.num_cams
        self.pub_fps = 0.0

        # 스레드 로컬 상태 (각 스레드에서만 읽고 쓴다 → 락 불필요)
        now = time.time()
        self._cap_counts = [0] * self.num_cams
        self._cap_last_time = [now] * self.num_cams
        self._det_counts = [0] * self.num_cams
        self._det_last_time = [now] * self.num_cams
        self._pub_count = 0
        self._pub_last_time = now

        # Latency 이동 평균
        self.latency_times = []
        self.window_size = 30

        # 동기화 품질 이동 평균
        self.sync_gap_times = []

        # ── CSV 메트릭 로깅 ──
        self.csv_file = None
        self.csv_writer = None
        if self.enable_metrics_log:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            csv_path = os.path.join(os.getcwd(), f'metrics_{timestamp}.csv')
            self.csv_file = open(csv_path, 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(
                ['time', 'cap_fps', 'det_fps', 'pub_fps', 'latency_ms', 'sync_gap_ms']
            )
            self.csv_file.flush()
            self.get_logger().info(f'Metrics logging enabled: {csv_path}')

        # 메인 타이머 15Hz: 캡처 프레임 합성 + 검출 오버레이 → 직접 publish
        self.timer = self.create_timer(1.0 / 15.0, self._timer_callback)
        self.get_logger().info('MultiViewRemotePublisher started')

    # ── 캡처 스레드 ──
    def _capture_loop(self, cap, q, cam_idx):
        """카메라에서 프레임을 읽어 큐를 최신 프레임으로 유지"""
        while self.is_running and cap.isOpened():
            ret, frame = cap.read()
            if ret:
                if q.full():
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                q.put((time.time(), frame))

                # 이 스레드 내부에서 독립적으로 Cap FPS 산출
                self._cap_counts[cam_idx] += 1
                now = time.time()
                elapsed = now - self._cap_last_time[cam_idx]
                if elapsed >= 1.0:
                    fps = self._cap_counts[cam_idx] / elapsed
                    with self.fps_lock:
                        self.cap_fps_per_cam[cam_idx] = fps
                    self._cap_counts[cam_idx] = 0
                    self._cap_last_time[cam_idx] = now

    # ── 검출 스레드 (카메라당 1개) ──
    def _detect_loop(self, cam_idx):
        """독립 스레드: 원본 프레임에서 체커보드 검출 → 오버레이 이미지 갱신"""
        while self.is_running:
            try:
                frame = self.detect_queues[cam_idx].get(timeout=0.1)
            except queue.Empty:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # 다운스케일링(1/2)으로 검출 속도 최적화
            small_gray = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
            flags = cv2.CALIB_CB_FAST_CHECK | cv2.CALIB_CB_ADAPTIVE_THRESH
            ret_cb, small_corners = cv2.findChessboardCorners(
                small_gray, self.checkerboard, flags
            )

            if ret_cb:
                corners = small_corners * 2.0
                criteria = (
                    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
                    30, 0.001,
                )
                corners = cv2.cornerSubPix(
                    gray, corners, (11, 11), (-1, -1), criteria
                )
                # 검출 결과를 프레임에 그린 후 480x270으로 축소
                overlay = frame.copy()
                cv2.drawChessboardCorners(
                    overlay, self.checkerboard, corners, ret_cb
                )
                overlay_small = cv2.resize(overlay, (480, 270))
                with self.detect_lock:
                    self.detect_overlays[cam_idx] = overlay_small
            else:
                with self.detect_lock:
                    self.detect_overlays[cam_idx] = None

            # 이 스레드 내부에서 독립적으로 Det FPS 산출
            self._det_counts[cam_idx] += 1
            now = time.time()
            elapsed = now - self._det_last_time[cam_idx]
            if elapsed >= 1.0:
                fps = self._det_counts[cam_idx] / elapsed
                with self.fps_lock:
                    self.det_fps_per_cam[cam_idx] = fps
                self._det_counts[cam_idx] = 0
                self._det_last_time[cam_idx] = now

    # ── 메인 타이머 콜백: 합성 + 오버레이 + 직접 publish ──
    def _timer_callback(self):
        """15Hz: 캡처 프레임에 검출 오버레이를 덮어씌운 뒤 2x2 합성 → 직접 publish"""

        capture_timestamps = [None] * self.num_cams

        # 캡처 큐에서 최신 프레임 수집
        for i, q in enumerate(self.capture_queues):
            try:
                ts, frame = q.get_nowait()
                self.last_frames[i] = cv2.resize(frame, (480, 270))
                capture_timestamps[i] = ts

                # 검출 스레드에 원본 프레임 전달 (가득 차면 드롭)
                dq = self.detect_queues[i]
                if dq.full():
                    try:
                        dq.get_nowait()
                    except queue.Empty:
                        pass
                dq.put(frame)
            except queue.Empty:
                pass

        capture_time = capture_timestamps[0]

        # 4개 카메라 모두 최소 1프레임 수신 전까지 대기
        if any(f is None for f in self.last_frames) or capture_time is None:
            return

        # 동기화 품질 계산
        sync_gap_ms = 0.0
        valid_timestamps = [t for t in capture_timestamps if t is not None]
        if len(valid_timestamps) == self.num_cams:
            sync_gap_ms = (max(valid_timestamps) - min(valid_timestamps)) * 1000

        self.sync_gap_times.append(sync_gap_ms)
        if len(self.sync_gap_times) > self.window_size:
            self.sync_gap_times.pop(0)
        avg_sync_gap_ms = sum(self.sync_gap_times) / len(self.sync_gap_times)

        # 검출 오버레이가 있으면 해당 카메라 프레임을 교체
        with self.detect_lock:
            display_frames = []
            for i in range(self.num_cams):
                if self.detect_overlays[i] is not None:
                    display_frames.append(self.detect_overlays[i])
                else:
                    display_frames.append(self.last_frames[i])

        # 2x2 합성 (최종 960x540)
        top = cv2.hconcat([display_frames[0], display_frames[1]])
        bottom = cv2.hconcat([display_frames[2], display_frames[3]])
        combined = cv2.vconcat([top, bottom])

        # publish 직전 시점 기록
        publish_time = time.time()

        # Latency 이동 평균 (캡처 → publish 직전까지의 실제 경과 시간)
        raw_latency = (publish_time - capture_time) * 1000
        self.latency_times.append(raw_latency)
        if len(self.latency_times) > self.window_size:
            self.latency_times.pop(0)
        latency_ms = sum(self.latency_times) / len(self.latency_times)

        # 4채널 평균 FPS 계산 (각 스레드가 기록한 값을 읽기만 함)
        with self.fps_lock:
            avg_cap_fps = sum(self.cap_fps_per_cam) / self.num_cams
            avg_det_fps = sum(self.det_fps_per_cam) / self.num_cams
            cur_pub_fps = self.pub_fps

        # 오버레이: 3가지 스레드별 FPS + Latency + Sync
        fps_text = f'Cap: {avg_cap_fps:.1f} | Det: {avg_det_fps:.1f} | Pub: {cur_pub_fps:.1f}'
        cv2.putText(
            combined, fps_text, (20, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
        )
        cv2.putText(
            combined, f'Latency: {latency_ms:.1f} ms', (20, 55),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2,
        )
        cv2.putText(
            combined, f'Sync: {avg_sync_gap_ms:.1f} ms', (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2,
        )

        # 모드별 출력 분기
        if self.display_mode == 'local':
            cv2.imshow(self.win_name, combined)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                rclpy.shutdown()

        elif self.display_mode == 'remote':
            ret_enc, encoded = cv2.imencode(
                '.jpg', combined,
                [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
            )
            if not ret_enc:
                return

            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.format = 'jpeg'
            msg.data = encoded.tobytes()
            self.image_pub.publish(msg)

        # 이 스레드(타이머) 내부에서 독립적으로 Pub FPS 산출
        self._pub_count += 1
        now = time.time()
        elapsed = now - self._pub_last_time
        if elapsed >= 1.0:
            fps = self._pub_count / elapsed
            with self.fps_lock:
                self.pub_fps = fps
            self._pub_count = 0
            self._pub_last_time = now

        # 매 publish마다 CSV 1행 기록
        if self.csv_writer is not None:
            self.csv_writer.writerow([
                f'{time.time():.6f}',
                f'{avg_cap_fps:.2f}',
                f'{avg_det_fps:.2f}',
                f'{cur_pub_fps:.2f}',
                f'{latency_ms:.2f}',
                f'{avg_sync_gap_ms:.2f}',
            ])
            self.csv_file.flush()

    def _shutdown(self):
        """스레드 종료 + 카메라/CSV 자원 해제 (멱등)"""
        cv2.destroyAllWindows()
        if not self.is_running:
            return
        self.is_running = False
        for t in self.detect_threads:
            if t.is_alive():
                t.join(timeout=1.0)
        for t in self.capture_threads:
            if t.is_alive():
                t.join(timeout=1.0)
        for cap in self.caps:
            if cap.isOpened():
                cap.release()
        if self.csv_file is not None:
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
    node = MultiViewRemotePublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
