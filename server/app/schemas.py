"""API 응답 모양. /docs 에 그대로 표시되고, 서버가 다른 모양을 보내려 하면 서버에서 먼저 오류가 난다.
앱 담당은 이 파일(또는 /docs)만 보면 된다."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class Ok(BaseModel):
    ok: bool = True


class TokenOut(BaseModel):
    user_id: int
    role: Literal["ELDER", "GUARDIAN"]
    token: str


class InviteOut(BaseModel):
    code: str
    expires_at: datetime


class LinkOut(BaseModel):
    link_id: int
    elder_id: int
    elder_name: str
    guardian_id: int
    guardian_name: str


class Category(BaseModel):
    code: str
    label: str


class ConsentOut(BaseModel):
    link_id: int
    guardian_name: str
    category: str
    label: str
    granted: bool


# ── 대화 ──
class PlayView(BaseModel):
    session_id: int
    kind: Literal["RECALL", "QUIZ"]
    quiz_category: str | None = None
    question: str | None = None       # 퀴즈: 지금 화면에 띄울 문제
    answered: int | None = None
    correct: int | None = None
    total: int | None = None


class Saved(BaseModel):
    memories: int
    daily: int
    rejected: int                     # 근거가 확인되지 않아 버린 후보 수


class StartOut(BaseModel):
    conversation_id: int
    say: str                          # 앱은 이 문장을 TTS로 읽는다


class TurnOut(BaseModel):
    say: str
    ended: bool                       # true면 AI가 대화를 마무리함 → 앱은 대화 화면 닫기
    play: PlayView | None
    saved: Saved


class SayOut(BaseModel):
    say: str
    play: PlayView | None


class ConversationOut(BaseModel):
    id: int
    started_at: datetime
    ended_at: datetime | None
    status: Literal["ACTIVE", "ENDED"]


class TurnRow(BaseModel):
    seq: int
    speaker: Literal["AI", "ELDER"]
    text: str


# ── 기억 ──
class MemoryOut(BaseModel):
    id: int
    kind: str
    content: str
    topic: str | None
    created_at: datetime


# ── 놀이 ──
class PlayStat(BaseModel):
    kind: Literal["RECALL", "QUIZ"]
    sessions: int                     # 참여 횟수
    completed: int                    # 끝까지 한 횟수
    quiz_answered: int
    quiz_correct: int


class PlayStatsOut(BaseModel):
    days: int
    stats: list[PlayStat]


# ── 보호자 ──
class DayItem(BaseModel):
    category: str
    label: str
    summary: str | None               # null = 그날 이야기에 나오지 않음 (확인 안 됨, 나쁜 상태 아님)


class DayOut(BaseModel):
    day: date
    items: list[DayItem]              # 동의된 항목만
    play: list[PlayStat] | None       # PLAY 공유 동의가 없으면 null
    hidden_categories: list[str]      # 어르신이 공유하지 않은 항목 (앱에서 "공유 안 됨" 표시용)


class DayBrief(BaseModel):
    day: date
    has_summary: bool
    play_sessions: int | None
