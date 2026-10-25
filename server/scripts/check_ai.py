"""AI 모듈이 약속(ai/contract.py)을 지키는지 DB 없이 확인한다.
실행: python scripts/check_ai.py            → ai/__init__.py 가 가리키는 모듈 검사
      python scripts/check_ai.py ai.llm     → 특정 모듈 검사"""
import importlib
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.contract import RespondOut, SummaryOut  # noqa: E402
from app.rules import evidence_ok  # noqa: E402

mod = importlib.import_module(sys.argv[1] if len(sys.argv) > 1 else "ai")
CATS = [{"code": "MEAL", "label": "식사"}, {"code": "MOOD", "label": "기분"},
        {"code": "ACTIVITY", "label": "활동"}, {"code": "HEALTH", "label": "건강 관련 언급"}]
MEM = {"id": 7, "kind": "EXPERIENCE", "content": "젊을 때 남편과 제주도 여행을 다녀옴", "topic": "TRAVEL"}


def ctx(event="TURN", play=None, allowed=True, memories=(MEM,)):
    return {"event": event, "today": date.today().isoformat(), "now": "14:00", "weekday": 1,
            "elder": {"id": 1, "name": "이영자"}, "memories": list(memories),
            "daily": {"allowed_to_ask": allowed, "categories": CATS, "known_today": {}, "missing": ["MEAL", "MOOD"]},
            "quiz_categories": [{"code": "MUSIC", "label": "음악·트로트"}], "play_today": {"RECALL": 0, "QUIZ": 0},
            "play": play}


H = [{"seq": 1, "speaker": "AI", "text": "안녕하세요!"},
     {"seq": 2, "speaker": "ELDER", "text": "점심에 국수 먹었어, 나는 트로트를 좋아해"}]
QUIZ = {"session_id": 1, "kind": "QUIZ", "elder_turns": 1, "quiz_category": "MUSIC",
        "quiz": {"last_result": {"question": "...", "user_answer": "임영웅", "is_correct": True, "answer": "임영웅"},
                 "current_question": {"id": 2, "question": '"동백 아가씨"를 부른 가수는?', "hint": None},
                 "answered": 1, "total": 3, "finished": False, "correct": 1}}
fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"  통과  {name}")
    except Exception as e:
        fails += 1
        print(f"  실패  {name}\n        {e}")


def elder_said(h):
    return " ".join(t["text"] for t in h if t["speaker"] == "ELDER")


def t_start():
    out = RespondOut.model_validate(mod.respond([], ctx("START")))
    assert out.say, "첫 인사가 비어 있음"


def t_turn():
    out = RespondOut.model_validate(mod.respond(H, ctx()))
    said = [t["text"] for t in H if t["speaker"] == "ELDER"]
    for m in [*out.memory_candidates, *out.daily_info]:
        assert evidence_ok(m.evidence, said, m.content), \
            f"서버가 버리게 될 후보: content={m.content!r}, evidence={m.evidence!r} (contract.py 맨 위 규칙 참고)"
    for d in out.daily_info:
        assert d.category in {c["code"] for c in CATS}, f"없는 일상 항목: {d.category}"


def t_no_daily_when_not_allowed():
    out = RespondOut.model_validate(mod.respond(H, ctx(allowed=False)))
    assert not out.daily_check.asked, "allowed_to_ask=false인데 일상 질문을 함"


def t_quiz():
    out = RespondOut.model_validate(mod.respond(H, ctx(play=QUIZ)))
    assert "동백" in out.say, "다음 문제(current_question)를 읽어 주지 않음"


def t_summary():
    out = SummaryOut.model_validate(mod.summarize_day(date.today().isoformat(), {"MEAL": ["점심에 국수를 드심"]}, {}))
    assert set(out.summaries) <= {"MEAL"}, f"기록 없는 항목을 요약함: {set(out.summaries) - {'MEAL'}}"


print(f"검사 대상: {mod.__name__}")
check("respond: 대화 시작 인사", t_start)
check("respond: 기억·일상 후보의 근거가 실제 어르신 말인지", t_turn)
check("respond: 일상 질문 하루 1번 (allowed_to_ask=false면 안 물음)", t_no_daily_when_not_allowed)
check("respond: 퀴즈 중 다음 문제 읽어 주기", t_quiz)
check("summarize_day: 기록 있는 항목만 요약", t_summary)
print("\n모두 통과" if not fails else f"\n{fails}개 실패")
sys.exit(1 if fails else 0)
