from setuptools import find_packages, setup

package_name = 'multi_view_sensing'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='jay',
    maintainer_email='jay@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            # 터미널에서 'streamer'라고 치면 이 코드가 실행되도록 설정
            'streamer = multi_view_sensing.camera_streamer:main',
            'calib_collector = multi_view_sensing.calib_data_collector:main'
        ],
    },
)
