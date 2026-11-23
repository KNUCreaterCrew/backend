from fastapi import APIRouter

router = APIRouter(tags=["health"])


# 외부 업타임 서비스가 무료 플랜 서버를 깨워 두려고 이 경로를 부른다.
# UptimeRobot처럼 HEAD로 확인하는 서비스도 있어 GET과 함께 연다(FastAPI는 HEAD를 자동으로 열지 않는다).
@router.api_route("/health", methods=["GET", "HEAD"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
