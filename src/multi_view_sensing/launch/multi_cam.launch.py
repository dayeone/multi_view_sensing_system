import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    enable_metrics_log = LaunchConfiguration('enable_metrics_log')

    # 4개의 독립된 카메라 노드 정의
    cam0_node = Node(
        package='multi_view_sensing',
        executable='calib_collector',
        name='cam0_collector',
        parameters=[{
            'device_path': '/dev/video0',
            'enable_metrics_log': enable_metrics_log,
        }],
        output='screen'
    )
    cam1_node = Node(
        package='multi_view_sensing',
        executable='calib_collector',
        name='cam1_collector',
        parameters=[{
            'device_path': '/dev/video4',
            'enable_metrics_log': enable_metrics_log,
        }],
        output='screen'
    )
    cam2_node = Node(
        package='multi_view_sensing',
        executable='calib_collector',
        name='cam2_collector',
        parameters=[{
            'device_path': '/dev/video8',
            'enable_metrics_log': enable_metrics_log,
        }],
        output='screen'
    )
    cam3_node = Node(
        package='multi_view_sensing',
        executable='calib_collector',
        name='cam3_collector',
        parameters=[{
            'device_path': '/dev/video12',
            'enable_metrics_log': enable_metrics_log,
        }],
        output='screen'
    )

    # 런치 시스템에 노드 4개 동시 실행 요청
    return LaunchDescription([
        DeclareLaunchArgument(
            'enable_metrics_log',
            default_value='false',
            description='Log per-iteration metrics (cap/det FPS, latency) to CSV',
        ),
        cam0_node,
        cam1_node,
        cam2_node,
        cam3_node
    ])
