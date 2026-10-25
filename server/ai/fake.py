"""가짜 AI (규칙 기반). 진짜 LLM이 붙기 전까지 서버 전체를 끝까지 돌려 보기 위한 것.
입력·출력 모양은 ai/contract.py 약속과 똑같다. 말은 어색해도 '어떤 신호를 서버에 주는지'는 진짜와 같다."""
import re

STOP = ("그만", "안 할래", "안할래", "됐어", "하기 싫", "나중에 할")
YES = ("응", "네", "좋아", "그래", "해볼", "하자", "할래")
NO = ("아니", "싫어", "안 해", "안해", "다음에")
DECLINE = ("말하기 싫", "몰라", "나중에", "그건 왜", "묻지 마")
BYE = ("잘 자", "끊을게", "그만 얘기", "안녕히", "이만 할게", "다음에 또")

TOPIC_WORDS = {"MUSIC": ("트로트", "노래", "가수", "음악"),
               "FOOD": ("요리", "음식", "반찬", "김치", "떡"),
               "TRAVEL": ("여행", "제주", "바다", "산에", "다녀왔", "놀러")}
DAILY_WORDS = {"MEAL": ("먹었", "드셨", "밥", "아침", "점심", "저녁", "국수", "식사"),
               "MOOD": ("기분", "피곤", "우울", "행복", "심심", "외로", "즐거"),
               "ACTIVITY": ("산책", "운동", "시장", "복지관", "노인정", "교회", "텃밭"),
               "HEALTH": ("아프", "아파", "무릎", "허리", "두통", "감기", "약 먹", "병원")}
DAILY_QUESTION = {"MEAL": "참, 오늘 식사는 맛있게 하셨어요?", "MOOD": "참, 오늘 기분은 어떠세요?",
                  "ACTIVITY": "참, 오늘은 어디 다녀오신 데 있으세요?", "HEALTH": "참, 오늘 몸은 좀 괜찮으세요?"}


def _has(text, words):
    return any(w in text for w in words)


def _clauses(text):
    return [c.strip() for c in re.split(r"는데|지만|고 |,|\.|그리고", text) if len(c.strip()) >= 2]


def _last(history, speaker):
    return next((t["text"] for t in reversed(history) if t["speaker"] == speaker), "")


def _topic(text):
    return next((k for k, ws in TOPIC_WORDS.items() if _has(text, ws)), None)


def _out(say, **kw):
    base = {"say": say, "memory_candidates": [], "daily_info": [],
            "daily_check": {"asked": False, "declined": False},
            "play": {"action": "NONE"}, "end_conversation": False}
    base.update(kw)
    return base


def respond(history: list[dict], context: dict) -> dict:
    name = context["elder"]["name"]
    play = context.get("play")
    ev = context["event"]

    # ── 대화 시작: 기억이 있으면 꺼내서 인사 ─────────────────────
    if ev == "START":
        mem = next((m for m in context["memories"] if m["kind"] in ("EXPERIENCE", "INTEREST")), None)
        if mem:
            return _out(f"{name}님, 안녕하세요! 지난번에 '{mem['content']}' 말씀해 주셨죠. 오늘은 어떻게 지내셨어요?")
        return _out(f"{name}님, 안녕하세요! 오늘 하루는 어떠셨어요?")

    # ── 놀이가 방금 시작됨: 첫 질문 ─────────────────────────────
    if ev == "PLAY_STARTED" and play:
        if play["kind"] == "QUIZ":
            q = play["quiz"]["current_question"]
            return _out(f"좋아요, 퀴즈 시작할게요! 첫 번째 문제예요. {q['question']}")
        return _out(f"좋아요. '{play['memory']['content']}' 이야기를 해 볼까요? 그때 가장 기억에 남는 게 뭐예요?")

    said = _last(history, "ELDER")
    asked_before = _last(history, "AI")

    # ── 놀이 진행 중 ────────────────────────────────────────────
    if play:
        if play["kind"] == "QUIZ":
            quiz = play["quiz"]
            if _has(said, STOP) and not (quiz["last_result"] or {}).get("is_correct"):
                return _out("알겠어요, 퀴즈는 여기까지 할게요. 다른 이야기 나눠요.", play={"action": "STOP"})
            r = quiz["last_result"]
            feedback = "정답이에요!" if r and r["is_correct"] else f"아쉬워요, 정답은 {r['answer']}예요." if r else ""
            if quiz["finished"]:
                return _out(f"{feedback} 퀴즈 끝! {quiz['total']}문제 중에 {quiz['correct']}문제 맞히셨어요.",
                            play={"action": "END"})
            return _out(f"{feedback} 다음 문제예요. {quiz['current_question']['question']}")
        # 회상 놀이: 두 번 이야기 들으면 마무리
        if _has(said, STOP):
            return _out("알겠어요, 이 이야기는 여기까지 할게요.", play={"action": "STOP"})
        if play["elder_turns"] >= 2:
            return _out("좋은 이야기 들려주셔서 고마워요. 덕분에 저도 즐거웠어요.", play={"action": "END"})
        return _out("그러셨군요! 그때 누구랑 함께 하셨어요?")

    # ── 일반 대화 ───────────────────────────────────────────────
    if _has(said, BYE):
        return _out("오늘 이야기 나눠서 즐거웠어요. 편안한 하루 보내세요!", end_conversation=True)

    # 이번 말에서 기억·일상 후보 찾기 (근거 = 어르신이 한 말 그대로)
    mems, daily = [], []
    for c in _clauses(said):
        if _has(c, ("좋아해", "좋아하", "즐겨")):
            mems.append({"kind": "INTEREST", "content": c, "topic": _topic(c), "evidence": c})
        elif _has(c, ("다녀왔", "갔었", "살았", "젊을 때", "옛날에")):
            mems.append({"kind": "EXPERIENCE", "content": c, "topic": _topic(c), "evidence": c})
        for cat, ws in DAILY_WORDS.items():
            if cat in [x["code"] for x in context["daily"]["categories"]] and _has(c, ws):
                daily.append({"category": cat, "content": c, "evidence": c})
    found = {"memory_candidates": mems, "daily_info": daily}

    # 방금 놀이를 제안했었다면 → 수락/거절
    if "퀴즈" in asked_before and "해 보실래요" in asked_before:
        if _has(said, NO):
            return _out("알겠어요, 그냥 이야기 나눠요.", **found)
        if _has(said, YES):
            cat = next((m["topic"] for m in context["memories"] if m.get("topic")), None) or "MUSIC"
            return _out("좋아요!", play={"action": "START", "kind": "QUIZ", "quiz_category": cat}, **found)
    if "이야기 해 볼까요" in asked_before and _has(said, YES):
        mem = next((m for m in context["memories"] if m["kind"] == "EXPERIENCE"), None)
        if mem:
            return _out("좋아요!", play={"action": "START", "kind": "RECALL", "memory_id": mem["id"]}, **found)

    # 방금 일상 질문을 했는데 답하기 싫다고 하면 → 존중
    if "참, " in asked_before and _has(said, DECLINE):
        return _out("네, 괜찮아요. 편하게 다른 이야기 해요.", daily_check={"asked": False, "declined": True}, **found)

    # 오늘 아직 안 물었으면 → 모르는 항목 하나만 물어봄 (하루 최대 1번은 서버가 막아 줌)
    d = context["daily"]
    missing = [m for m in d["missing"] if m not in {x["category"] for x in daily}]
    if d["allowed_to_ask"] and missing:
        return _out(f"그러셨군요. {DAILY_QUESTION.get(missing[0], '참, 오늘은 어떠셨어요?')}",
                    daily_check={"asked": True, "declined": False}, **found)

    # 대화가 좀 이어졌고 오늘 놀이를 안 했으면 → 제안 (선택)
    elder_turns = sum(1 for t in history if t["speaker"] == "ELDER")
    if elder_turns >= 3 and sum(context["play_today"].values()) == 0:
        if any(m["kind"] == "EXPERIENCE" for m in [*context["memories"], *mems]):
            return _out("그러셨군요. 예전에 말씀하신 추억 이야기 해 볼까요?", **found)
        return _out("그러셨군요. 심심하실 때 간단한 퀴즈 한번 해 보실래요?", **found)

    return _out("그러셨군요. 더 이야기해 주세요.", **found)


def summarize_day(day: str, records: dict, context: dict) -> dict:
    """records: {"MEAL": ["점심에 국수를 드심", ...], ...} → 항목별 한 문장"""
    return {"extractor": "rule-v1",
            "summaries": {cat: " / ".join(items) for cat, items in records.items() if items}}
