from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    enable_metrics_log = LaunchConfiguration('enable_metrics_log')

    return LaunchDescription([
        DeclareLaunchArgument(
            'enable_metrics_log',
            default_value='false',
            description='Log per-publish metrics (cap/det/pub FPS, latency) to CSV',
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
            }],
        ),
    ])
