"""대화 엔진: 어르신 말 한 마디가 들어왔을 때 서버가 하는 일 전부.
흐름: 말 저장 → (퀴즈면 정답 판정) → 맥락 모으기 → AI 호출 → AI '후보'를 규칙으로 검사해 저장 → AI 말 저장"""
from datetime import datetime

import ai
from ai.contract import DailyCheck, DailyInfo, MemoryCandidate, PlayAction, RespondOut, SummaryOut
from pydantic import ValidationError

from .config import IDLE_LIMIT, KST, MEMORIES_IN_CONTEXT, QUIZ_ONLY_VERIFIED, QUIZ_QUESTIONS_PER_PLAY
from .db import one, rows, run
from .rules import evidence_ok, judge_quiz

FALLBACK_SAY = "죄송해요, 제가 잘 못 들었어요. 한 번만 다시 말씀해 주시겠어요?"
NEUTRAL_SAY = "그러셨군요. 이야기 더 들려주세요."
QUIZ_LABELS = {"MUSIC": "음악·트로트", "FOOD": "음식·요리", "TRAVEL": "여행·지역"}


def now_kst() -> datetime:
    return datetime.now(KST)


# ─────────────────────────── 잠금 ───────────────────────────
def lock_elder(conn, elder_id: int):
    """이 어르신에 대한 요청을 한 줄로 세운다 (두 번 누름·재전송이 동시에 와도 순서대로 처리)"""
    one(conn, "SELECT id FROM users WHERE id = :e FOR UPDATE", e=elder_id)


# ─────────────────────────── 대화 기록 ───────────────────────────
def add_turn(conn, cid: int, speaker: str, text: str):
    run(conn, """INSERT INTO turns (conversation_id, seq, speaker, text)
                 VALUES (:c, COALESCE((SELECT MAX(seq) FROM turns WHERE conversation_id = :c), 0) + 1, :s, :t)""",
        c=cid, s=speaker, t=text)


def history(conn, cid: int) -> list[dict]:
    return rows(conn, "SELECT seq, speaker, text FROM turns WHERE conversation_id = :c ORDER BY seq", c=cid)


# ─────────────────────────── 놀이 ───────────────────────────
def active_play(conn, elder_id: int) -> dict | None:
    return one(conn, "SELECT * FROM play_sessions WHERE elder_id = :e AND status = 'ACTIVE'", e=elder_id)


def pick_question(conn, elder_id: int, category: str, exclude: list[int]) -> dict | None:
    """이 어르신이 아직 안 푼 문제를 먼저, 다 풀었으면 가장 오래전에 푼 문제부터 (GAME-05)"""
    return one(conn, """
        SELECT q.id, q.question, q.hint FROM quiz_questions q
        LEFT JOIN (SELECT a.question_id, MAX(a.created_at) AS last_at FROM quiz_answers a
                   JOIN play_sessions p ON p.id = a.play_session_id WHERE p.elder_id = :e
                   GROUP BY a.question_id) h ON h.question_id = q.id
        WHERE q.category = :c AND q.active AND (q.verified OR NOT :vo) AND NOT (q.id = ANY(CAST(:ex AS bigint[])))
        ORDER BY h.last_at NULLS FIRST, random() LIMIT 1""", e=elder_id, c=category, ex=exclude or [],
               vo=QUIZ_ONLY_VERIFIED)


def quiz_progress(conn, sid: int) -> dict:
    return one(conn, """SELECT COUNT(*) AS answered, COUNT(*) FILTER (WHERE is_correct) AS correct,
                               COALESCE(array_agg(question_id), '{}') AS ids
                        FROM quiz_answers WHERE play_session_id = :s""", s=sid)


def play_context(conn, p: dict, cid: int, quiz_override: dict | None = None) -> dict:
    elder_turns = one(conn, """SELECT COUNT(*) AS n FROM turns WHERE conversation_id = :c AND speaker = 'ELDER'
                               AND created_at >= :t""", c=cid, t=p["started_at"])["n"]
    ctx = {"session_id": p["id"], "kind": p["kind"], "elder_turns": elder_turns, "quiz_category": p["quiz_category"]}
    if p["kind"] == "RECALL":
        ctx["memory"] = one(conn, "SELECT id, kind, content FROM memories WHERE id = :m", m=p["memory_id"])
    else:
        if quiz_override:
            ctx["quiz"] = quiz_override
        else:
            prog = quiz_progress(conn, p["id"])
            q = one(conn, "SELECT id, question, hint FROM quiz_questions WHERE id = :q", q=p["current_question_id"])
            ctx["quiz"] = {"last_result": None, "current_question": q, "answered": prog["answered"],
                           "total": QUIZ_QUESTIONS_PER_PLAY, "finished": False, "correct": prog["correct"]}
    return ctx


def start_play(conn, elder_id: int, cid: int, kind: str, quiz_category: str | None, memory_id: int | None) -> dict:
    """놀이 시작 (AI 제안 수락 또는 놀이 선택 화면). 실패하면 이유와 함께 ValueError"""
    if active_play(conn, elder_id):
        raise ValueError("이미 진행 중인 놀이가 있어요")
    first_q = None
    if kind == "QUIZ":
        if quiz_category not in QUIZ_LABELS:
            raise ValueError(f"지원하지 않는 퀴즈 분야예요: {quiz_category}")
        first_q = pick_question(conn, elder_id, quiz_category, [])
        if not first_q:
            raise ValueError("이 분야에 문제가 없어요")
    else:
        if memory_id is None:
            m = one(conn, """SELECT id FROM memories WHERE elder_id = :e AND kind IN ('EXPERIENCE','PERSON')
                             ORDER BY created_at DESC LIMIT 1""", e=elder_id)
            memory_id = m and m["id"]
        if not memory_id or not one(conn, "SELECT 1 AS x FROM memories WHERE id = :m AND elder_id = :e",
                                    m=memory_id, e=elder_id):
            raise ValueError("회상 놀이에 쓸 기억이 아직 없어요")   # 없는 과거를 지어내지 않음
    # started_at = clock_timestamp(): 같은 요청 안에서 저장한 '수락' 말보다 뒤로 찍혀야 놀이 중 말 수를 바르게 센다
    return one(conn, """INSERT INTO play_sessions (elder_id, conversation_id, kind, quiz_category, memory_id,
                                                   current_question_id, started_at)
                        VALUES (:e, :c, :k, :qc, :m, :q, clock_timestamp()) RETURNING *""",
               e=elder_id, c=cid, k=kind, qc=quiz_category if kind == "QUIZ" else None,
               m=memory_id if kind == "RECALL" else None, q=first_q and first_q["id"])


def finish_play(conn, sid: int, status: str):
    run(conn, """UPDATE play_sessions SET status = :s, ended_at = now(), current_question_id = NULL
                 WHERE id = :i AND status = 'ACTIVE'""", s=status, i=sid)


# ─────────────────────────── 맥락 (AI에게 넘길 정보) ───────────────────────────
def build_context(conn, elder_id: int, cid: int, event: str, quiz_override: dict | None = None) -> dict:
    now = now_kst()
    today = now.date()
    elder = one(conn, "SELECT id, name FROM users WHERE id = :e", e=elder_id)
    mems = rows(conn, """SELECT id, kind, content, topic FROM memories WHERE elder_id = :e
                         ORDER BY created_at DESC LIMIT :n""", e=elder_id, n=MEMORIES_IN_CONTEXT)
    cats = rows(conn, "SELECT code, label FROM share_categories WHERE is_daily ORDER BY sort")
    known: dict[str, list[str]] = {}
    for r in rows(conn, "SELECT category, content FROM daily_records WHERE elder_id = :e AND day = :d ORDER BY id",
                  e=elder_id, d=today):
        known.setdefault(r["category"], []).append(r["content"])
    asked = one(conn, "SELECT 1 AS x FROM daily_checks WHERE elder_id = :e AND day = :d", e=elder_id, d=today)
    play_today = {"RECALL": 0, "QUIZ": 0}
    for r in rows(conn, """SELECT kind, COUNT(*) AS n FROM play_sessions WHERE elder_id = :e
                           AND (started_at AT TIME ZONE 'Asia/Seoul')::date = :d GROUP BY kind""", e=elder_id, d=today):
        play_today[r["kind"]] = r["n"]
    p = active_play(conn, elder_id)
    return {
        "event": event, "today": today.isoformat(), "now": now.strftime("%H:%M"), "weekday": today.isoweekday(),
        "elder": elder, "memories": mems,
        "daily": {"allowed_to_ask": asked is None, "categories": cats, "known_today": known,
                  "missing": [c["code"] for c in cats if c["code"] not in known]},
        "quiz_categories": [{"code": k, "label": v} for k, v in QUIZ_LABELS.items()],
        "play_today": play_today,
        "play": play_context(conn, p, cid, quiz_override) if p else None,
    }


def parse_respond(raw) -> RespondOut:
    """AI 출력 검사. say·놀이 신호가 망가졌으면 전체 실패(예외).
    후보(기억·일상)는 하나씩 따로 검사해서 잘못된 것만 버린다 — 후보 하나 때문에 대답 전체를 버리지 않게."""
    if not isinstance(raw, dict):
        raise ValueError(f"dict가 아님: {type(raw).__name__}")
    out = RespondOut.model_validate({k: v for k, v in raw.items() if k not in ("memory_candidates", "daily_info")})
    for key, model, dest in (("memory_candidates", MemoryCandidate, out.memory_candidates),
                             ("daily_info", DailyInfo, out.daily_info)):
        for item in raw.get(key) or []:
            try:
                dest.append(model.model_validate(item))
            except ValidationError as e:
                print(f"[ai] {key} 후보 하나 버림: {e.errors()[0]['msg']}")
    return out


def quiz_say(quiz_ctx: dict) -> str:
    """AI가 실패했을 때 퀴즈를 서버가 직접 진행하는 문장 (판정은 이미 서버가 했으므로 대화가 엇갈리지 않게)"""
    r = quiz_ctx["last_result"]
    head = "맞았어요!" if r["is_correct"] else f"아쉬워요, 정답은 {r['answer']}예요."
    if quiz_ctx["finished"]:
        return f"{head} 퀴즈는 여기까지예요. {quiz_ctx['total']}문제 중에 {quiz_ctx['correct']}개 맞히셨어요."
    return f"{head} 다음 문제예요. {quiz_ctx['current_question']['question']}"


def call_ai(conn, elder_id: int, cid: int, event: str, quiz_override: dict | None = None) -> tuple[RespondOut, dict]:
    """AI 호출 + 약속 검사. 실패해도 대화는 끊지 않는다.
    - 퀴즈 판정이 이미 끝난 턴이면 서버가 결과와 다음 문제를 직접 말한다 (되묻기 X: 이미 다음 문제로 넘어갔으므로)
    - 그 밖에는 되묻기"""
    ctx = build_context(conn, elder_id, cid, event, quiz_override)
    h = history(conn, cid)
    try:
        out = parse_respond(ai.respond(h, ctx))
        if out.daily_check.asked and not ctx["daily"]["allowed_to_ask"]:     # FAM-08 하루 1번: 서버가 막는다
            print(f"[rule] elder {elder_id}: 오늘 이미 일상 질문을 했는데 AI가 또 물음 → 다시 요청")
            ctx2 = {**ctx, "rule_reminder": "오늘은 이미 일상 확인 질문을 했습니다. 이번 대답에는 일상 질문을 넣지 마세요."}
            out2 = parse_respond(ai.respond(h, ctx2))
            if out2.daily_check.asked:
                out2.say = quiz_say(quiz_override) if quiz_override else NEUTRAL_SAY
                out2.daily_check = DailyCheck()
            out = out2
    except Exception as e:  # LLM 오류, 형식 위반
        print(f"[ai] respond 실패 → 대체 문장: {e!r}")
        out = RespondOut(say=quiz_say(quiz_override) if quiz_override else FALLBACK_SAY)
    return out, ctx


# ─────────────────────────── AI '후보' 검사 후 저장 ───────────────────────────
def apply_candidates(conn, elder_id: int, cid: int, out: RespondOut, ctx: dict) -> dict:
    elder_texts = [t["text"] for t in history(conn, cid) if t["speaker"] == "ELDER"]
    today = ctx["today"]
    saved = {"memories": 0, "daily": 0, "rejected": 0}

    for m in out.memory_candidates:                          # MEM-04: 실제로 한 말이 근거일 때만 저장
        if not evidence_ok(m.evidence, elder_texts, m.content):
            saved["rejected"] += 1
            continue
        r = run(conn, """INSERT INTO memories (elder_id, kind, content, topic, evidence, source_conversation_id)
                         VALUES (:e, :k, :c, :t, :ev, :cid) ON CONFLICT (elder_id, content) DO NOTHING""",
                e=elder_id, k=m.kind, c=m.content, t=m.topic, ev=m.evidence, cid=cid)
        saved["memories"] += r.rowcount

    daily_codes = {c["code"] for c in ctx["daily"]["categories"]}
    for d in out.daily_info:                                 # 일상 기록: 말한 것만, 같은 날 같은 내용은 한 번
        if d.category not in daily_codes or not evidence_ok(d.evidence, elder_texts, d.content):
            saved["rejected"] += 1
            continue
        r = run(conn, """INSERT INTO daily_records (elder_id, day, category, content, evidence, source_conversation_id)
                         SELECT :e, :d, :c, :t, :ev, :cid
                         WHERE NOT EXISTS (SELECT 1 FROM daily_records WHERE elder_id = :e AND day = :d
                                           AND category = :c AND content = :t)""",
                e=elder_id, d=today, c=d.category, t=d.content, ev=d.evidence, cid=cid)
        saved["daily"] += r.rowcount

    if out.daily_check.asked or out.daily_check.declined:   # FAM-08: 하루 최대 1번 (다시 묻는 건 call_ai에서 막음)
        run(conn, """INSERT INTO daily_checks (elder_id, day, conversation_id, declined) VALUES (:e, :d, :c, :dec)
                     ON CONFLICT (elder_id, day) DO UPDATE SET declined = daily_checks.declined OR :dec""",
            e=elder_id, d=today, c=cid, dec=out.daily_check.declined)
    return saved


# ─────────────────────────── 대화 한 턴 ───────────────────────────
def handle_turn(conn, elder_id: int, cid: int, text: str) -> dict:
    add_turn(conn, cid, "ELDER", text)                        # 말하자마자 저장

    # 퀴즈 중이면 서버가 먼저 정답 판정 (GAME-09) → 결과를 AI에게 알려 주고 반응하게 함
    p = active_play(conn, elder_id)
    pending = None
    if p and p["kind"] == "QUIZ" and p["current_question_id"]:
        q = one(conn, "SELECT * FROM quiz_questions WHERE id = :q", q=p["current_question_id"])
        prog = quiz_progress(conn, p["id"])
        others = [x for r in rows(conn, """SELECT answer, accepted FROM quiz_questions
                                           WHERE category = :c AND id <> :q""", c=q["category"], q=q["id"])
                  for x in [r["answer"], *r["accepted"]]]
        correct = judge_quiz(text, q["answer"], q["accepted"], others)
        answered = prog["answered"] + 1
        finished = answered >= QUIZ_QUESTIONS_PER_PLAY
        nxt = None if finished else pick_question(conn, elder_id, p["quiz_category"], [*prog["ids"], q["id"]])
        finished = finished or nxt is None
        pending = {"q": q, "correct": correct, "next": nxt, "finished": finished}
        quiz_ctx = {"last_result": {"question": q["question"], "user_answer": text, "is_correct": correct,
                                    "answer": q["answer"]},
                    "current_question": nxt, "answered": answered, "total": QUIZ_QUESTIONS_PER_PLAY,
                    "finished": finished, "correct": prog["correct"] + int(correct)}
        out, ctx = call_ai(conn, elder_id, cid, "TURN", quiz_ctx)
    else:
        out, ctx = call_ai(conn, elder_id, cid, "TURN")

    saved = apply_candidates(conn, elder_id, cid, out, ctx)
    say = out.say

    # 놀이 상태 반영
    if p:
        if pending:
            stopped = out.play.action == "STOP"
            if stopped and not pending["correct"]:
                finish_play(conn, p["id"], "STOPPED")       # "그만할래"는 오답으로 치지 않음
            else:
                run(conn, """INSERT INTO quiz_answers (play_session_id, question_id, user_answer, is_correct)
                             VALUES (:s, :q, :a, :c) ON CONFLICT DO NOTHING""",
                    s=p["id"], q=pending["q"]["id"], a=text, c=pending["correct"])
                if pending["finished"]:
                    finish_play(conn, p["id"], "COMPLETED")
                elif stopped:
                    finish_play(conn, p["id"], "STOPPED")
                else:
                    run(conn, "UPDATE play_sessions SET current_question_id = :q WHERE id = :s",
                        q=pending["next"]["id"], s=p["id"])
        elif out.play.action in ("END", "STOP"):
            finish_play(conn, p["id"], "COMPLETED" if out.play.action == "END" else "STOPPED")
    elif out.play.action == "START":                          # AI 제안을 어르신이 수락 → 서버가 놀이를 염
        try:
            start_play(conn, elder_id, cid, out.play.kind or "QUIZ", out.play.quiz_category, out.play.memory_id)
            out2, _ = call_ai(conn, elder_id, cid, "PLAY_STARTED")
            say = out2.say
        except ValueError as e:
            say = f"{out.say} 그런데 지금은 놀이를 시작하기 어려워요. 그냥 이야기 나눠요."
            print(f"[play] 시작 실패: {e}")

    add_turn(conn, cid, "AI", say)
    ended = False
    if out.end_conversation:
        end_conversation(conn, cid)
        ended = True
    return {"say": say, "ended": ended, "play": play_view(conn, elder_id), "saved": saved}


def play_view(conn, elder_id: int) -> dict | None:
    """앱 화면에 띄울 놀이 상태 (GAME-07)"""
    p = active_play(conn, elder_id)
    if not p:
        return None
    v = {"session_id": p["id"], "kind": p["kind"], "quiz_category": p["quiz_category"]}
    if p["kind"] == "QUIZ":
        prog = quiz_progress(conn, p["id"])
        q = one(conn, "SELECT question FROM quiz_questions WHERE id = :q", q=p["current_question_id"])
        v.update(question=q and q["question"], answered=prog["answered"], correct=prog["correct"],
                 total=QUIZ_QUESTIONS_PER_PLAY)
    return v


# ─────────────────────────── 대화 시작·종료 ───────────────────────────
def start_conversation(conn, elder_id: int) -> dict:
    lock_elder(conn, elder_id)                                 # 같은 어르신의 '대화 시작' 두 번이 겹치지 않게
    old = one(conn, "SELECT id FROM conversations WHERE elder_id = :e AND status = 'ACTIVE'", e=elder_id)
    if old:                                                    # 끝내지 않은 대화가 있으면 정리하고 새로 시작
        end_conversation(conn, old["id"])
    c = one(conn, "INSERT INTO conversations (elder_id) VALUES (:e) RETURNING id", e=elder_id)
    out, _ = call_ai(conn, elder_id, c["id"], "START")
    add_turn(conn, c["id"], "AI", out.say)
    return {"conversation_id": c["id"], "say": out.say}


def end_conversation(conn, cid: int):
    c = one(conn, """UPDATE conversations SET status = 'ENDED', ended_at = now()
                     WHERE id = :c AND status = 'ACTIVE' RETURNING elder_id, started_at""", c=cid)
    if not c:
        return
    p = one(conn, "SELECT id FROM play_sessions WHERE conversation_id = :c AND status = 'ACTIVE'", c=cid)
    if p:
        finish_play(conn, p["id"], "STOPPED")
    # 자정을 넘긴 대화면 기록이 이틀에 걸쳐 있으므로, 이 대화에서 나온 기록의 날짜마다 요약
    days = {r["day"] for r in rows(conn, "SELECT DISTINCT day FROM daily_records WHERE source_conversation_id = :c",
                                   c=cid)}
    days.add(c["started_at"].astimezone(KST).date())
    for d in sorted(days):
        summarize_day(conn, c["elder_id"], d)


def summarize_day(conn, elder_id: int, day):
    """그날 일상 기록 → 항목별 요약 (FAM-04). 기록이 없는 항목은 요약하지 않음 (추측 금지)"""
    recs: dict[str, list[str]] = {}
    for r in rows(conn, "SELECT category, content FROM daily_records WHERE elder_id = :e AND day = :d ORDER BY id",
                  e=elder_id, d=day):
        recs.setdefault(r["category"], []).append(r["content"])
    if not recs:
        return
    # 항목마다 따로 요약: 한 항목 요약에 다른 항목(동의 안 한 것일 수 있음) 내용이 섞이지 않게
    summaries = {}
    for cat, texts in recs.items():
        try:
            out = SummaryOut.model_validate(ai.summarize_day(day.isoformat(), {cat: texts}, {"elder_id": elder_id}))
            summaries[cat] = out.summaries.get(cat) or " / ".join(texts)    # 빠뜨렸으면 기록 그대로
        except Exception as e:
            print(f"[ai] summarize_day({cat}) 실패 → 기록을 그대로 이어 붙임: {e!r}")
            summaries[cat] = " / ".join(texts)
    for cat, text in summaries.items():
        run(conn, """INSERT INTO daily_summaries (elder_id, day, category, summary) VALUES (:e, :d, :c, :s)
                     ON CONFLICT (elder_id, day, category) DO UPDATE SET summary = :s, updated_at = now()""",
            e=elder_id, d=day, c=cat, s=text)


def end_idle_conversations(conn, now: datetime) -> int:
    # SKIP LOCKED: 지금 말 한 마디를 처리 중인 대화(잠겨 있음)는 건드리지 않는다
    ids = rows(conn, """SELECT c.id FROM conversations c WHERE c.status = 'ACTIVE'
                        AND COALESCE((SELECT MAX(created_at) FROM turns t WHERE t.conversation_id = c.id), c.started_at)
                            < :lim
                        FOR UPDATE SKIP LOCKED""", lim=now - IDLE_LIMIT)
    for r in ids:
        end_conversation(conn, r["id"])
    return len(ids)
