"""정해진 시각에 도는 일: 하루 1번 대화 알림, 오래 멈춘 대화 정리, 대화 원문 보관기간 정리."""
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from .config import DAILY_INVITE_TIME, KST, TURN_RETENTION_DAYS
from .db import engine, one, rows, run
from .push import send_to_user
from .service import end_idle_conversations

INVITE_BODY = "오늘 이야기 나눠요! 눌러서 대화를 시작해 보세요."


def send_daily_invites(conn, day: date) -> int:
    """CON-09: 어르신마다 하루 1번. 같은 날 다시 돌아도 PK(elder_id, day)가 막아서 두 번 가지 않는다.
    다시 부르지 않고, 안 받아도 보호자에게 아무것도 보내지 않는다."""
    sent = 0
    for e in rows(conn, """SELECT DISTINCT u.id FROM users u JOIN devices d ON d.user_id = u.id
                           WHERE u.role = 'ELDER'"""):
        log = one(conn, """INSERT INTO notification_log (elder_id, day) VALUES (:e, :d)
                           ON CONFLICT DO NOTHING RETURNING elder_id""", e=e["id"], d=day)
        if not log:
            continue                                            # 오늘 이미 보냄
        try:                                                    # 한 명 실패가 나머지를 막지 않게
            ok = send_to_user(conn, e["id"], {"type": "DAILY_INVITE", "screen": "conversation",
                                              "notification_id": f"invite-{day.isoformat()}"},
                              title="AI 친구", body=INVITE_BODY)
        except Exception as err:
            print(f"[push] elder {e['id']} 발송 실패: {err!r}")
            ok = False
        run(conn, "UPDATE notification_log SET delivered = :ok WHERE elder_id = :e AND day = :d",
            ok=ok, e=e["id"], d=day)
        sent += 1
    return sent


def purge_old_turns(conn, now: datetime) -> int:
    """기획 5.6: 대화 원문은 필요한 기간만. 추출된 정보(기억·일상 기록·요약)는 남는다.
    원문이 다른 곳에 그대로 복사돼 있는 칸도 같이 비운다: 일상 기록의 근거, 퀴즈 답.
    (기억의 근거는 기억과 함께 남는다 — 어르신이 '내 기억' 화면에서 지우면 같이 지워짐)"""
    lim = now - timedelta(days=TURN_RETENTION_DAYS)
    r = run(conn, "DELETE FROM turns WHERE created_at < :lim", lim=lim)
    run(conn, "UPDATE daily_records SET evidence = '' WHERE created_at < :lim AND evidence <> ''", lim=lim)
    run(conn, "UPDATE quiz_answers SET user_answer = '' WHERE created_at < :lim AND user_answer <> ''", lim=lim)
    return r.rowcount


def _job_invite():
    with engine.begin() as conn:
        send_daily_invites(conn, datetime.now(KST).date())


def _job_minutely():
    with engine.begin() as conn:
        end_idle_conversations(conn, datetime.now(KST))


def _job_nightly():
    with engine.begin() as conn:
        purge_old_turns(conn, datetime.now(KST))


def start() -> BackgroundScheduler:
    s = BackgroundScheduler(timezone=KST)
    # misfire_grace_time: 서버가 10:00에 바빴거나 잠깐 꺼져 있었어도 1시간 안에 다시 켜지면 그날 알림을 보냄
    s.add_job(_job_invite, "cron", hour=DAILY_INVITE_TIME.hour, minute=DAILY_INVITE_TIME.minute,
              misfire_grace_time=3600, coalesce=True)
    s.add_job(_job_minutely, "interval", minutes=1, max_instances=1)
    s.add_job(_job_nightly, "cron", hour=3, minute=10)
    s.start()
    if datetime.now(KST).time() >= DAILY_INVITE_TIME:            # 알림 시각 이후에 서버를 켰으면 오늘 몫을 바로
        s.add_job(_job_invite)                                    # (이미 보낸 사람은 notification_log가 막음)
    return s
