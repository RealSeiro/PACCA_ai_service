"""로그인(토큰)과 권한 검사 — 관문 1(연결)과 관문 2(동의)."""
import hashlib
import hmac
import secrets
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import JWT_SECRET
from .db import one, rows

bearer = HTTPBearer()


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 600_000).hex()}"


def check_password(pw: str, stored: str) -> bool:
    salt, h = stored.split("$")
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 600_000).hex(), h)


def make_token(user_id: int, role: str, days: int) -> str:
    return jwt.encode({"sub": str(user_id), "role": role, "exp": int(time.time()) + days * 86400},
                      JWT_SECRET, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    try:
        p = jwt.decode(cred.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "로그인이 필요합니다")
    return {"id": int(p["sub"]), "role": p["role"]}


def guardian_user(u: dict = Depends(current_user)) -> dict:
    if u["role"] != "GUARDIAN":
        raise HTTPException(403, "보호자만 쓸 수 있습니다")
    return u


def elder_user(u: dict = Depends(current_user)) -> dict:
    if u["role"] != "ELDER":
        raise HTTPException(403, "어르신 기기만 쓸 수 있습니다")
    return u


def require_link(conn, guardian_id: int, elder_id: int) -> int:
    """관문 1: 이 보호자가 이 어르신과 연결돼 있나 → link_id"""
    link = one(conn, """SELECT id FROM care_links
                        WHERE guardian_id = :g AND elder_id = :e AND status = 'ACTIVE'""", g=guardian_id, e=elder_id)
    if not link:
        raise HTTPException(403, "연결된 어르신이 아닙니다")
    return link["id"]


def granted_categories(conn, link_id: int) -> set[str]:
    """관문 2: 이 연결에서 어르신이 공유를 허락한 항목들 (행이 없으면 허락 안 함)"""
    return {r["category"] for r in rows(conn, "SELECT category FROM consents WHERE link_id = :l AND granted",
                                         l=link_id)}
