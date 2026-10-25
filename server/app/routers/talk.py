"""대화와 놀이 (CON-05, CON-06, GAME-01·06·07) — 어르신 앱이 부르는 주소들. STT는 폰에서 하고 글자만 보낸다."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import elder_user
from ..db import get_db, one, rows
from ..schemas import ConversationOut, SayOut, StartOut, TurnOut, TurnRow
from ..service import (active_play, add_turn, call_ai, end_conversation, finish_play, handle_turn, play_view,
                       lock_elder, start_conversation, start_play)

router = APIRouter(tags=["대화·놀이 (어르신 앱)"])


def _mine(db, cid: int, elder_id: int, active: bool = True) -> dict:
    """내 대화인지 확인. 진행 중인 대화를 바꾸는 요청이면 잠가서, 같은 대화에 대한 요청
    (두 번 누름, 앱 재전송, 30분 정리 작업)이 동시에 섞이지 않고 하나씩 처리되게 한다."""
    if active:
        lock_elder(db, elder_id)
    c = one(db, "SELECT * FROM conversations WHERE id = :c AND elder_id = :e" + (" FOR UPDATE" if active else ""),
            c=cid, e=elder_id)
    if not c:
        raise HTTPException(404, "대화를 찾을 수 없습니다")
    if active and c["status"] != "ACTIVE":
        raise HTTPException(409, "이미 끝난 대화예요. 새 대화를 시작해 주세요")
    return c


@router.post("/conversations", response_model=StartOut)
def start(e=Depends(elder_user), db=Depends(get_db)):
    """대화 시작 (앱을 열거나 알림을 눌렀을 때). AI가 먼저 인사한다."""
    return start_conversation(db, e["id"])


class TurnIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@router.post("/conversations/{cid}/turns", response_model=TurnOut)
def turn(cid: int, body: TurnIn, e=Depends(elder_user), db=Depends(get_db)):
    """어르신 말 한 마디 → AI 답 한 마디 (+ 놀이 상태)"""
    _mine(db, cid, e["id"])
    return handle_turn(db, e["id"], cid, body.text)


@router.post("/conversations/{cid}/end", response_model=TurnOut)
def end(cid: int, e=Depends(elder_user), db=Depends(get_db)):
    _mine(db, cid, e["id"])
    end_conversation(db, cid)
    return {"say": "", "ended": True, "play": None, "saved": {"memories": 0, "daily": 0, "rejected": 0}}


class PlayIn(BaseModel):
    kind: Literal["RECALL", "QUIZ"]
    quiz_category: Literal["MUSIC", "FOOD", "TRAVEL"] | None = None
    memory_id: int | None = None


@router.post("/conversations/{cid}/play", response_model=SayOut)
def choose_play(cid: int, body: PlayIn, e=Depends(elder_user), db=Depends(get_db)):
    """놀이 선택 화면에서 직접 고른 경우 (GAME-01). AI가 놀이를 열어 준다."""
    _mine(db, cid, e["id"])
    try:
        start_play(db, e["id"], cid, body.kind, body.quiz_category, body.memory_id)
    except ValueError as err:
        raise HTTPException(409, str(err))
    out, _ = call_ai(db, e["id"], cid, "PLAY_STARTED")
    add_turn(db, cid, "AI", out.say)
    return {"say": out.say, "play": play_view(db, e["id"])}


@router.post("/conversations/{cid}/play/stop", response_model=SayOut)
def stop_play(cid: int, e=Depends(elder_user), db=Depends(get_db)):
    """화면의 '그만하기' 버튼. 일반 대화로 돌아간다."""
    _mine(db, cid, e["id"])
    p = active_play(db, e["id"])
    if p:
        finish_play(db, p["id"], "STOPPED")
    say = "알겠어요, 놀이는 여기까지 하고 다시 이야기 나눠요."
    add_turn(db, cid, "AI", say)
    return {"say": say, "play": None}


@router.get("/me/conversations", response_model=list[ConversationOut])
def my_conversations(limit: int = Query(20, ge=1, le=100), e=Depends(elder_user), db=Depends(get_db)):
    return rows(db, """SELECT id, started_at, ended_at, status FROM conversations WHERE elder_id = :e
                       ORDER BY started_at DESC LIMIT :n""", e=e["id"], n=limit)


@router.get("/me/conversations/{cid}/turns", response_model=list[TurnRow])
def my_turns(cid: int, e=Depends(elder_user), db=Depends(get_db)):
    """대화 원문은 어르신 본인만 볼 수 있다 (보호자 API에는 원문이 없음)"""
    _mine(db, cid, e["id"], active=False)
    return rows(db, "SELECT seq, speaker, text FROM turns WHERE conversation_id = :c ORDER BY seq", c=cid)
