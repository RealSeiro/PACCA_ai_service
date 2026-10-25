"""계정·연결·동의 (SYS-02, FAM-02, FAM-06)
어르신: 앱에서 이름만 넣고 시작 → 초대 코드 만들기 → 공유 항목 동의
보호자: 이메일 가입·로그인 → 어르신이 알려준 초대 코드 입력 → 연결"""
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import check_password, current_user, elder_user, guardian_user, hash_password, make_token
from ..config import INVITE_CODE_MINUTES, KST
from ..db import get_db, one, rows, run
from ..schemas import Category, ConsentOut, InviteOut, LinkOut, Ok, TokenOut

router = APIRouter(tags=["계정·연결·동의"])


class ElderIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)


@router.post("/auth/elder", response_model=TokenOut)
def elder_start(body: ElderIn, db=Depends(get_db)):
    """어르신 앱 첫 실행: 이름만 받고 계정 생성. 토큰(1년)을 폰에 저장해 두고 계속 쓴다."""
    u = one(db, "INSERT INTO users (role, name) VALUES ('ELDER', :n) RETURNING id", n=body.name)
    return {"user_id": u["id"], "role": "ELDER", "token": make_token(u["id"], "ELDER", days=365)}


class SignupIn(BaseModel):
    name: str
    email: str
    password: str = Field(min_length=6)


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/signup", response_model=TokenOut)
def guardian_signup(body: SignupIn, db=Depends(get_db)):
    if one(db, "SELECT 1 AS x FROM users WHERE email = :e", e=body.email):
        raise HTTPException(409, "이미 가입된 이메일입니다")
    u = one(db, """INSERT INTO users (role, name, email, password_hash) VALUES ('GUARDIAN', :n, :e, :p)
                   RETURNING id""", n=body.name, e=body.email, p=hash_password(body.password))
    return {"user_id": u["id"], "role": "GUARDIAN", "token": make_token(u["id"], "GUARDIAN", days=30)}


@router.post("/auth/login", response_model=TokenOut)
def guardian_login(body: LoginIn, db=Depends(get_db)):
    u = one(db, "SELECT id, password_hash FROM users WHERE email = :e AND role = 'GUARDIAN'", e=body.email)
    if not u or not check_password(body.password, u["password_hash"]):
        raise HTTPException(401, "이메일 또는 비밀번호가 맞지 않습니다")
    return {"user_id": u["id"], "role": "GUARDIAN", "token": make_token(u["id"], "GUARDIAN", days=30)}


@router.post("/me/invite-codes", response_model=InviteOut)
def make_invite(e=Depends(elder_user), db=Depends(get_db)):
    """어르신 앱 '보호자 연결' 화면: 6자리 코드를 만들어 보호자에게 알려 준다."""
    while True:
        code = f"{secrets.randbelow(10**6):06d}"
        if not one(db, "SELECT 1 AS x FROM invite_codes WHERE code = :c", c=code):
            break
    exp = datetime.now(KST) + timedelta(minutes=INVITE_CODE_MINUTES)
    run(db, "INSERT INTO invite_codes (code, elder_id, expires_at) VALUES (:c, :e, :x)", c=code, e=e["id"], x=exp)
    return {"code": code, "expires_at": exp}


class JoinIn(BaseModel):
    code: str


# 코드 찍어 맞히기 방지: 보호자 한 명당 10분에 5번까지 틀릴 수 있음 (서버 한 대 기준, 재시작하면 초기화)
JOIN_FAIL_LIMIT, JOIN_FAIL_WINDOW = 5, 600
_join_fails: dict[int, deque] = defaultdict(deque)


@router.post("/links", response_model=LinkOut)
def join(body: JoinIn, g=Depends(guardian_user), db=Depends(get_db)):
    """보호자가 초대 코드 입력 → 연결. 확인과 사용 처리를 한 문장으로 해서 같은 코드가 두 번 쓰이지 않게."""
    fails, now = _join_fails[g["id"]], time.monotonic()
    while fails and now - fails[0] > JOIN_FAIL_WINDOW:
        fails.popleft()
    if len(fails) >= JOIN_FAIL_LIMIT:
        raise HTTPException(429, "코드를 여러 번 틀렸어요. 10분 뒤에 다시 시도해 주세요")
    c = one(db, """UPDATE invite_codes SET used_at = now(), used_by = :g
                   WHERE code = :c AND used_at IS NULL AND expires_at > now() RETURNING elder_id""",
            c=body.code, g=g["id"])
    if not c:
        fails.append(now)
        raise HTTPException(400, "코드가 틀렸거나 만료되었어요. 어르신 앱에서 새 코드를 받아 주세요")
    link = one(db, """INSERT INTO care_links (guardian_id, elder_id) VALUES (:g, :e)
                      ON CONFLICT (guardian_id, elder_id) DO UPDATE SET status = 'ACTIVE' RETURNING id""",
               g=g["id"], e=c["elder_id"])
    # 끊었다가 다시 연결한 경우 예전 동의가 되살아나지 않게: 다시 연결 = 처음부터 '공유 안 함'
    run(db, "DELETE FROM consents WHERE link_id = :l", l=link["id"])
    return _link(db, link["id"])


def _link(db, link_id):
    return one(db, """SELECT l.id AS link_id, e.id AS elder_id, e.name AS elder_name,
                             g.id AS guardian_id, g.name AS guardian_name
                      FROM care_links l JOIN users e ON e.id = l.elder_id JOIN users g ON g.id = l.guardian_id
                      WHERE l.id = :l""", l=link_id)


@router.get("/links", response_model=list[LinkOut])
def my_links(u=Depends(current_user), db=Depends(get_db)):
    col = "elder_id" if u["role"] == "ELDER" else "guardian_id"
    return rows(db, f"""SELECT l.id AS link_id, e.id AS elder_id, e.name AS elder_name,
                               g.id AS guardian_id, g.name AS guardian_name
                        FROM care_links l JOIN users e ON e.id = l.elder_id JOIN users g ON g.id = l.guardian_id
                        WHERE l.{col} = :u AND l.status = 'ACTIVE' ORDER BY l.id""", u=u["id"])


@router.delete("/links/{link_id}", response_model=Ok)
def unlink(link_id: int, u=Depends(current_user), db=Depends(get_db)):
    """어르신이든 보호자든 연결을 끊을 수 있다. 끊기면 보호자는 아무것도 못 본다."""
    r = run(db, """UPDATE care_links SET status = 'REVOKED' WHERE id = :l AND (elder_id = :u OR guardian_id = :u)""",
            l=link_id, u=u["id"])
    if r.rowcount == 0:
        raise HTTPException(404, "연결을 찾을 수 없습니다")
    run(db, "DELETE FROM consents WHERE link_id = :l", l=link_id)      # 동의도 함께 지움
    return {"ok": True}


@router.get("/categories", response_model=list[Category])
def categories(db=Depends(get_db)):
    return rows(db, "SELECT code, label FROM share_categories ORDER BY sort")


@router.get("/me/consents", response_model=list[ConsentOut])
def get_consents(e=Depends(elder_user), db=Depends(get_db)):
    """FAM-07 동의 화면용: 연결된 보호자 × 모든 공유 항목 (기본은 공유 안 함)"""
    return rows(db, """
        SELECT l.id AS link_id, g.name AS guardian_name, k.code AS category, k.label,
               COALESCE(c.granted, false) AS granted
        FROM care_links l JOIN users g ON g.id = l.guardian_id CROSS JOIN share_categories k
        LEFT JOIN consents c ON c.link_id = l.id AND c.category = k.code
        WHERE l.elder_id = :e AND l.status = 'ACTIVE' ORDER BY l.id, k.sort""", e=e["id"])


class ConsentIn(BaseModel):
    link_id: int
    category: str
    granted: bool


@router.put("/me/consents", response_model=Ok)
def set_consents(body: list[ConsentIn], e=Depends(elder_user), db=Depends(get_db)):
    """동의·철회. 철회하면 그 순간부터 보호자 조회에서 빠진다 (조회 때마다 서버가 확인하므로)."""
    for c in body:
        if not one(db, "SELECT 1 AS x FROM care_links WHERE id = :l AND elder_id = :e AND status = 'ACTIVE'",
                      l=c.link_id, e=e["id"]):
            raise HTTPException(404, f"연결을 찾을 수 없습니다: {c.link_id}")
        if not one(db, "SELECT 1 AS x FROM share_categories WHERE code = :c", c=c.category):
            raise HTTPException(400, f"없는 공유 항목입니다: {c.category}")
        run(db, """INSERT INTO consents (link_id, category, granted) VALUES (:l, :c, :g)
                   ON CONFLICT (link_id, category) DO UPDATE SET granted = :g, updated_at = now()""",
            l=c.link_id, c=c.category, g=c.granted)
    return {"ok": True}


class DeviceIn(BaseModel):
    fcm_token: str


@router.post("/devices", response_model=Ok)
def register_device(body: DeviceIn, u=Depends(current_user), db=Depends(get_db)):
    run(db, """INSERT INTO devices (user_id, fcm_token, last_seen_at) VALUES (:u, :t, now())
               ON CONFLICT (fcm_token) DO UPDATE SET user_id = :u, last_seen_at = now()""", u=u["id"], t=body.fcm_token)
    return {"ok": True}


@router.delete("/me", response_model=Ok)
def delete_me(u=Depends(current_user), db=Depends(get_db)):
    """탈퇴 = 이 사람의 데이터를 전부 즉시 지운다 (개인정보 보호법 제21조 파기).
    어르신: 대화·기억·일상·놀이·연결·동의·알림 기록까지. 보호자: 연결·동의·기기·계정."""
    uid = u["id"]
    run(db, "DELETE FROM consents WHERE link_id IN (SELECT id FROM care_links WHERE elder_id = :u OR guardian_id = :u)", u=uid)
    run(db, "DELETE FROM care_links WHERE elder_id = :u OR guardian_id = :u", u=uid)
    run(db, "UPDATE invite_codes SET used_by = NULL WHERE used_by = :u", u=uid)
    run(db, "DELETE FROM invite_codes WHERE elder_id = :u", u=uid)
    run(db, "DELETE FROM devices WHERE user_id = :u", u=uid)
    if u["role"] == "ELDER":
        for t in ("play_sessions", "daily_summaries", "daily_records", "daily_checks", "notification_log",
                  "memories", "conversations"):          # quiz_answers·turns는 CASCADE로 같이 지워짐
            run(db, f"DELETE FROM {t} WHERE elder_id = :u", u=uid)
    run(db, "DELETE FROM users WHERE id = :u", u=uid)
    return {"ok": True}
