"""푸시 알림 (FCM). FIREBASE_CREDENTIALS가 없으면 콘솔에 찍기만 한다(개발용)."""
from .config import FIREBASE_CREDENTIALS
from .db import rows

_ready = None


def _fcm_ready() -> bool:
    global _ready
    if _ready is None:
        _ready = False
        if FIREBASE_CREDENTIALS:
            import firebase_admin
            from firebase_admin import credentials
            firebase_admin.initialize_app(credentials.Certificate(FIREBASE_CREDENTIALS))
            _ready = True
    return _ready


def send_to_user(conn, user_id: int, data: dict, title: str | None = None, body: str | None = None) -> bool:
    """user의 모든 기기로 푸시. 하나라도 성공하면 True."""
    if not _fcm_ready():
        print(f"[push:dev] user={user_id} data={data} title={title!r} body={body!r}")
        return True
    tokens = [r["fcm_token"] for r in rows(conn, "SELECT fcm_token FROM devices WHERE user_id = :u", u=user_id)]
    if not tokens:
        return False
    from firebase_admin import messaging
    msg = messaging.MulticastMessage(
        tokens=tokens,
        data={k: str(v) for k, v in data.items()},           # 앱이 읽는 신호 (예: START_CHECKIN)
        notification=messaging.Notification(title=title, body=body) if title else None,
        android=messaging.AndroidConfig(priority="high"),     # 잠든 폰도 깨우도록
    )
    return messaging.send_each_for_multicast(msg).success_count > 0
