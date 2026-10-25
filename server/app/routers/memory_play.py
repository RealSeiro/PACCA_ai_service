"""기억 조회·삭제 (MEM-06), 놀이 참여 기록 (GAME-08), 퀴즈 분야 목록 — 어르신 본인용"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import elder_user
from ..config import KST
from ..db import get_db, rows, run
from ..schemas import Category, MemoryOut, Ok, PlayStatsOut
from ..service import QUIZ_LABELS

router = APIRouter(tags=["기억·놀이 기록 (어르신 앱)"])


@router.get("/me/memories", response_model=list[MemoryOut])
def my_memories(e=Depends(elder_user), db=Depends(get_db)):
    """'AI가 기억하는 나' 화면. 본인 것만 나온다."""
    return rows(db, """SELECT id, kind, content, topic, created_at FROM memories WHERE elder_id = :e
                       ORDER BY created_at DESC""", e=e["id"])


@router.delete("/me/memories/{mid}", response_model=Ok)
def forget(mid: int, e=Depends(elder_user), db=Depends(get_db)):
    """기억 삭제. 다른 사람의 기억 번호를 넣어도 elder_id 조건 때문에 지워지지 않는다."""
    # 이 기억으로 회상 놀이를 하던 중이면 놀이부터 끝낸다 (바탕 기억 없이 놀이가 이어지지 않게)
    run(db, """UPDATE play_sessions SET status = 'STOPPED', ended_at = now(), current_question_id = NULL
               WHERE elder_id = :e AND memory_id = :m AND status = 'ACTIVE'""", m=mid, e=e["id"])
    r = run(db, "DELETE FROM memories WHERE id = :m AND elder_id = :e", m=mid, e=e["id"])
    if r.rowcount == 0:
        raise HTTPException(404, "기억을 찾을 수 없습니다")
    return {"ok": True}


@router.get("/quiz/categories", response_model=list[Category])
def quiz_categories():
    return [{"code": k, "label": v} for k, v in QUIZ_LABELS.items()]


def play_stats(db, elder_id: int, since, until) -> list[dict]:
    """놀이 종류별 참여 횟수 (GAME-08, FAM-09)"""
    return rows(db, """
        SELECT k.kind,
               COUNT(p.id) AS sessions,
               COUNT(p.id) FILTER (WHERE p.status = 'COMPLETED') AS completed,
               COALESCE(SUM((SELECT COUNT(*) FROM quiz_answers a WHERE a.play_session_id = p.id)), 0) AS quiz_answered,
               COALESCE(SUM((SELECT COUNT(*) FROM quiz_answers a WHERE a.play_session_id = p.id AND a.is_correct)), 0)
                 AS quiz_correct
        FROM (VALUES ('RECALL'), ('QUIZ')) AS k(kind)
        LEFT JOIN play_sessions p ON p.kind = k.kind AND p.elder_id = :e AND p.started_at >= :a AND p.started_at < :b
        GROUP BY k.kind ORDER BY k.kind""", e=elder_id, a=since, b=until)


@router.get("/me/plays/stats", response_model=PlayStatsOut)
def my_play_stats(days: int = Query(7, ge=1, le=365), e=Depends(elder_user), db=Depends(get_db)):
    now = datetime.now(KST)
    return {"days": days, "stats": play_stats(db, e["id"], now - timedelta(days=days), now + timedelta(seconds=1))}
