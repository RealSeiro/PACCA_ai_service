"""서버 ↔ AI 약속 v2 (입력·출력 모양). AI 담당(곽민석)은 이 파일만 보면 된다.

AI 모듈은 함수 2개를 제공한다:
    respond(history: list[dict], context: dict) -> dict        # RespondOut 모양
    summarize_day(day: str, records: dict, context: dict) -> dict   # SummaryOut 모양

역할 나누기 (기획 v2 "LLM과 시스템 규칙의 역할 분리")
  - AI: 말 만들기, 기억 '후보' 찾기, 일상 정보 '후보' 찾기, 놀이를 제안·시작·끝낼지 판단, 요약 문장 쓰기
  - 서버: 후보를 검사해서 저장할지 결정, 일상 질문 하루 1번 제한, 퀴즈 문제 고르기와 정답 판정,
          놀이 기록, 공유 동의, 알림
  → 그래서 AI 출력에는 항상 근거(evidence: 어르신이 실제로 한 말)를 붙인다. 서버가 버리는 경우:
      · evidence가 이번 대화의 어르신 말에 그대로 없음
      · evidence가 너무 짧은 조각 (6글자 미만. 단, 어르신 말 전체가 그보다 짧으면 그 말 전체는 OK)
      · content가 evidence와 내용이 거의 안 겹침 (content의 두 글자 조각 중 25% 이상이 evidence에 있어야 함)
    후보는 하나씩 검사한다. 잘못된 후보 하나가 있어도 그것만 버리고 대답(say)은 그대로 쓴다.

──────────────── respond 입력 ────────────────
history[i] : {"seq": 1, "speaker": "AI" | "ELDER", "text": "..."}   (이번 대화 전체)
context    : {
  "event": "START" | "TURN" | "PLAY_STARTED",   # 왜 불렀는지 (대화 시작 / 어르신이 말함 / 방금 놀이가 시작됨)
  "today": "2026-11-03", "now": "14:05", "weekday": 2,
  "elder": {"id": 2, "name": "이영자"},
  "memories": [{"id": 7, "kind": "EXPERIENCE", "content": "...", "topic": "TRAVEL"}],   # 최근 30개
  "daily": {
    "allowed_to_ask": true,                    # false면 오늘은 일상 확인 질문 금지 (이미 물었음)
    "categories": [{"code": "MEAL", "label": "식사"}, ...],
    "known_today": {"MEAL": ["점심에 국수를 드심"]},   # 오늘 이미 들은 것 (다시 묻지 말 것)
    "missing": ["MOOD", "ACTIVITY", "HEALTH"]
  },
  "quiz_categories": [{"code": "MUSIC", "label": "음악·트로트"}, ...],
  "play_today": {"RECALL": 0, "QUIZ": 1},       # 오늘 참여 횟수 (너무 자주 제안하지 않게)
  "rule_reminder": "..."                         # (가끔) 규칙을 어겨서 다시 부를 때만 들어감. 꼭 따를 것
                                                 #   예: allowed_to_ask=false인데 일상 질문을 했을 때 → 다시 물으면 서버가 문장을 바꿔 버림
  "play": null | {                              # 진행 중인 놀이가 있을 때만
    "session_id": 3, "kind": "QUIZ" | "RECALL", "elder_turns": 2,   # 놀이 시작 뒤 어르신이 말한 횟수
    "quiz_category": "MUSIC",
    "memory": {"id": 7, "content": "...", "kind": "..."},          # RECALL일 때
    "quiz": {                                   # QUIZ일 때
      "last_result": null | {"question": "...", "user_answer": "...", "is_correct": true, "answer": "임영웅"},
      "current_question": null | {"id": 12, "question": "...", "hint": "..."},   # 이번에 낼 문제
      "answered": 1, "total": 3, "finished": false, "correct": 1
    }
  }
}
퀴즈일 때: 어르신 말은 서버가 먼저 정답 판정을 해서 last_result에 넣어 준다. AI는 그 결과로
반응하고 current_question을 자연스럽게 읽어 주면 된다. finished=true면 마무리 인사.
AI 호출이 실패하면 서버가 "맞았어요! 다음 문제예요. ..." 식으로 직접 진행한다.

──────────────── summarize_day ────────────────
항목 하나씩 부른다: records = {"MEAL": ["점심에 국수를 드심", ...]} (항목 1개).
다른 항목 내용이 섞이면 동의하지 않은 정보가 보호자에게 갈 수 있으므로 받은 항목만 요약할 것.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, Field

MemoryKind = Literal["INTEREST", "PREFERENCE", "EXPERIENCE", "PERSON", "OTHER"]
QuizCategory = Literal["MUSIC", "FOOD", "TRAVEL"]
Text200 = Annotated[str, Field(min_length=2, max_length=200)]


class MemoryCandidate(BaseModel):
    kind: MemoryKind
    content: Text200                  # 저장할 문장: "트로트, 특히 임영웅 노래를 좋아함"
    topic: QuizCategory | None = None
    evidence: Text200                 # 어르신이 실제로 한 말 (이번 대화에서 그대로 인용)


class DailyInfo(BaseModel):
    category: str = Field(description="context.daily.categories의 code")
    content: Text200                  # "점심에 국수를 드심"
    evidence: Text200


class DailyCheck(BaseModel):
    asked: bool = False               # 이번 응답(say)에 일상 확인 질문을 넣었나
    declined: bool = False            # 어르신이 그 질문에 답하기 싫다고 했나


class PlayAction(BaseModel):
    action: Literal["NONE", "START", "END", "STOP"] = "NONE"   # END = 자연스럽게 끝남, STOP = 어르신이 그만둠
    kind: Literal["RECALL", "QUIZ"] | None = None
    quiz_category: QuizCategory | None = None
    memory_id: int | None = None      # RECALL 시작 시 바탕이 될 기억


class RespondOut(BaseModel):
    say: Annotated[str, Field(min_length=1, max_length=500)]
    memory_candidates: list[MemoryCandidate] = []
    daily_info: list[DailyInfo] = []
    daily_check: DailyCheck = DailyCheck()
    play: PlayAction = PlayAction()
    end_conversation: bool = False


class SummaryOut(BaseModel):
    # {"MEAL": "점심에 국수를 드셨어요.", "MOOD": "..."} — 그날 기록이 있는 항목만
    summaries: dict[str, Annotated[str, Field(min_length=1, max_length=300)]]
    extractor: str = "ai"
