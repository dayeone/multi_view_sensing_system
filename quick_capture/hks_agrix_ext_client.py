"""
HKS Agrix 플랫폼 ext-api 외부 클라이언트
- 이미지 파일 업로드: POST /api/v1/ext/files
- AI 데이터셋 이미지셋 등록: POST /api/v1/ext/ai-dataset/imageset
"""

import hashlib
import hmac
import base64
import time
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("API_URL", "https://agrix.hks24.co.kr")
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
AIDATASET_ID = int(os.getenv("AIDATASET_ID", "5"))

print(f"불러온 액세스 키: {ACCESS_KEY}")


def create_hmac_auth_header(access_key: str, secret_key: str) -> dict:
    """HMAC-SHA256 인증 헤더 생성 (서버 HmacUtils.sign()과 동일)"""
    timestamp = int(time.time())
    signature = base64.b64encode(
        hmac.new(
            secret_key.encode("utf-8"),
            str(timestamp).encode("utf-8"),
            hashlib.sha256
        ).digest()
    ).decode("utf-8")

    return {
        "Authorization": f"HMAC-SHA256 accessKey={access_key}, signature={signature}, timestamp={timestamp}"
    }


def upload_image(image_path: str) -> str:
    """이미지 파일 업로드 → 업로드된 URL 반환"""
    headers = create_hmac_auth_header(ACCESS_KEY, SECRET_KEY)
    url = f"{API_URL}/api/v1/ext/files"

    with open(image_path, "rb") as f:
        response = requests.post(url, headers=headers, files={"uploadFile": f})

    if response.status_code != 200:
        print(f"서버 에러 상세: {response.text}")

    response.raise_for_status()
    data = response.json()
    print(f"[업로드 성공] {data}")
    return data["url"]


def register_imageset(aidataset_id: int, image_url: str) -> dict:
    """AI 데이터셋 이미지셋 등록"""
    headers = create_hmac_auth_header(ACCESS_KEY, SECRET_KEY)
    headers["Content-Type"] = "application/json"
    url = f"{API_URL}/api/v1/ext/ai-dataset/imageset"

    response = requests.post(url, headers=headers, json={
        "aidatasetId": aidataset_id,
        "imageUrl": image_url,
    })

    response.raise_for_status()
    data = response.json()
    print(f"[이미지셋 등록 성공] id={data['id']}, url={data['imageUrl']}")
    return data


def upload_and_register(image_path: str, aidataset_id: int = AIDATASET_ID):
    """이미지 업로드 → 이미지셋 등록 한 번에"""
    print(f"\n[1/2] 이미지 업로드: {image_path}")
    image_url = upload_image(image_path)

    print(f"[2/2] 이미지셋 등록: aidatasetId={aidataset_id}")
    return register_imageset(aidataset_id, image_url)


# ============================================================
# 단독 실행 테스트
# ============================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용법: python hks_agrix_ext_client.py <이미지파일경로>")
        print("예시:   python hks_agrix_ext_client.py sample.jpg")
        sys.exit(1)

    image_path = sys.argv[1]
    result = upload_and_register(image_path)
    print(f"\n완료: 이미지셋 ID={result['id']}")
