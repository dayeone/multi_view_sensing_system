from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
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
            }],
        ),
    ])
