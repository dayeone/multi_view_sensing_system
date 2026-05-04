from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    enable_metrics_log = LaunchConfiguration('enable_metrics_log')
    display_mode = LaunchConfiguration('display_mode')

    return LaunchDescription([
        DeclareLaunchArgument(
            'enable_metrics_log',
            default_value='false',
            description='Log per-publish metrics (cap/det/pub FPS, latency, sync) to CSV',
        ),
        DeclareLaunchArgument(
            'display_mode',
            default_value='local',
            description='Display mode: local (OpenCV window) or remote (ROS topic publish)',
        ),
        Node(
            package='multi_view_sensing',
            executable='multi_view_remote_publisher',
            name='multi_view_remote_publisher',
            output='screen',
            parameters=[{
                'device_paths': [
                    '/dev/video0',
                    '/dev/video4',
                    '/dev/video8',
                    '/dev/video12',
                ],
                'enable_metrics_log': enable_metrics_log,
                'display_mode': display_mode,
            }],
        ),
    ])
