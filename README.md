# PACCA AI Service

**Personalized AI Conversation and Cognitive Activity Service for Older Adults**
고령자를 위한 개인화 AI 대화·인지 놀이 서비스 (AI P-실무프로젝트)

어르신이 AI 친구와 음성으로 대화하면, AI가 대화에서 관심사와 경험을 기억하고 그 기억으로 회상 놀이와 관심사 퀴즈를 이어 갑니다. 어르신이 동의한 범위에서만 보호자에게 일상 요약과 놀이 참여 현황을 보여 줍니다.

## 폴더 구성

| 폴더 | 담당 | 내용 |
|---|---|---|
| `android/` | 강현준 | Android 앱 (어르신 모드·보호자 모드, STT·TTS, 서버 API 연동) |
| `server/` | 김도현 | FastAPI 서버 + PostgreSQL (API, 인증·권한, 시스템 규칙, 스케줄러) |
| `server/ai/` | 곽민석 | AI 모듈. 서버와 주고받는 입출력 형식은 `server/ai/contract.py`에 정해져 있음 |
| `docs/` | 박민경 | 계획서, 기능명세서, 보고서, 발표자료 |

각자 자기 폴더에서 작업하면 서로의 작업과 충돌하지 않습니다. 앱과 서버는 API로, 서버와 AI 모듈은 `contract.py`의 형식으로만 연결됩니다.

## 서버 실행

`server/README.md`를 참고하세요. (`cd server` 후 실행)

## 함께 작업하는 방법

1. `main`에서 새 브랜치를 만든다: `git checkout -b 기능이름` (예: `android-chat-screen`, `ai-respond`)
2. 작업을 커밋하고 브랜치를 올린다: `git push -u origin 기능이름`
3. GitHub에서 Pull Request를 열고, 필요하면 팀원에게 확인을 부탁한 뒤 Merge한다.

- 비밀번호, API 키, `.env`, Firebase 키 파일은 절대 올리지 않습니다. (`.gitignore`에 등록돼 있음)
- 다른 사람 폴더를 고쳐야 하면 그 사람에게 먼저 말하고 PR로 올립니다.
