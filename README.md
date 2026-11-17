# ZeroFrame Backend

ZeroFrame은 경북대학교 컴퓨터학부 학생이 과방이나 실습실에 가기 전에 빈자리를 확인하는 서비스입니다. 이 저장소는 **실습실 장치가 확인한 좌석 상태를 학생의 모바일 좌석도에 전달하는 FastAPI 서버**를 위한 공간입니다.

## 로컬에서 실행하기

개발 환경은 Python 3.13과 uv를 사용합니다. uv가 필요한 경우 [공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)를 참고하세요.

```sh
git clone https://github.com/KNUCreaterCrew/backend.git
cd backend
uv sync --locked
uv run uvicorn app.main:app --reload
```

`uv sync --locked`는 저장소의 `uv.lock`에 기록된 버전으로 가상환경을 구성합니다. 서버가 켜지면 브라우저에서 `http://127.0.0.1:8000/health`를 열어 HTTP 200과 다음 응답을 확인할 수 있습니다.

```json
{"status": "ok"}
```

같은 폴더에서 아래 명령을 실행하면 상태 확인, 방 조회, 혼잡도 집계 테스트를 실행합니다.

```sh
uv run python -m pytest
```

## 방 하나의 좌석 현황 조회

서버를 실행한 뒤 `http://127.0.0.1:8000/api/v1/rooms/IT4-101`을 열면 제1실습실의 좌석 배치와 요약을 볼 수 있습니다. 이 방은 프론트엔드 연동을 위한 고정 예시입니다. 좌석 상태, 관측 시각, 장치 연결 여부까지 모두 예시 값입니다.

| 전체 | 빈자리 | 확인 불가 | 혼잡도 |
| --- | --- | --- | --- |
| 4석 | 1석 (A1) | 1석 (B2) | `MODERATE` |

A2는 사용 중이고 B1에는 짐이 있습니다. A1만 이용 가능하므로 빈자리 비율은 1/4입니다. `seats` 배열에는 각 좌석의 상태, 배치 좌표, 콘센트와 창가 여부, 상태 변경 시각, 마지막 확인 시각이 들어갑니다. 등록되지 않은 방 ID로 조회하면 HTTP 404를 반환합니다.

### 요청을 따라 코드 읽기

`app/main.py`는 FastAPI 앱을 만들고 라우터를 등록합니다. 방 조회 요청 한 건은 아래 순서로 처리됩니다.

| 순서 | 코드 | 맡은 일 |
| --- | --- | --- |
| 1 | [라우터](app/routers/rooms.py) | URL에서 방 ID를 받아 서비스를 호출합니다. 방을 찾지 못하면 HTTP 404로 응답합니다. |
| 2 | [서비스](app/services/rooms.py) → [저장소](app/repositories/rooms.py) | 서비스가 방 ID로 조회하면 저장소가 해당 방의 좌석 목록을 돌려줍니다. 현재 저장소는 시작할 때 [예시 데이터](app/data/example-room.json)를 읽습니다. |
| 3 | [서비스](app/services/rooms.py) | 읽어 온 좌석 목록에서 `EMPTY`와 `UNKNOWN`을 따로 세고 빈자리 비율로 혼잡도를 계산합니다. 목록과 집계를 한 응답에 담습니다. |
| 4 | [스키마](app/schemas/rooms.py) | `RoomSnapshot`은 응답의 필드와 타입을 정의합니다. FastAPI가 이 형식으로 JSON을 반환하고 `/docs`에 응답 구조를 표시합니다. |

집계 기준을 바꿀 때는 서비스를, 데이터를 읽는 방식을 바꿀 때는 저장소를 살펴보면 됩니다. [공통 연동 명세](https://github.com/KNUCreaterCrew/docs/blob/main/INTERFACES.md)

## 학생이 좌석도를 열면

| 상황 | 백엔드가 맡을 일 |
| --- | --- |
| 학생이 제1실습실을 선택합니다. | 방의 좌석 배치와 최근 상태를 함께 반환합니다. 빈자리와 확인 불가 좌석은 따로 집계합니다. |
| 다른 학생이 A1에 앉습니다. | Vision 장치가 보낸 상태를 반영하고, 이 방을 보고 있는 학생들에게 WebSocket으로 변경을 알립니다. |
| 실습실 장치의 연결이 끊깁니다. | 30초 이상 보고가 없으면 해당 방의 좌석을 ‘확인 불가’로 바꿉니다. 연결이 돌아오면 새로 확인된 자리부터 상태를 갱신합니다. |

카메라 영상과 좌석 이미지는 실습실 장치 안에서 처리합니다. 백엔드가 받는 데이터는 방·좌석 ID, 상태, 관측 시각 등의 JSON입니다.

서비스의 기획과 시스템 간 연동 명세는 공통 문서 저장소에서, 카메라 관측과 좌석 판정은 Vision 저장소에서 관리합니다. [공통 문서](https://github.com/KNUCreaterCrew/docs) · [Vision](https://github.com/KNUCreaterCrew/vision)
