"""`_flush_catching_duplicate` 只認名稱唯一約束，不冒名頂替其他完整性錯誤（#506）。

TOCTOU 那條路（兩位管理者同時送出同名標籤）需要真實並發，測不到；但「**哪些**
`IntegrityError` 該被轉成 409」可以測，而那正是容易寫錯的那一半——`except IntegrityError`
全收會把 FK / NOT NULL / 長度超限等未預期的缺陷一律標成「名稱重複」，使用者看到錯的 409、
真正的原因被吞掉，而未預期的錯誤本來就該以 500 現形才會被發現。

不連 DB：直接餵假的 session 與假的 `IntegrityError`，驗分流。
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AppError
from app.dm.catalog.adapter import _flush_catching_duplicate

pytestmark = pytest.mark.unit


class _Orig(Exception):
    """假的 DBAPI 例外：帶 `sqlstate`，比照 SQLAlchemy asyncpg dialect 代理過來的形狀。"""

    def __init__(self, message: str, sqlstate: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


class _FlushRaises:
    """假 session：flush 時拋出指定 orig 訊息 / sqlstate 的 `IntegrityError`。"""

    def __init__(self, orig_message: str, sqlstate: str = "23505") -> None:
        self._orig = _Orig(orig_message, sqlstate)

    async def flush(self) -> None:
        raise IntegrityError("INSERT ...", {}, self._orig)


class _FlushOk:
    def __init__(self) -> None:
        self.flushed = False

    async def flush(self) -> None:
        self.flushed = True


async def test_撞名稱唯一約束轉成409() -> None:
    db = _FlushRaises('duplicate key value violates unique constraint "UQ_DM_TAG_GROUP_NAME"')

    with pytest.raises(AppError) as exc:
        await _flush_catching_duplicate(db)  # type: ignore[arg-type]

    assert exc.value.status_code == 409
    assert exc.value.error_code == "DM_CATALOG_001"


async def test_其他完整性錯誤原樣拋出不冒充名稱重複() -> None:
    """⛔ 這條是本檔的重點：全收 `IntegrityError` 時它會變紅。

    若有人把守門改回 `except IntegrityError: raise AppError(...)`，這個 FK 違反就會被
    說成「此標籤名稱在該組已存在」——錯的訊息，而且真正的缺陷從此看不見。
    """
    db = _FlushRaises('insert or update violates foreign key constraint "FK_DM_TAG_GROUP"', sqlstate="23503")

    with pytest.raises(IntegrityError):
        await _flush_catching_duplicate(db)  # type: ignore[arg-type]


async def test_使用者把標籤取名為約束名也不會矇混過關() -> None:
    """🔴 判斷式的比對母體不得含使用者輸入。

    PostgreSQL 的 `DETAIL:` 行會把整列欄位值印出來（`Failing row contains (…)`），而
    `TAG_NAME` **是使用者輸入的**。若比對整個 `str(exc.orig)`，一個名叫 `UQ_DM_TAG_GROUP_NAME`
    的標籤就能讓不相干的錯誤被說成「名稱重複」——正是這個函式存在的理由被反過來利用。

    今天打不到（`DM_TAG` 無 CHECK、FK 違反的 DETAIL 不含 `TAG_NAME`），但這是形狀問題，
    加一個欄位或一條 CHECK 就會活過來。
    """
    db = _FlushRaises(
        'null value in column "TAG_GROUP_CODE" violates not-null constraint\n'
        "DETAIL:  Failing row contains (99, AUDIENCE, UQ_DM_TAG_GROUP_NAME, t).",
        sqlstate="23502",
    )

    with pytest.raises(IntegrityError):
        await _flush_catching_duplicate(db)  # type: ignore[arg-type]


async def test_正常情況照常flush() -> None:
    """正向錨點：沒有例外時不得誤攔——否則上面兩條可能只是因為它永遠拋錯而通過。"""
    db = _FlushOk()

    await _flush_catching_duplicate(db)  # type: ignore[arg-type]

    assert db.flushed is True
