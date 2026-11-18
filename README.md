# ZeroFrame Backend

ZeroFrame은 경북대학교 컴퓨터학부 학생이 과방이나 실습실에 가기 전에 빈자리를 확인하는 서비스입니다. 이 저장소는 **실습실 장치가 확인한 좌석 상태를 학생의 모바일 좌석도에 전달하는 FastAPI 서버**를 위한 공간입니다.

## 로컬에서 실행하기

개발 환경은 Python 3.13과 uv를 사용합니다. uv가 필요한 경우 [공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)를 참고하세요.

```sh
git clone https://github.com/KNUCreaterCrew/backend.git
cd backend
uv sync --locked
echo "EDGE_API_KEY=local-dev-key" > .env
uv run uvicorn app.main:app --reload
```

`uv sync --locked`는 저장소의 `uv.lock`에 기록된 버전으로 가상환경을 구성합니다. 서버는 장치 인증 키를 환경 변수 `EDGE_API_KEY`나 `.env` 파일에서 읽으며, 키가 없으면 시작하지 않습니다. `.env`는 저장소에 올리지 않습니다. 위 키는 로컬 확인용 예시이므로 실제 장치에는 따로 만든 키를 씁니다. 서버가 켜지면 브라우저에서 `http://127.0.0.1:8000/health`를 열어 HTTP 200과 다음 응답을 확인할 수 있습니다.

```json
{"status": "ok"}
```

같은 폴더에서 아래 명령을 실행하면 상태 확인, 방 조회, 혼잡도 집계, 장치 보고 반영 테스트를 실행합니다. 테스트는 테스트용 키를 주입하므로 `.env`가 없어도 됩니다.

```sh
uv run python -m pytest
```

PR을 열거나 `main`에 push하면 GitHub Actions가 같은 명령으로 테스트를 실행합니다. 저장소의 `.gitattributes`는 Windows와 WSL 어느 쪽에서 내려받아도 파일 줄바꿈을 LF로 맞춥니다.

## 방 하나의 좌석 현황 조회

서버를 실행한 뒤 `http://127.0.0.1:8000/api/v1/rooms/IT4-101`을 열면 제1실습실의 좌석 배치와 요약을 볼 수 있습니다. 방과 좌석 정보는 두 곳에서 옵니다.

| 정보 | 보관 위치 | 바뀌는 때 |
| --- | --- | --- |
| 방 이름, 좌석 ID·라벨, 배치 좌표, 콘센트·창가 여부 | [배치 설정 파일](app/data/rooms.json) | 사람이 파일을 고치고 서버를 다시 시작할 때 |
| 좌석 상태와 사유, 상태 변경 시각, 마지막 확인 시각, 장치 연결 여부 | 서버 메모리 | 장치 보고와 연결 감시에 따라 |

방금 시작한 서버는 아직 장치 보고를 받지 못했으므로 모든 좌석이 확인 불가입니다.

| 전체 | 빈자리 | 확인 불가 | 혼잡도 | 장치 연결 |
| --- | --- | --- | --- | --- |
| 4석 | 0석 | 4석 | `HIGH` | `false` |

각 좌석은 `UNKNOWN`·`EDGE_OFFLINE`이고 마지막 확인 시각은 `null`, 상태 변경 시각은 서버 시작 시각입니다. 네 좌석이 각각 빈자리·사용 중·짐 있음·확인 불가인 예시는 [테스트](tests/test_rooms.py)에서 메모리 상태를 바꿔 재현합니다. 등록되지 않은 방 ID로 조회하면 HTTP 404를 반환합니다.

### 요청을 따라 코드 읽기

`app/main.py`의 `create_app()`이 FastAPI 앱을 만들고 라우터를 등록합니다. 앱이 시작될 때(lifespan) [배치 설정 파일](app/data/rooms.json)을 읽어 방 저장소를 만들고 `app.state`에 둡니다. 방 조회 요청 한 건은 아래 순서로 처리됩니다.

| 순서 | 코드 | 맡은 일 |
| --- | --- | --- |
| 1 | [라우터](app/routers/rooms.py) | URL에서 방 ID를 받고, [의존성](app/dependencies.py)으로 저장소를 주입받아 서비스를 호출합니다. 방을 찾지 못하면 HTTP 404로 응답합니다. |
| 2 | [서비스](app/services/rooms.py) → [저장소](app/repositories/rooms.py) | 서비스가 방 ID로 조회하면 저장소가 방의 배치와 메모리의 최신 상태([내부 모델](app/models/rooms.py))를 함께 돌려줍니다. |
| 3 | [서비스](app/services/rooms.py) | 좌석마다 배치와 상태를 합친 뒤 `EMPTY`와 `UNKNOWN`을 따로 세고 빈자리 비율로 혼잡도를 계산합니다. 목록과 집계를 한 응답에 담습니다. |
| 4 | [응답 스키마](app/schemas/rooms.py) | `RoomSnapshot`은 응답의 필드와 타입을 정의합니다. 내부 모델과 분리돼 있어 저장 방식이 바뀌어도 응답 형식은 유지됩니다. FastAPI가 이 형식으로 JSON을 반환하고 `/docs`에 응답 구조를 표시합니다. |

엔드포인트는 `async def`로 작성합니다. 방 상태는 프로세스 메모리에 있으므로 uvicorn은 워커 1개로 실행합니다. 테스트는 `create_app()`으로 매번 새 앱과 새 저장소를 띄우며, 다른 방 데이터를 넣은 저장소를 주입할 수도 있습니다.

집계 기준을 바꿀 때는 서비스를, 데이터를 읽는 방식을 바꿀 때는 저장소를 살펴보면 됩니다. [공통 연동 명세](https://github.com/KNUCreaterCrew/docs/blob/main/INTERFACES.md)

## 장치의 상태 보고 반영

Vision 장치는 맡은 좌석 전체의 상태를 `POST /api/v1/rooms/{room_id}/seats/status`로 보냅니다. 상태가 바뀌면 바로 보내고, 바뀌지 않아도 10초마다 보냅니다. 요청 형식과 반영 규칙은 [공통 연동 명세](https://github.com/KNUCreaterCrew/docs/blob/main/INTERFACES.md)를 따릅니다. 서버를 켠 뒤 아래 예시 보고를 보내고 방을 다시 조회하면 A1이 사용 중으로 바뀌어 있습니다.

```sh
curl -X POST http://127.0.0.1:8000/api/v1/rooms/IT4-101/seats/status \
  -H 'Content-Type: application/json' -H 'X-Edge-Api-Key: local-dev-key' \
  -d '{"room_id":"IT4-101","timestamp":"2026-11-24T10:15:30+09:00","inference_fps":2.1,"saved_frames_count":0,
       "seats":[{"seat_id":"A-01","status":"OCCUPIED","confidence":null,"last_observed_at":"2026-11-24T10:15:29+09:00"}]}'
```

| 경우 | 응답 | 방 상태 |
| --- | --- | --- |
| 키가 없거나 틀림 | 401 | 그대로 |
| 등록되지 않은 방 | 404 | 그대로 |
| 형식 오류, 등록되지 않은 좌석이 섞임, 경로와 본문의 방 ID가 다름 | 422 | 그대로. 일부 좌석만 바뀌지 않습니다. |
| 정상 보고 | 200, `updated_count`는 status·reason이 바뀐 좌석 수 | 보고에 담긴 좌석만 바뀝니다. |

[서비스](app/services/reports.py)는 방별 잠금 안에서 보고를 검증하고, 저장된 상태와 비교해 바뀐 좌석 목록을 만든 뒤 한꺼번에 저장합니다. 같은 보고가 다시 오면 바뀐 좌석이 없으므로 `updated_count`가 0이고 방의 `version`도 그대로입니다. 새 관측이 없는 하트비트는 마지막 확인 시각을 바꾸지 않습니다. 서버는 보고를 받은 시각(`server_time`)을 방마다 기록하며, 이후 장치 연결 판단에 이 시각을 씁니다.

## 학생이 좌석도를 열면

| 상황 | 백엔드가 맡을 일 |
| --- | --- |
| 학생이 제1실습실을 선택합니다. | 방의 좌석 배치와 최근 상태를 함께 반환합니다. 빈자리와 확인 불가 좌석은 따로 집계합니다. |
| 다른 학생이 A1에 앉습니다. | Vision 장치가 보낸 상태를 반영하고, 이 방을 보고 있는 학생들에게 WebSocket으로 변경을 알립니다. |
| 실습실 장치의 연결이 끊깁니다. | 30초 이상 보고가 없으면 해당 방의 좌석을 ‘확인 불가’로 바꿉니다. 연결이 돌아오면 새로 확인된 자리부터 상태를 갱신합니다. |

카메라 영상과 좌석 이미지는 실습실 장치 안에서 처리합니다. 백엔드가 받는 데이터는 방·좌석 ID, 상태, 관측 시각 등의 JSON입니다.

서비스의 기획과 시스템 간 연동 명세는 공통 문서 저장소에서, 카메라 관측과 좌석 판정은 Vision 저장소에서 관리합니다. [공통 문서](https://github.com/KNUCreaterCrew/docs) · [Vision](https://github.com/KNUCreaterCrew/vision)
