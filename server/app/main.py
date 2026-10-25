"""서버 시작점.  실행: uvicorn app.main:app --reload   →   http://localhost:8000/docs"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from . import scheduler
from .config import SCHEDULER_ENABLED
from .routers import accounts, guardian, memory_play, talk


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched = scheduler.start() if SCHEDULER_ENABLED else None
    yield
    if sched:
        sched.shutdown()


app = FastAPI(title="AI 친구 서버 v2", version="2.0", lifespan=lifespan)
for r in (accounts, talk, memory_play, guardian):
    app.include_router(r.router)


@app.exception_handler(IntegrityError)
def conflict(request: Request, exc: IntegrityError):
    """DB 규칙(중복 금지 등)에 걸린 요청은 서버 오류(500)가 아니라 '충돌(409)'로 답한다. 앱은 잠시 뒤 다시 시도하면 됨"""
    return JSONResponse(status_code=409, content={"detail": "같은 요청이 동시에 처리되는 중이에요. 잠시 뒤 다시 시도해 주세요"})


@app.get("/health", tags=["상태"])
def health():
    return {"ok": True}
