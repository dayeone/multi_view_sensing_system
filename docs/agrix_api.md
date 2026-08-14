# HKS Agrix 서버 연동 매뉴얼

취득 이미지와 로봇 상태를 HK 솔루션즈 Agrix 플랫폼에 전송하기 위한 규격과 절차.

- 서버: `https://agrix.hks24.co.kr`
- MQTT 브로커: `device.agrix.hks24.co.kr:8883`

---

## 1. 자격증명 체계 — 2종

**Agrix는 용도가 다른 자격증명 두 벌을 운영한다.** 두 벌 모두 필드 이름이
`ACCESS_KEY` / `SECRET_KEY`로 동일하고 길이도 같아, 파일만 봐서는 구분되지 않는다.
**용도를 혼동하면 인증에 실패한다.**

| 구분 | 디바이스 키 | ext-api 키 |
|---|---|---|
| **용도** | 로봇·센서 상태 보고 | **이미지 업로드**, 데이터셋 등록 |
| **범위** | 기기 단위 | 계정 단위 |
| **발급** | `POST /api/v1/devices/register` → 웹 디바이스 관리 페이지에서 업체 승인 | 계정 발급 (디바이스 등록과 무관) |
| **사용처** | MQTT 브로커, `/api/v1/devices/telemetry` | `/api/v1/ext/files`, `/api/v1/ext/ai-dataset/imageset` |
| **파일** | `~/data_server_upload_system/device` | `~/data_server_upload_system/.env` |

**이미지 업로드에는 ext-api 키를 쓴다.** 디바이스 키로는 업로드되지 않는다.

ext-api 키는 계정 단위이므로 **여러 기기가 공유해도 된다.** 업로드 API 본문이
`{aidatasetId, imageUrl}` 뿐이라 기기 식별을 하지 않기 때문이다. 기기 구분은
디바이스 키·MQTT 쪽이 담당한다.

---

## 2. 인증 방식 — HMAC-SHA256

비밀키를 전송하지 않는다. 비밀키로 **현재 UNIX 시각에 서명**을 만들어 그 서명만 보낸다.

```
Authorization: HMAC-SHA256 accessKey=<키>, signature=<서명>, timestamp=<UNIX시각>
```

서명 생성 (`hks_agrix_ext_client.py:create_hmac_auth_header`):

```python
timestamp = int(time.time())
signature = base64.b64encode(
    hmac.new(secret_key.encode(), str(timestamp).encode(), hashlib.sha256).digest()
).decode()
```

**시각 동기화가 필수다.** 클라이언트 시계가 서버와 어긋나면 서명이 거부된다.
시스템 복원 직후 등 시계가 의심되면 아래로 확인한다.

```bash
date; curl -sI https://agrix.hks24.co.kr | grep -i "^date:"
```

---

## 3. 이미지 업로드 (ext-api)

2단계로 진행한다. 클라이언트: [quick_capture/hks_agrix_ext_client.py](../quick_capture/hks_agrix_ext_client.py)

### 3-1. 파일 업로드

```
POST /api/v1/ext/files
Content-Type: multipart/form-data
필드: uploadFile
```

응답:
```json
{ "id": 2294, "uuid": "ba1c...", "url": "https://agrix.hks24.co.kr/dn/file/20260813/ba1c....jpg", "completed": true }
```

### 3-2. 데이터셋 등록

```
POST /api/v1/ext/ai-dataset/imageset
Content-Type: application/json
{ "aidatasetId": 5, "imageUrl": "<3-1에서 받은 url>" }
```

응답:
```json
{ "id": 1995, "imageUrl": "https://..." }
```

### 실행

```bash
cd ~/data_server_upload_system && python3 hks_agrix_ext_client.py <이미지경로>
```

세션 폴더 일괄 업로드는 [quick_capture/uploader.py](../quick_capture/uploader.py)를 쓴다.
성공 시 `uploaded/`, 3회 재시도 실패 시 `failed/` 하위로 이동한다.

---

## 4. 텔레메트리 (디바이스 키)

### 4-1. HTTP

```
POST /api/v1/devices/telemetry
{ "IN:TEMP": 25.3, "IN:HUM": 60.1, "IN:CO2": 412.0 }
```

전송할 항목만 포함한다. 없는 센서는 키 자체를 제외한다.

키 목록은 [TELEMETRY_SPEC.md](../../data_server_upload_system/TELEMETRY_SPEC.md) 참조
(접두사 `IN:` 내부환경, `EXT:` 외부기상, `ROOT:` 근권부, `NUT:` 양액).

### 4-2. MQTT

```
브로커: device.agrix.hks24.co.kr:8883 (TLS)
인증  : username=DEVICE_KEY, password=DEVICE_SECRET
토픽  : devices/<DEVICE_KEY>/status
QoS   : 1 (AT_LEAST_ONCE)
```

상태 보고 예: `{"batteryLevel": 87, "uptimeSec": 12345}`

---

## 5. 오류 대응표

| 응답 | 메시지 | 원인 | 조치 |
|---|---|---|---|
| `401` | `서명이 올바르지 않습니다` | **① 키 종류 불일치** (디바이스 키로 ext-api 호출) | **키 종류를 먼저 확인한다** |
| `401` | 〃 | ② 시크릿 키 값 오류 | 웹페이지에서 재확인 |
| `401` | 〃 | ③ 클라이언트 시계 어긋남 | 시각 동기화 확인 |
| `403` | Forbidden | 승인 미완료 또는 IP 차단 | 웹 디바이스 관리 페이지에서 승인 상태 확인 |
| `404` | Not Found | `aidatasetId`가 없는 데이터셋 | ID 확인 |
| 연결 실패 | — | 인터넷 경로 없음 | 유선(로봇망)은 인터넷이 없다. 무선 연결 확인 |

**`401` 진단 순서: 키 종류 → 시계 → 값.** 서버가 키 종류 불일치도 "서명이
올바르지 않습니다"로 응답하므로, 값 오타부터 의심하면 원인을 찾지 못한다.

---

## 6. 설정 파일

`~/data_server_upload_system/.env` (git 추적 대상 아님, 기기마다 직접 생성)

```
# ext-api 키 — 이미지 업로드용
API_URL=https://agrix.hks24.co.kr
ACCESS_KEY=...
SECRET_KEY=...
AIDATASET_ID=5
```

### 새 기기 설정 절차

1. `.env` 생성 — **ext-api 키를 넣는다.** 편집기로 작성한다(`echo`는 셸 히스토리에 키가 남는다)
2. 의존성 확인 — `requests`, `python-dotenv`. `python3-dotenv` apt 패키지 사용
3. 업로드 시험 — `python3 hks_agrix_ext_client.py sample.jpg`
4. 웹페이지에서 해당 AI 데이터셋에 이미지가 실제로 들어갔는지 확인

**주의**: 시스템 파이썬에 `pip install -r requirements.txt`를 실행하지 않는다.
`numpy`가 2.x로 올라가 ROS 2 Humble이 동작하지 않게 된다. 부족한 패키지만 개별 설치한다.

---

## 7. 알려진 문제

| 위치 | 내용 |
|---|---|
| `hks_agrix_ext_client.py:22` | 액세스 키 전체를 stdout에 출력한다. 로그·스크린샷에 남으므로 마스킹 필요 |
| `hks_agrix_ext_client.py` | `quick_capture/`와 `data_server_upload_system/`에 동일 파일이 두 벌 존재. 정본을 하나로 정해야 한다 |
| `mqtt_test.py` | 디바이스 키·시크릿이 소스에 하드코딩되어 있고 두 값이 동일하다(미완성). `.env`에서 읽도록 수정 필요 |
