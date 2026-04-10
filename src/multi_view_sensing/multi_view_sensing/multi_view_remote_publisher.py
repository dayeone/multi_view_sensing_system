import rclpy
from rclpy.node import Node
import cv2
import os
import time
import threading
import queue
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
                target=self._capture_loop, args=(cap, q), daemon=True
            )
            t.start()
            self.capture_threads.append(t)

        # ── 검출 결과 공유 (lock 보호) ──
        # detect_overlays[i] = 검출된 corners가 그려진 640x360 이미지 or None
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

        # ── 3단계: 합성+송출 ──
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.image_pub = self.create_publisher(
            CompressedImage, '/multi_view/image_compressed', qos_profile
        )

        # 카메라별 마지막 수신 프레임 캐시 (640x360)
        self.last_frames = [None] * self.num_cams

        # 송출 버퍼 큐
        self.publish_queue = queue.Queue(maxsize=10)
        self.publish_thread = threading.Thread(
            target=self._publish_loop, daemon=True
        )
        self.publish_thread.start()

        # FPS / Latency 이동 평균
        self.prev_time = 0.0
        self.frame_times = []
        self.latency_times = []
        self.window_size = 30

        # 메인 타이머 30Hz: 캡처 프레임 합성 + 검출 오버레이 → publish
        self.timer = self.create_timer(1.0 / 30.0, self._timer_callback)
        self.get_logger().info('MultiViewRemotePublisher started')

    # ── 캡처 스레드 ──
    def _capture_loop(self, cap, q):
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
                # 검출 결과를 프레임에 그린 후 640x360으로 축소
                overlay = frame.copy()
                cv2.drawChessboardCorners(
                    overlay, self.checkerboard, corners, ret_cb
                )
                overlay_small = cv2.resize(overlay, (640, 360))
                with self.detect_lock:
                    self.detect_overlays[cam_idx] = overlay_small
            else:
                with self.detect_lock:
                    self.detect_overlays[cam_idx] = None

    # ── 메인 타이머 콜백: 합성 + 오버레이 ──
    def _timer_callback(self):
        """30Hz: 캡처 프레임에 검출 오버레이를 덮어씌운 뒤 2x2 합성"""
        capture_time = None

        # 캡처 큐에서 최신 프레임 수집
        for i, q in enumerate(self.capture_queues):
            try:
                ts, frame = q.get_nowait()
                self.last_frames[i] = cv2.resize(frame, (640, 360))
                if capture_time is None:
                    capture_time = ts

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

        # 4개 카메라 모두 최소 1프레임 수신 전까지 대기
        if any(f is None for f in self.last_frames) or capture_time is None:
            return

        # 검출 오버레이가 있으면 해당 카메라 프레임을 교체
        with self.detect_lock:
            display_frames = []
            for i in range(self.num_cams):
                if self.detect_overlays[i] is not None:
                    display_frames.append(self.detect_overlays[i])
                else:
                    display_frames.append(self.last_frames[i])

        # 2x2 합성 (최종 1280x720)
        top = cv2.hconcat([display_frames[0], display_frames[1]])
        bottom = cv2.hconcat([display_frames[2], display_frames[3]])
        combined = cv2.vconcat([top, bottom])

        # FPS 이동 평균
        curr_time = time.time()
        if self.prev_time > 0:
            sec = curr_time - self.prev_time
            self.frame_times.append(sec)
            if len(self.frame_times) > self.window_size:
                self.frame_times.pop(0)
            avg_sec = sum(self.frame_times) / len(self.frame_times)
            fps = 1.0 / avg_sec if avg_sec > 0 else 0.0
        else:
            fps = 0.0
        self.prev_time = curr_time

        # Latency 이동 평균
        raw_latency = (curr_time - capture_time) * 1000
        self.latency_times.append(raw_latency)
        if len(self.latency_times) > self.window_size:
            self.latency_times.pop(0)
        latency_ms = sum(self.latency_times) / len(self.latency_times)

        # 오버레이
        cv2.putText(
            combined, f'FPS: {fps:.1f}', (20, 50),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2,
        )
        cv2.putText(
            combined, f'Latency: {latency_ms:.1f} ms', (20, 90),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2,
        )

        # JPEG 인코딩 후 송출 큐에 적재
        ret_enc, encoded = cv2.imencode(
            '.jpg', combined,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
        )
        if ret_enc:
            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.format = 'jpeg'
            msg.data = encoded.tobytes()
            if self.publish_queue.full():
                try:
                    self.publish_queue.get_nowait()
                except queue.Empty:
                    pass
            self.publish_queue.put(msg)

    # ── 송출 스레드 ──
    def _publish_loop(self):
        """50ms 간격으로 publish_queue에서 꺼내 Foxglove로 송출"""
        while self.is_running:
            try:
                msg = self.publish_queue.get(timeout=0.1)
                self.image_pub.publish(msg)
            except queue.Empty:
                continue
            time.sleep(0.05)

    def __del__(self):
        """소멸자: 스레드 종료 및 카메라 자원 해제"""
        self.is_running = False
        for t in self.detect_threads:
            if t.is_alive():
                t.join(timeout=1.0)
        if hasattr(self, 'publish_thread') and self.publish_thread.is_alive():
            self.publish_thread.join(timeout=1.0)
        for t in self.capture_threads:
            if t.is_alive():
                t.join(timeout=1.0)
        for cap in self.caps:
            if cap.isOpened():
                cap.release()


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
