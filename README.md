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

같은 폴더에서 아래 명령을 실행하면 상태 확인 API의 응답 코드와 본문을 테스트합니다.

```sh
uv run python -m pytest
```

## 학생이 좌석도를 열면

| 상황 | 백엔드가 맡을 일 |
| --- | --- |
| 학생이 제1실습실을 선택합니다. | 방의 좌석 배치와 최근 상태를 함께 반환합니다. 빈자리와 확인 불가 좌석은 따로 집계합니다. |
| 다른 학생이 A1에 앉습니다. | Vision 장치가 보낸 상태를 반영하고, 이 방을 보고 있는 학생들에게 WebSocket으로 변경을 알립니다. |
| 실습실 장치의 연결이 끊깁니다. | 30초 이상 보고가 없으면 해당 방의 좌석을 ‘확인 불가’로 바꿉니다. 연결이 돌아오면 새로 확인된 자리부터 상태를 갱신합니다. |

카메라 영상과 좌석 이미지는 실습실 장치 안에서 처리합니다. 백엔드가 받는 데이터는 방·좌석 ID, 상태, 관측 시각 등의 JSON입니다.

서비스의 기획과 시스템 간 연동 명세는 공통 문서 저장소에서, 카메라 관측과 좌석 판정은 Vision 저장소에서 관리합니다. [공통 문서](https://github.com/KNUCreaterCrew/docs) · [Vision](https://github.com/KNUCreaterCrew/vision)
