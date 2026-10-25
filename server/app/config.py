"""설정값 한곳 모음. 실제 값은 .env 파일에서 읽는다 (.env는 GitHub에 올리지 않음)."""
import os
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://anbu:anbu@localhost:5432/anbu")
JWT_SECRET = os.environ.get("JWT_SECRET", "")
# 토큰 서명 열쇠. 저장소에 적힌 값이나 짧은 값이면 남이 토큰을 위조할 수 있으므로 서버를 켜지 않는다.
if len(JWT_SECRET.encode()) < 32 or JWT_SECRET.startswith(("dev-secret", "여기에")):
    raise RuntimeError("JWT_SECRET을 .env에 32자 이상 무작위 값으로 넣어 주세요. 만들기: "
                       'python -c "import secrets; print(secrets.token_urlsafe(48))"')
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "1") == "1"
FIREBASE_CREDENTIALS = os.environ.get("FIREBASE_CREDENTIALS")  # 서비스 계정 JSON 경로. 없으면 푸시는 콘솔 출력만

KST = ZoneInfo("Asia/Seoul")

# 기획 v2 규칙 (숫자는 팀 협의로 바꿀 수 있는 제안값)
DAILY_INVITE_TIME = time.fromisoformat(os.environ.get("DAILY_INVITE_TIME", "10:00"))  # 하루 1번 대화 알림 시각 (모든 사용자 공통)
QUIZ_QUESTIONS_PER_PLAY = 3          # 퀴즈 한 판에 3문제
QUIZ_ONLY_VERIFIED = os.environ.get("QUIZ_ONLY_VERIFIED", "0") == "1"   # 1이면 팀 검수(verified) 끝난 문제만 출제
MEMORIES_IN_CONTEXT = int(os.environ.get("MEMORIES_IN_CONTEXT", "30"))  # AI에게 넘기는 최근 기억 수. 0 = 기억 없이 대화 (기획 6장 Baseline 실험용)
IDLE_LIMIT = timedelta(minutes=30)   # 대화 중 30분 동안 말이 없으면 대화 종료 처리
TURN_RETENTION_DAYS = int(os.environ.get("TURN_RETENTION_DAYS", "30"))  # 대화 원문 보관 기간 (기획 5.6, 팀 확정 필요)
INVITE_CODE_MINUTES = 30             # 초대 코드 유효 시간
