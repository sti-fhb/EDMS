"""全域的例外去識別化（#833 C2）。

`logger.exception()` 的 `exc_info` 由 logging 自己格式化成 traceback，最後一行就是 `str(exc)`——SQLAlchemy
的例外在那裡附上 `[SQL: …]` 與 `[parameters: …]`，綁定參數（Email、姓名…）原樣進 log。原本只有
`main.unhandled_exception_handler` 經 `format_exception_for_log` 去識別化，排程、發信 worker 等 21 處
`logger.exception()` 都沒有（`log_redaction` 模組說明列為未涵蓋）。

`install_exception_redaction()` 改由 LogRecordFactory 在紀錄**產生時**就填好去識別化的 `exc_text`：
標準 Formatter 看到已有 `exc_text` 就不再自己格式化，所以不論由哪個 handler 輸出都生效——包括正式環境
實際走的 `logging.lastResort`（root 沒有 handler，見 `install_exception_redaction` 說明）。
"""

import io
import logging

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.log_redaction import install_exception_redaction

pytestmark = pytest.mark.unit

_EMAIL = "wang.secret@example.com"


class _PgError(Exception):
    def __init__(self) -> None:
        super().__init__(
            'duplicate key value violates unique constraint "UQ_DP_USER_EMAIL"\n'
            f"DETAIL:  Key (EMAIL)=({_EMAIL}) already exists."
        )


def _integrity_error() -> IntegrityError:
    return IntegrityError('INSERT INTO "DP_USER" ("EMAIL") VALUES ($1)', (_EMAIL,), _PgError())


@pytest.fixture
def installed():
    """從原生 `LogRecord` 起裝一次，結束後還原，避免影響其他測試（也不依賴 main 是否已被 import）。"""
    original = logging.getLogRecordFactory()
    logging.setLogRecordFactory(logging.LogRecord)
    install_exception_redaction()
    try:
        yield
    finally:
        logging.setLogRecordFactory(original)


def _log_exception(logger_name: str = "app.dp.notify.worker") -> str:
    """以標準 Formatter 經一個獨立 handler 記一筆 `logger.exception`，回傳輸出文字。"""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)
    try:
        try:
            raise _integrity_error()
        except IntegrityError:
            logger.exception("寄信失敗 email_log_id=%s", 42)
    finally:
        logger.removeHandler(handler)
    return stream.getvalue()


def test_未安裝時_綁定參數原樣進_log():
    """對照組：證明下面的斷言不是因為例外本來就不含個資。

    顯式換回原生 `LogRecord`：同一行程裡其他測試 `import main` 時已經裝好了。
    """
    original = logging.getLogRecordFactory()
    logging.setLogRecordFactory(logging.LogRecord)
    try:
        out = _log_exception()
    finally:
        logging.setLogRecordFactory(original)

    assert _EMAIL in out
    assert "[parameters:" in out


def test_logger_exception_的綁定參數與_DETAIL_被去識別化(installed):
    out = _log_exception()

    assert _EMAIL not in out
    assert "[parameters:" not in out
    assert "DETAIL:" not in out


def test_去識別化後仍保留排查所需的資訊(installed):
    """不以「不記 traceback」換取安全：型別、約束名、呼叫位置都要在。"""
    out = _log_exception()

    assert "寄信失敗 email_log_id=42" in out
    assert "sqlalchemy.exc.IntegrityError" in out
    assert "UQ_DP_USER_EMAIL" in out
    assert "test_core_log_exception_redaction.py" in out, "要有堆疊位置"
    assert "[敏感內容已遮罩]" in out, "讀 log 的人要知道是遮罩掉了，不是本來就沒有"


def test_任何_logger_都生效_不限_app(installed):
    """排程（apscheduler）、uvicorn 等第三方 logger 記錄的例外一樣會帶出綁定參數。"""
    assert _EMAIL not in _log_exception("apscheduler.executors.default")


def test_沒有例外的紀錄原樣不動(installed):
    record = logging.getLogger("app.x").makeRecord("app.x", logging.WARNING, __file__, 1, "user=%s", ("u1",), None)

    assert record.exc_text is None
    assert record.getMessage() == "user=u1"


def test_保留_exc_info_供既有程式讀取(installed):
    """只預先填 `exc_text`，不清掉 `exc_info`：caplog 與讀 `record.exc_info` 的既有程式照常運作。"""
    try:
        raise _integrity_error()
    except IntegrityError as exc:
        record = logging.getLogger("app.x").makeRecord(
            "app.x", logging.ERROR, __file__, 1, "x", (), (type(exc), exc, exc.__traceback__)
        )

    assert record.exc_info is not None
    assert record.exc_info[1].__class__ is IntegrityError
    assert _EMAIL not in record.exc_text


def test_重複安裝不會包兩層(installed):
    factory = logging.getLogRecordFactory()
    install_exception_redaction()

    assert logging.getLogRecordFactory() is factory


def test_應用程式啟動時已安裝():
    """守門：`main` import 時就裝好。排程與發信 worker 都在同一個行程，靠這一處涵蓋。"""
    import main  # noqa: F401

    assert getattr(logging.getLogRecordFactory(), "redacts_exceptions", False)


class _UnprintableError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("__str__ 壞掉")


def test_格式化失敗不往外拋_只留型別(installed):
    """記 log 不可讓呼叫端中斷：發信 worker 的 `logger.exception` 在 while 迴圈的 except 裡，
    往外拋就讓整個迴圈結束（code / security review）。"""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("app.dp.notify.worker")
    logger.addHandler(handler)
    try:
        try:
            raise _UnprintableError()
        except _UnprintableError:
            logger.exception("寄信失敗")  # 不拋
    finally:
        logger.removeHandler(handler)

    assert "_UnprintableError: [例外訊息格式化失敗，已省略]" in stream.getvalue()


def test_正式環境的輸出路徑_lastResort_也被去識別化(installed, monkeypatch, capsys):
    """正式環境 root 沒有 handler，紀錄由 `logging.lastResort` 印到 stderr——這正是改用 factory 的理由。

    pytest 會在 root 掛 caplog 的 handler，這裡用一個不往上傳、自己也沒有 handler 的 logger 走到 lastResort。
    """
    logger = logging.getLogger("app.test_last_resort")
    monkeypatch.setattr(logger, "propagate", False)
    assert not logger.handlers

    try:
        raise _integrity_error()
    except IntegrityError:
        logger.exception("寄信失敗")

    err = capsys.readouterr().err
    assert "寄信失敗" in err, "正向錨點：確實走到 lastResort"
    assert "sqlalchemy.exc.IntegrityError" in err
    assert _EMAIL not in err
    assert "[parameters:" not in err
