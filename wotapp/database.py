from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_engine = None
_Session: sessionmaker | None = None


class Base(DeclarativeBase):
    pass


def _sqlite_url(path: Path) -> str:
    # 绝对路径：Windows 为 sqlite:///C:/...，Unix 为 sqlite:////...
    return "sqlite:///" + path.resolve().as_posix()


def get_engine():
    global _engine, _Session
    if _engine is None:
        from wotapp.config import get_settings

        path = Path(get_settings().sqlite_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            _sqlite_url(path),
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> sessionmaker:
    get_engine()
    assert _Session is not None
    return _Session


def init_db() -> None:
    from wotapp import models  # noqa: F401

    Base.metadata.create_all(get_engine())


def reset_db() -> None:
    """测试用：丢掉已创建的引擎，使下一次连接读取新的 SQLITE_PATH。"""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
