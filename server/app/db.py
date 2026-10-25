"""DB 연결. SQL을 직접 쓰고(text), 결과는 dict처럼 꺼내 쓴다."""
from sqlalchemy import create_engine, text

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL)


def get_db():
    """API 요청 하나 = 트랜잭션 하나.
    요청 처리 중 오류가 나면 그 요청에서 쓴 내용이 전부 취소(rollback)되고,
    끝까지 성공해야 한꺼번에 저장(commit)된다."""
    with engine.begin() as conn:
        yield conn


def one(conn, sql, **params):
    """결과 한 행 (없으면 None)"""
    row = conn.execute(text(sql), params).mappings().first()
    return dict(row) if row else None


def rows(conn, sql, **params):
    """결과 여러 행"""
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def run(conn, sql, **params):
    """INSERT/UPDATE처럼 결과가 필요 없는 명령"""
    return conn.execute(text(sql), params)
