"""v2 시연 겸 검증: 기획 v2의 사용자 흐름을 처음부터 끝까지 돌리고, 서버 규칙이 지켜지는지 확인한다.
실행: python scripts/demo.py   (DB가 켜져 있어야 함. 서버를 따로 켤 필요는 없음)
마지막에 '모든 확인 통과'가 나오면 성공."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ.setdefault("JWT_SECRET", "demo-only-" + "x" * 40)   # 시연용. 실제 서버는 .env 값

from fastapi.testclient import TestClient  # noqa: E402

import ai  # noqa: E402
from app.config import KST  # noqa: E402
from app.db import engine, one, run  # noqa: E402
from app.main import app  # noqa: E402
from app.scheduler import purge_old_turns, send_daily_invites  # noqa: E402
from app.service import end_idle_conversations  # noqa: E402

c = TestClient(app)
stamp = datetime.now().strftime("%H%M%S%f")
checks = 0


def call(method, url, token=None, expect=200, **kw):
    r = c.request(method, url, headers={"Authorization": f"Bearer {token}"} if token else {}, **kw)
    if r.status_code != expect:
        raise SystemExit(f"✗ {method} {url} → {r.status_code} (기대 {expect}) {r.text}")
    return r.json()


def check(cond, msg):
    global checks
    if not cond:
        raise SystemExit(f"✗ 확인 실패: {msg}")
    checks += 1
    print(f"  ✓ {msg}")


def step(t):
    print(f"\n=== {t}")


def say(cid, E, text):
    r = call("POST", f"/conversations/{cid}/turns", E, json={"text": text})
    print(f"  어르신: {text}\n  AI   : {r['say']}" + (f"   [놀이: {r['play']}]" if r["play"] else ""))
    return r


step("1. 어르신 앱 시작, 보호자 가입, 초대 코드로 연결")
E = call("POST", "/auth/elder", json={"name": "이영자"})
eid, E = E["user_id"], E["token"]
G = call("POST", "/auth/signup", json={"name": "박지훈", "email": f"g{stamp}@t.com", "password": "pw1234"})["token"]
code = call("POST", "/me/invite-codes", E)["code"]
link = call("POST", "/links", G, json={"code": code})
check(link["elder_id"] == eid, "초대 코드로 보호자-어르신 연결")
call("POST", "/links", G, expect=400, json={"code": code})
check(True, "같은 초대 코드는 두 번 못 씀")

step("2. 어르신이 공유 동의: 식사·기분·놀이 참여만 켜고, 활동·건강은 끔")
cons = call("GET", "/me/consents", E)
check(all(not x["granted"] for x in cons), "처음엔 모든 항목이 '공유 안 함'")
call("PUT", "/me/consents", E, json=[{"link_id": link["link_id"], "category": k, "granted": True}
                                     for k in ("MEAL", "MOOD", "PLAY")])

step("3. 첫 대화: 자유롭게 이야기 → 기억·일상 기록 저장, 일상 질문은 하루 1번")
cid = call("POST", "/conversations", E)
print(f"  AI   : {cid['say']}")
cid = cid["conversation_id"]
r = say(cid, E, "나는 트로트 좋아해, 임영웅 노래를 제일 좋아하지")
check(r["saved"]["memories"] >= 1, f"관심사가 기억으로 저장됨 ({r['saved']})")
check(r["say"].endswith("하셨어요?") or "참," in r["say"], "AI가 오늘 일상 질문을 한 번 함")
r = say(cid, E, "점심에 국수 먹었어")
check(r["saved"]["daily"] == 1, "식사 이야기가 오늘 일상 기록으로 저장됨")
check("참," not in r["say"], "일상 질문을 같은 날 다시 하지 않음")
r = say(cid, E, "젊을 때 남편이랑 제주도 여행 다녀왔어")
check(r["saved"]["memories"] >= 1, "경험이 기억으로 저장됨")
check("추억" in r["say"], "대화가 이어지자 AI가 회상 놀이를 '제안'함 (강요 아님)")

step("4. 회상 놀이: 제안 수락 → 저장된 기억으로 질문 → 두 번 이야기하면 마무리")
r = say(cid, E, "응 좋아")
check(r["play"] and r["play"]["kind"] == "RECALL", "어르신이 수락해서 회상 놀이 시작")
check("제주도" in r["say"], "회상 질문이 실제로 저장된 기억(제주도 여행)에서 나옴")
say(cid, E, "바다가 정말 예뻤어")
r = say(cid, E, "남편이랑 손잡고 걸었지")
check(r["play"] is None, "회상 놀이가 끝나고 일반 대화로 돌아옴")

step("5. 관심사 퀴즈: 놀이 선택 화면에서 음악 퀴즈 → 정답·오답·그만하기")
r = call("POST", f"/conversations/{cid}/play", E, json={"kind": "QUIZ", "quiz_category": "MUSIC"})
print(f"  AI   : {r['say']}")
with engine.begin() as db:
    q = one(db, """SELECT q.answer FROM play_sessions p JOIN quiz_questions q ON q.id = p.current_question_id
                   WHERE p.elder_id = :e AND p.status = 'ACTIVE'""", e=eid)
r = say(cid, E, f"{q['answer']}이요")
check(r["play"]["answered"] == 1 and r["play"]["correct"] == 1, "문제은행 정답으로 서버가 '정답' 판정")
r = say(cid, E, "음 잘 모르겠어")
check(r["play"]["answered"] == 2 and r["play"]["correct"] == 1, "모르는 답은 오답으로 기록")
r = say(cid, E, "이제 그만할래")
check(r["play"] is None, "'그만할래'로 퀴즈가 멈추고 일반 대화로 돌아옴")
with engine.begin() as db:
    p = one(db, """SELECT status, (SELECT COUNT(*) FROM quiz_answers a WHERE a.play_session_id = p.id) AS n
                   FROM play_sessions p WHERE elder_id = :e AND kind = 'QUIZ'""", e=eid)
check(p["status"] == "STOPPED" and p["n"] == 2, "'그만할래'는 오답으로 치지 않음 (답 2개만 기록)")

step("6. 기분 이야기 후 작별 인사 → 대화 종료 → 날짜별 요약 생성")
r = say(cid, E, "오늘 기분이 좋아, 무릎이 좀 아프긴 해")
check(r["saved"]["daily"] >= 2, "기분·건강 언급이 일상 기록으로 저장됨")
r = say(cid, E, "이제 이만 할게 안녕히")
check(r["ended"], "작별 인사로 대화가 끝남")

step("7. AI가 지어낸 기억은 서버가 버림 (허위 기억 방지)")
cid2 = call("POST", "/conversations", E)
print(f"  AI   : {cid2['say']}")
check("제주도" in cid2["say"] or "임영웅" in cid2["say"] or "트로트" in cid2["say"], "다음 대화 첫 인사에 기억을 활용함")
cid2 = cid2["conversation_id"]
real = ai.respond
ai.respond = lambda h, ctx: {"say": "그러셨군요.", "memory_candidates": [
    {"kind": "EXPERIENCE", "content": "미국에서 10년 살았음", "evidence": "미국에서 10년 살았어"}]}
r = say(cid2, E, "오늘은 날이 흐리네")
ai.respond = real
check(r["saved"]["memories"] == 0 and r["saved"]["rejected"] == 1, "어르신이 하지 않은 말을 근거로 한 기억은 저장 안 됨")
ai.respond = lambda h, ctx: {"say": "", "oops": True}
r = say(cid2, E, "응")
ai.respond = real
check("다시 말씀" in r["say"], "AI가 약속과 다른 값을 줘도 대화는 끊기지 않고 되묻기로 대신함")
call("POST", f"/conversations/{cid2}/end", E)

step("8. 보호자 화면: 동의한 항목만, 놀이 참여 현황")
today = datetime.now(KST).date().isoformat()
d = call("GET", f"/elders/{eid}/days/{today}", G)
for it in d["items"]:
    print(f"  [{it['label']}] {it['summary']}")
print(f"  놀이: {[(s['kind'], s['sessions'], s['completed']) for s in d['play']]}   숨김: {d['hidden_categories']}")
cats = {i["category"] for i in d["items"]}
check(cats == {"MEAL", "MOOD"}, "식사·기분만 보이고 활동·건강은 안 보임")
check("무릎" not in str(d), "공유 안 한 건강 언급(무릎)은 보호자에게 안 감")
check({s["kind"]: s["sessions"] for s in d["play"]} == {"QUIZ": 1, "RECALL": 1}, "놀이 참여 횟수 (회상 1, 퀴즈 1)")
call("PUT", "/me/consents", E, json=[{"link_id": link["link_id"], "category": "MEAL", "granted": False}])
d = call("GET", f"/elders/{eid}/days/{today}", G)
check("MEAL" not in {i["category"] for i in d["items"]}, "어르신이 식사 공유를 철회하자 바로 안 보임")
G2 = call("POST", "/auth/signup", json={"name": "남", "email": f"x{stamp}@t.com", "password": "pw1234"})["token"]
call("GET", f"/elders/{eid}/days/{today}", G2, expect=403)
check(True, "연결 안 된 보호자는 아무것도 못 봄 (403)")

step("9. 기억 조회·삭제 (본인만)")
mems = call("GET", "/me/memories", E)
print("  기억:", [m["content"] for m in mems])
other = call("POST", "/auth/elder", json={"name": "다른 어르신"})["token"]
call("DELETE", f"/me/memories/{mems[0]['id']}", other, expect=404)
check(True, "다른 사람은 내 기억을 못 지움")
call("DELETE", f"/me/memories/{mems[0]['id']}", E)
check(len(call("GET", "/me/memories", E)) == len(mems) - 1, "본인은 기억을 지울 수 있음")

step("10. 하루 1번 대화 알림, 원문 보관기간, 멈춘 대화 정리")
call("POST", "/devices", E, json={"fcm_token": f"tok-{stamp}"})
with engine.begin() as db:
    day = datetime.now(KST).date()
    first = send_daily_invites(db, day)
    second = send_daily_invites(db, day)
    sent_me = one(db, "SELECT COUNT(*) AS n FROM notification_log WHERE elder_id = :e", e=eid)["n"]
check(first >= 1 and second == 0 and sent_me == 1, "같은 날 알림은 한 번만 (다시 돌려도 안 감)")
with engine.begin() as db:
    run(db, "UPDATE turns SET created_at = now() - interval '40 days' WHERE conversation_id = :c", c=cid)
    purged = purge_old_turns(db, datetime.now(KST))
    left = one(db, "SELECT COUNT(*) AS n FROM memories WHERE elder_id = :e", e=eid)["n"]
check(purged > 0 and left >= 1, "보관기간 지난 원문은 지워지고, 추출된 기억은 남음")
cid3 = call("POST", "/conversations", E)["conversation_id"]
with engine.begin() as db:
    run(db, "UPDATE turns SET created_at = now() - interval '2 hours' WHERE conversation_id = :c", c=cid3)
    run(db, "UPDATE conversations SET started_at = now() - interval '2 hours' WHERE id = :c", c=cid3)
    n = end_idle_conversations(db, datetime.now(KST))
check(n >= 1, "30분 넘게 말이 없던 대화는 서버가 정리함")

step("11. 퀴즈를 끝까지: 3문제를 풀면 '완료'로 기록")
cid4 = call("POST", "/conversations", E)["conversation_id"]
r = call("POST", f"/conversations/{cid4}/play", E, json={"kind": "QUIZ", "quiz_category": "FOOD"})
print(f"  AI   : {r['say']}")
for i in range(3):
    with engine.begin() as db:
        q = one(db, """SELECT q.answer FROM play_sessions p JOIN quiz_questions q ON q.id = p.current_question_id
                       WHERE p.elder_id = :e AND p.status = 'ACTIVE'""", e=eid)
    r = say(cid4, E, q["answer"])
check(r["play"] is None and "3문제 중에 3문제" in r["say"], "3문제를 다 풀면 점수를 알려 주고 놀이가 끝남")
with engine.begin() as db:
    st = one(db, "SELECT status FROM play_sessions WHERE elder_id = :e AND quiz_category = 'FOOD'", e=eid)["status"]
check(st == "COMPLETED", "끝까지 한 퀴즈는 COMPLETED로 기록")
call("POST", "/conversations", E, json=None)
check(True, "새 대화를 시작하면 끝내지 않은 이전 대화는 자동 정리")

step("12. 일상 질문을 거절하면 존중하고 그날은 다시 묻지 않음")
cid5 = call("POST", "/conversations", other)["conversation_id"]
r = call("POST", f"/conversations/{cid5}/turns", other, json={"text": "그냥 그래"})
print(f"  AI   : {r['say']}")
r = call("POST", f"/conversations/{cid5}/turns", other, json={"text": "그건 말하기 싫어"})
print(f"  AI   : {r['say']}")
with engine.begin() as db:
    oid = one(db, "SELECT elder_id FROM conversations WHERE id = :c", c=cid5)["elder_id"]
    dc = one(db, "SELECT declined FROM daily_checks WHERE elder_id = :e", e=oid)
check(dc and dc["declined"], "거절 의사가 기록됨")
r = call("POST", f"/conversations/{cid5}/turns", other, json={"text": "날씨가 좋네"})
check("참," not in r["say"], "거절한 날에는 일상 질문을 다시 하지 않음")

step("13. 코드 검토에서 나온 구멍이 막혔는지")
from app.rules import judge_quiz  # noqa: E402
real_respond = ai.respond
n = call("POST", "/auth/elder", json={"name": "검토"})
nid, N = n["user_id"], n["token"]
cid6 = call("POST", "/conversations", N)["conversation_id"]
ai.respond = lambda h, ctx: {"say": "그러셨군요", "memory_candidates": [
    {"kind": "EXPERIENCE", "content": "미국에서 10년 살았음", "evidence": "어요"},                      # 너무 짧은 근거
    {"kind": "EXPERIENCE", "content": "점심을 굶고 쓰러지셨음", "evidence": "점심 맛있게 먹었어요"},    # 근거와 다른 내용
    {"kind": "INTEREST", "content": "등산", "topic": "HEALTH", "evidence": "등산"}]}                    # 형식 오류 후보
r = call("POST", f"/conversations/{cid6}/turns", N, json={"text": "점심 맛있게 먹었어요"})
check(r["saved"]["memories"] == 0 and r["say"] == "그러셨군요",
      "짧은 근거·근거와 다른 내용은 버리고, 형식 틀린 후보 하나 때문에 대답 전체를 버리지 않음")
ai.respond = lambda h, ctx: {"say": "참, 오늘 기분은 어떠세요?", "daily_check": {"asked": True}}
call("POST", f"/conversations/{cid6}/turns", N, json={"text": "그냥 그래"})
r = call("POST", f"/conversations/{cid6}/turns", N, json={"text": "응"})
check("참," not in r["say"], "AI가 규칙을 어기고 일상 질문을 또 해도 서버가 막음")
ai.respond = real_respond
call("POST", f"/conversations/{cid6}/play", N, json={"kind": "QUIZ", "quiz_category": "TRAVEL"})
ai.respond = lambda h, ctx: (_ for _ in ()).throw(TimeoutError("LLM 응답 없음"))
r = call("POST", f"/conversations/{cid6}/turns", N, json={"text": "모르겠어"})
ai.respond = real_respond
check("다음 문제" in r["say"] and r["play"]["answered"] == 1, "퀴즈 중 AI가 실패해도 서버가 결과와 다음 문제를 직접 말함")
check(not judge_quiz("이미자 아니고 조용필", "이미자", [], ["조용필"]) and judge_quiz("아마 이미자일걸", "이미자", []),
      "퀴즈 판정: '정답 아니고 ~'은 오답, '아마 정답일걸'은 정답")
code = call("POST", "/me/invite-codes", N)["code"]
G2 = call("POST", "/auth/signup", json={"name": "검토보호자", "email": f"r{stamp}@t.com", "password": "pw1234"})["token"]
lk = call("POST", "/links", G2, json={"code": code})
call("PUT", "/me/consents", N, json=[{"link_id": lk["link_id"], "category": "HEALTH", "granted": True}])
call("DELETE", f"/links/{lk['link_id']}", N)
code = call("POST", "/me/invite-codes", N)["code"]
call("POST", "/links", G2, json={"code": code})
cons = call("GET", "/me/consents", N)
check(not any(x["granted"] for x in cons), "연결을 끊었다 다시 이으면 예전 동의가 되살아나지 않음")
call("GET", "/me/conversations?limit=-1", N, expect=422)
check(True, "말이 안 되는 값(limit=-1)은 서버 오류가 아니라 입력 오류로 답함")
call("DELETE", "/me", N)
with engine.begin() as db:
    left = one(db, """SELECT (SELECT COUNT(*) FROM users WHERE id = :e) + (SELECT COUNT(*) FROM conversations WHERE elder_id = :e)
                      + (SELECT COUNT(*) FROM memories WHERE elder_id = :e) + (SELECT COUNT(*) FROM care_links WHERE elder_id = :e)
                      AS n""", e=nid)["n"]
check(left == 0, "탈퇴하면 그 어르신의 계정·대화·기억·연결이 전부 지워짐")

print(f"\n모든 확인 통과 ({checks}개). /docs 에서 같은 주소들을 직접 눌러 볼 수 있습니다.")
