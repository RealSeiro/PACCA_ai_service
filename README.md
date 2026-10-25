# AI 친구 서버 v2 (서버·DB 담당: 김도현)

기획안 v2(자유 대화 + 개인화 기억 + 인지 놀이 + 동의 기반 보호자 공유) 기준 서버입니다.
FastAPI + PostgreSQL. 앱(어르신 모드·보호자 모드)은 이 서버하고만 통신하고, AI 함수는 `ai/` 안에서 불립니다.

## 처음 실행 (Windows)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # 나온 값을 .env의 JWT_SECRET에 붙여 넣기 (안 하면 서버가 안 켜짐)
docker compose up -d                 # DB 켜기 (테이블 16개 + 퀴즈 30문제 자동 생성)
uvicorn app.main:app --reload        # http://localhost:8000/docs
```

- 한 바퀴 시연 겸 검증: `python scripts/demo.py` → 마지막에 "모든 확인 통과 (43개)"
- AI 모듈 약속 검사 (DB 불필요): `python scripts/check_ai.py`
- 테이블 구조를 바꿨으면 `docker compose down -v` 후 다시 `up -d` (데이터도 지워짐)

## 기능명세서 ↔ 코드

| ID | 기능 | 어디 |
|---|---|---|
| CON-05 | 자유 대화 API | `POST /conversations`, `/conversations/{id}/turns`, `/end` · `app/service.py` |
| CON-06 | 대화 기록 관리 | `turns` 테이블, `GET /me/conversations` · 보관기간 지나면 원문 삭제 (`TURN_RETENTION_DAYS`). 일상 기록 근거·퀴즈 답에 복사된 원문도 같이 비움. 기억의 근거 문장은 기억과 함께 남음(어르신이 지우면 같이 지워짐) |
| CON-09 | 하루 1번 대화 알림 | `app/scheduler.py` `send_daily_invites` · `notification_log` (같은 날 두 번 안 감, 재호출·보호자 경고 없음) |
| MEM-04 | 기억 데이터 관리 | `memories` · AI가 낸 후보 중 **근거(어르신이 실제 한 말)가 확인되고, 내용이 그 근거와 겹치는 것만** 저장 (`app/rules.py` `evidence_ok`) |
| MEM-06 | 기억 조회·삭제 API | `GET /me/memories`, `DELETE /me/memories/{id}` (본인만) |
| GAME-05 | 퀴즈 문제은행 | `quiz_questions` 30문제 (정답 + 인정 표현). 지금은 전부 `verified = false`(검수 전)라 다 출제됨. 팀 검수 후 `verified = true`로 바꾸고 `.env`에 `QUIZ_ONLY_VERIFIED=1`이면 검수된 문제만 나옴 |
| GAME-06 | 놀이 세션 관리 | `play_sessions` · `POST /conversations/{id}/play`, `/play/stop` · AI 제안 수락 시 자동 시작 |
| GAME-08 | 놀이 참여 기록 | `play_sessions`, `quiz_answers` · `GET /me/plays/stats` |
| GAME-09 | 퀴즈 정답 판정 | `app/rules.py` `judge_quiz` (서버가 문제은행 기준으로 판정 → 결과를 AI에게 알려 줌) |
| FAM-02 | 계정 연결 | 어르신 `POST /me/invite-codes` → 보호자 `POST /links {code}` |
| FAM-04 | 일상 요약 관리 | `daily_records` → 대화 끝날 때 `daily_summaries` (항목별) |
| FAM-06 | 공유 동의·권한 | `consents` · 모든 보호자 조회가 관문 1(연결)·관문 2(동의)를 지남 |
| FAM-08 | 일상 질문 하루 1번 (서버 쪽) | `daily_checks` · AI에게 `allowed_to_ask`로 알려 주고, 어기면 다시 요청·그래도 어기면 서버가 문장을 바꿈. 거절도 기록 |
| FAM-09 | 놀이 참여 현황 제공 | `GET /elders/{id}/days/{day}`의 `play` (PLAY 동의 시) |
| SYS-02 탈퇴 | 계정 삭제 | `DELETE /me` — 그 사람 데이터 전부 즉시 삭제 |
| SYS-02/04/06 | 인증·서버-AI 연동·DB | `app/auth.py`, `app/service.py`의 `call_ai`, `schema.sql` |

## 앱에서 접속
- 에뮬레이터 `http://10.0.2.2:8000`, 실제 폰은 `uvicorn ... --host 0.0.0.0` 후 `http://<PC IP>:8000`
- 모든 요청에 `Authorization: Bearer <토큰>` (어르신은 `POST /auth/elder`, 보호자는 `/auth/login`으로 받음)
- 푸시 `data.type`: `DAILY_INVITE` (어르신 폰, 누르면 대화 화면으로). `data.notification_id`(`invite-2026-10-23` 꼴)로 앱에서 중복 알림을 걸러낼 수 있음 (계획서 4.2 "중복 알림 수신")

## AI 연결 (곽민석 님)
`ai/contract.py`에 약속이 다 있습니다. `ai/llm.py`에 `respond`, `summarize_day`를 같은 모양으로 만들고
`python scripts/check_ai.py ai.llm` 통과 → `ai/__init__.py` import 한 줄 교체.
Baseline(기억 없이) 비교 실험은 `.env`에서 `MEMORIES_IN_CONTEXT=0`으로 두고 서버를 켜면 됩니다. 이때 AI에 넘어가는 `memories`가 빈 목록이 됩니다.

## 폴더
| 경로 | 내용 |
|---|---|
| `schema.sql` | 테이블 16개 + 퀴즈 30문제 |
| `app/service.py` | 대화 엔진 (말 저장 → 퀴즈 판정 → 맥락 → AI → 후보 검사 후 저장) |
| `app/rules.py` | 서버 규칙: 퀴즈 정답 판정, 근거 확인 |
| `app/scheduler.py` | 하루 1번 알림, 멈춘 대화 정리, 원문 보관기간 정리 |
| `app/auth.py` | 토큰, 관문 1·2 |
| `app/schemas.py` | API 응답 모양 (앱 담당이 보는 곳) |
| `app/routers/` | 계정·연결·동의 / 대화·놀이 / 기억·놀이 기록 / 보호자 화면 |
| `ai/` | 약속(`contract.py`)과 가짜 AI(`fake.py`, 규칙 기반) |
