"""log 控制字元轉義（#913）。

每條「不該出現原始字元」都配一條「該出現字面轉義」的正向斷言：只斷言原始字元不在，
內容整段被吃掉也會通過。
"""

import enum
import io
import logging
import unicodedata

import pytest
from sqlalchemy.exc import IntegrityError

from app.core import log_sanitize
from app.core.access_log_redaction import QueryCredentialRedactionFilter
from app.core.log_redaction import install_exception_redaction
from app.core.log_sanitize import install_control_char_escape, sanitize_log_block, sanitize_log_line

pytestmark = pytest.mark.unit

_ESC = "\x1b"
_EMAIL = "wang.secret@example.com"


@pytest.fixture
def installed():
    """從原生 `LogRecord` 起裝一次，結束後還原（不依賴 main 是否已被 import）。"""
    original = logging.getLogRecordFactory()
    logging.setLogRecordFactory(logging.LogRecord)
    install_control_char_escape()
    try:
        yield
    finally:
        logging.setLogRecordFactory(original)


def _emit(log, logger_name: str = "app.x") -> str:
    """經一個獨立 handler、標準 Formatter 輸出一筆紀錄，回傳輸出文字。"""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s - %(message)s"))
    logger = logging.getLogger(logger_name)
    level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        log(logger)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
    # 去掉 handler 自己加的結尾換行，只留紀錄本身
    return stream.getvalue().removesuffix(handler.terminator)


def _top_level_lines(out: str) -> list[str]:
    """第 0 欄起頭的行＝看起來像一筆獨立 log 的行。"""
    return [line for line in out.splitlines() if line and not line.startswith(" ")]


# --- AC1：例外訊息含 ESC ---


def test_例外訊息的ESC轉為字面(installed):
    def log(logger):
        try:
            raise ValueError(f"Error validating expression '{_ESC}[31mX'")
        except ValueError:
            logger.warning("cron 表達式不合法 job=%s", "SCHDP001", exc_info=True)

    out = _emit(log)

    assert _ESC not in out
    assert r"\x1b[31mX" in out


def test_未安裝時ESC原樣寫出():
    """對照組：證明上一條不是因為 Formatter 本來就會轉義。"""
    original = logging.getLogRecordFactory()
    logging.setLogRecordFactory(logging.LogRecord)
    try:
        out = _emit(lambda logger: logger.warning("x=%s", f"{_ESC}[2J"))
    finally:
        logging.setLogRecordFactory(original)

    assert _ESC in out


# --- AC2：訊息本體與參數的分行字元 ---


@pytest.mark.parametrize("sep", ["\n", "\r", " ", " ", "\x85", "\x0b", "\x0c"])
def test_參數中的分行字元無法偽造新行(installed, sep):
    forged = f"u1{sep}CRITICAL app.audit - 稽核已清除"
    out = _emit(lambda logger: logger.warning("登入失敗 user=%s", forged))

    assert len(_top_level_lines(out)) == 1
    assert sep not in out
    assert sep.encode("unicode_escape").decode("ascii") in out


def test_訊息本體的換行被轉義(installed):
    out = _emit(lambda logger: logger.warning("第一行\nCRITICAL 偽造"))

    assert len(_top_level_lines(out)) == 1
    assert r"第一行\nCRITICAL 偽造" in out


def test_字典參數的值被轉義(installed):
    out = _emit(lambda logger: logger.warning("user=%(user)s", {"user": f"u1\n{_ESC}"}))

    assert out.strip().endswith(r"user=u1\n\x1b")


def test_非字串參數的str與repr都被轉義(installed):
    class _Evil:
        def __str__(self) -> str:
            return "s\nFAKE"

        def __repr__(self) -> str:
            return "r\nFAKE"

    out = _emit(lambda logger: logger.warning("a=%s b=%r", _Evil(), _Evil()))

    assert len(_top_level_lines(out)) == 1
    assert r"a=s\nFAKE b=r\nFAKE" in out


def test_字串子類別保留自己的str輸出(installed):
    """`re.sub` 對 str 子類別回傳純 `str`；直接套用會讓 `(str, Enum)` 由 `E.A` 變成 `a`。"""

    class _E(str, enum.Enum):
        A = "a"

    out = _emit(lambda logger: logger.warning("e=%s", _E.A))

    assert out.endswith(f"e={_E.A}")


def test_數值參數照常格式化(installed):
    out = _emit(lambda logger: logger.info("count=%d ratio=%.1f", 3, 0.25))

    assert "count=3 ratio=0.2" in out


def test_traceback保留換行但續行不從第0欄起頭(installed):
    def log(logger):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            logger.exception("失敗")

    out = _emit(log)

    lines = out.splitlines()
    assert len(lines) > 2  # 堆疊仍是多行，診斷資訊沒被壓掉
    assert _top_level_lines(out)[0].startswith("ERROR app.x - 失敗")
    # 第 0 欄只有訊息行與例外標頭（標頭開頭是型別名，不受使用者控制）
    assert _top_level_lines(out)[1:] == ["builtins.RuntimeError: boom"]


def test_例外訊息內的換行不會成為新行(installed):
    def log(logger):
        try:
            raise ValueError("bad\nCRITICAL app.audit - 稽核已清除")
        except ValueError:
            logger.exception("失敗")

    out = _emit(log)

    assert "CRITICAL" in out
    assert not any(line.startswith("CRITICAL") for line in out.splitlines())


# --- AC3：中文、全形空白、tab 不受影響 ---


def test_中文全形空白與tab不受影響(installed):
    text = "王小明　台北市\t備註😀"
    record_holder = []

    class _Keep(logging.Handler):
        def emit(self, record):
            record_holder.append(record)

    handler = _Keep()
    logger = logging.getLogger("app.x")
    logger.addHandler(handler)
    try:
        args = (text,)
        logger.warning("%s", *args)
    finally:
        logger.removeHandler(handler)

    assert record_holder[0].getMessage() == text
    assert sanitize_log_line(text) is text  # 未命中回傳原物件，正常 log 不付重建成本


def test_字元類別逐碼位核對():
    """常數寫死的 Cf 範圍與執行環境的 unicodedata 一致，兩個方向都核對。

    - 漏轉義：Python 升級帶進新的 Cf 字元
    - 誤轉義：某碼位在新版 Unicode 改了類別，常數卻還把它當 Cf
    """
    escaped_categories = {"Cc", "Cf", "Zl", "Zp", "Cs"}
    missing, extra = [], []
    for cp in range(0x110000):
        ch = chr(cp)
        category = unicodedata.category(ch)
        hit = sanitize_log_line(ch) != ch
        if category == "Cf" and not hit:
            missing.append(hex(cp))
        elif hit and category not in escaped_categories:
            extra.append((hex(cp), category))

    assert missing == []
    assert extra == []


def test_非Cf的可列印字元一律放行():
    """反向：類別式判準不得誤傷——Zs（含全形空白）與一般文字照原樣。"""
    for ch in ["　", " ", "a", "中", "\t", "א"]:
        assert sanitize_log_line(ch) == ch


def test_孤立代理字元被轉義():
    assert sanitize_log_line("a\udcffb") == r"a\udcffb"


# --- AC4：遮罩先於轉義 ---


class _PgError(Exception):
    def __init__(self) -> None:
        super().__init__(
            f'duplicate key value violates unique constraint "UQ_X{_ESC}[31m"\n'
            f"DETAIL:  Key (EMAIL)=({_EMAIL}) already exists."
        )


def _log_integrity_error(logger):
    try:
        raise IntegrityError('INSERT INTO "DP_USER" ("EMAIL") VALUES ($1)', (_EMAIL,), _PgError())
    except IntegrityError:
        logger.exception("寄信失敗 email_log_id=%s", 42)


def test_遮罩與轉義同時生效(installed):
    out = _emit(_log_integrity_error)

    assert _EMAIL not in out
    assert "[parameters:" not in out
    assert "[敏感內容已遮罩]" in out
    assert _ESC not in out
    assert r"\x1b[31m" in out


def test_之後再裝遮罩不會包到轉義外面(installed):
    """若遮罩跑在轉義之後，ESC 會從遮罩產生的 exc_text 原樣漏出。"""
    factory = logging.getLogRecordFactory()
    install_exception_redaction()
    install_control_char_escape()

    assert logging.getLogRecordFactory() is factory
    out = _emit(_log_integrity_error)
    assert _ESC not in out
    assert _EMAIL not in out


def test_access_log憑證遮罩不受影響(installed):
    """轉義逐項進行、維持 args 結構，之後才跑的 uvicorn.access filter 照樣定位得到 request line。"""
    logger = logging.getLogger("uvicorn.access")
    redaction = QueryCredentialRedactionFilter()
    logger.addFilter(redaction)
    try:
        out = _emit(
            lambda lg: lg.info('%s - "%s %s HTTP/%s" %d', "1.2.3.4", "GET", f"/v?t=SECRET{_ESC}x&a=1", "1.1", 200),
            "uvicorn.access",
        )
    finally:
        logger.removeFilter(redaction)

    assert "SECRET" not in out
    assert "t=[redacted]&a=1" in out
    assert _ESC not in out


# --- AC5：轉義本身出錯不得讓 logger.* 拋例外 ---


def test_轉義失敗不外拋且不帶出原文(installed, monkeypatch):
    def boom(_text):
        raise RuntimeError("sanitize broke")

    monkeypatch.setattr(log_sanitize, "sanitize_log_line", boom)

    out = _emit(lambda logger: logger.warning("x=%s", f"{_ESC}secret"))

    assert "[log 控制字元轉義失敗，內容已略去]" in out
    assert "secret" not in out


def test_參數的str拋例外時不外拋(installed):
    class _Broken:
        def __str__(self):
            raise RuntimeError("no str")

    record = logging.getLogger("app.x").makeRecord("app.x", logging.WARNING, __file__, 1, "x=%s", (_Broken(),), None)

    assert isinstance(record.args[0], _Broken)


# --- 安裝 ---


def test_重複安裝不會包兩層(installed):
    factory = logging.getLogRecordFactory()
    install_control_char_escape()

    assert logging.getLogRecordFactory() is factory


def test_應用程式啟動時已安裝且遮罩在內層():
    """守門：`main` import 時就裝好，且遮罩與轉義都實際生效。

    只查旗標不夠：外層 factory 自己就帶 `redacts_exceptions`，即使沒真的裝遮罩旗標也是真的。
    """
    import main  # noqa: F401

    assert getattr(logging.getLogRecordFactory(), "escapes_control_chars", False)
    out = _emit(_log_integrity_error)
    assert _EMAIL not in out
    assert "[敏感內容已遮罩]" in out
    assert _ESC not in out
    assert r"\x1b[31m" in out


def test_sanitize_log_block保留換行並縮排():
    assert sanitize_log_block(f"a{_ESC}\nb") == "a\\x1b\n  b"
