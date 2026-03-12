import rclpy
from rclpy.node import Node
import cv2
import numpy as np
import os
from datetime import datetime

class MultiCameraLite(Node):
    def __init__(self):
        """
        Initialize the Multi-Camera Streamer Node
        """
        super().__init__('multi_camera_lite')
        
        # Camera indices for Logitech BRIO (0, 4, 8, 12)
        self.camera_indices = [0, 4, 8, 12]
        self.save_path = os.path.expanduser('~/pest_control_ws/captured_images')
        
        # Ensure the storage directory exists
        os.makedirs(self.save_path, exist_ok=True)
        
        # Initialize camera captures with V4L2 backend
        self.caps = []
        for idx in self.camera_indices:
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            if cap.isOpened():
                # Set codec to MJPG for high bandwidth efficiency
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.caps.append(cap)
        
        # Create a timer to process frames at ~20 FPS (0.05s interval)
        self.timer = self.create_timer(0.05, self.timer_callback)
        self.win_name = 'Multi-View Feed (Experimental)'
        
        # Define window with NORMAL flag to allow manual resizing
        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)

        self.win_name = 'Multi-View Feed (Resizable)'
        
        # 1. Create a window that can be resized
        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
        
        # 2. [Solution] Set the initial window size to fit your monitor
        # 1280x720 is half the size of the combined image, making it easy to handle.
        cv2.resizeWindow(self.win_name, 1280, 720)
        
        # 3. [Optional] Keep the aspect ratio to prevent distortion
        cv2.setWindowProperty(self.win_name, cv2.WND_PROP_ASPECT_RATIO, cv2.WINDOW_KEEPRATIO)

    def timer_callback(self):
        """
        Capture, resize, and merge frames from 4 cameras
        """
        frames = []
        for cap in self.caps:
            ret, frame = cap.read()
            if ret:
                # Resize each frame to standard HD for merging
                frames.append(cv2.resize(frame, (1280, 720)))

        # Process when all 4 frames are captured successfully
        if len(frames) == 4:
            # Concatenate images into a 2x2 grid
            top_row = np.hstack(frames[0:2])
            bottom_row = np.hstack(frames[2:4])
            combined = np.vstack([top_row, bottom_row])
            
            # Render the final combined feed
            cv2.imshow(self.win_name, combined)
            
            # Handle keyboard inputs (Wait for 1ms)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('s'): # Save a snapshot on 's' key press
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                save_file = os.path.join(self.save_path, f'snapshot_{ts}.jpg')
                cv2.imwrite(save_file, combined)
                self.get_logger().info(f'Image saved at: {save_file}')

    def __del__(self):
        """
        Release camera resources on node destruction
        """
        for cap in self.caps:
            cap.release()
        cv2.destroyAllWindows()

def main(args=None):
    rclpy.init(args=args)
    node = MultiCameraLite()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()