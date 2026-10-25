"""보호자 화면 (FAM-04, FAM-09): 날짜별 일상 요약과 놀이 참여 현황.
모든 조회는 관문 1(연결) → 관문 2(동의)를 지난다. 대화 원문과 기억은 보호자에게 아예 주지 않는다."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query

from ..auth import granted_categories, guardian_user, require_link
from ..config import KST
from ..db import get_db, rows
from ..schemas import DayBrief, DayOut
from .memory_play import play_stats

router = APIRouter(tags=["보호자 화면"])


@router.get("/elders/{elder_id}/days/{day}", response_model=DayOut)
def day_view(elder_id: int, day: date, g=Depends(guardian_user), db=Depends(get_db)):
    link_id = require_link(db, g["id"], elder_id)              # 관문 1
    allowed = granted_categories(db, link_id)                   # 관문 2
    cats = rows(db, "SELECT code, label, is_daily FROM share_categories ORDER BY sort")
    summ = {r["category"]: r["summary"] for r in rows(db, """SELECT category, summary FROM daily_summaries
                                                             WHERE elder_id = :e AND day = :d""", e=elder_id, d=day)}
    items = [{"category": c["code"], "label": c["label"], "summary": summ.get(c["code"])}
             for c in cats if c["is_daily"] and c["code"] in allowed]
    play = None
    if "PLAY" in allowed:
        a = datetime.combine(day, datetime.min.time(), tzinfo=KST)
        play = play_stats(db, elder_id, a, a + timedelta(days=1))
    return {"day": day, "items": items, "play": play,
            "hidden_categories": [c["code"] for c in cats if c["code"] not in allowed]}


@router.get("/elders/{elder_id}/days", response_model=list[DayBrief])
def recent_days(elder_id: int, days: int = Query(7, ge=1, le=31), g=Depends(guardian_user), db=Depends(get_db)):
    """최근 n일 목록 (요약이 있는 날인지, 놀이 몇 번 했는지 — 동의 범위 안에서)"""
    link_id = require_link(db, g["id"], elder_id)
    allowed = granted_categories(db, link_id)
    today = datetime.now(KST).date()
    out = []
    for i in range(min(days, 31)):
        d = today - timedelta(days=i)
        has = bool(rows(db, """SELECT 1 FROM daily_summaries WHERE elder_id = :e AND day = :d
                               AND category = ANY(CAST(:c AS text[])) LIMIT 1""", e=elder_id, d=d, c=list(allowed)))
        n = None
        if "PLAY" in allowed:
            n = rows(db, """SELECT COUNT(*) AS n FROM play_sessions WHERE elder_id = :e
                            AND (started_at AT TIME ZONE 'Asia/Seoul')::date = :d""", e=elder_id, d=d)[0]["n"]
        out.append({"day": d, "has_summary": has, "play_sessions": n})
    return out
