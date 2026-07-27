#!/usr/bin/env bash
# NUC2(SI 납품 상태) 매니페스트 수집 스크립트
# 사용법: NUC2 터미널에서  bash nuc2_manifest.sh
# 결과는 ~/nuc2_manifest/ 폴더에 저장됨. 외장하드에도 복사 보관 권장.
set -u

OUT="$HOME/nuc2_manifest"
mkdir -p "$OUT"
cd "$OUT" || exit 1

echo "[1/8] 디스크 레이아웃 (내장 디스크 모델/용량 확인용 - 중요)"
lsblk -o NAME,MODEL,SIZE,TYPE,MOUNTPOINT > disk_layout.txt

echo "[2/8] 설치된 apt 패키지 전체"
dpkg -l > apt_packages.txt

echo "[3/8] 수동 설치 apt 패키지"
apt-mark showmanual > apt_manual.txt

echo "[4/8] pip 패키지"
pip3 freeze > pip_packages.txt 2>/dev/null || echo "(pip3 없음)" > pip_packages.txt

echo "[5/8] ROS 관련 패키지"
dpkg -l | grep -i ros > ros_packages.txt 2>/dev/null || true

echo "[6/8] 시스템 정보"
{ uname -a; echo "---"; lsb_release -a 2>/dev/null; } > system_info.txt

echo "[7/8] 네트워크 구성"
ip a > network.txt 2>/dev/null || true
cp -r /etc/netplan "$OUT/netplan" 2>/dev/null || true

echo "[8/8] 완료. 결과 폴더: $OUT"
ls -la "$OUT"
echo
echo ">> disk_layout.txt 를 열어 내장 디스크 용량이 2TB 이하인지 확인하세요."
