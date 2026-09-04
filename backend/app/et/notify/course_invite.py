"""課程邀請信之參數組法與連結產生（US8 / #273）。

## 為何四條寄信路徑共用這一個模組

課程邀請信有四個觸發點——發布時標籤帶入、已發布課程新增標籤、貼標追溯（彙整信）、
教師 Email 邀請。前三者用同一個範本 `COURSE_INVITE`、需要同一組七個佔位。

params 的 key 若與範本佔位對不上，平台 `_SafeFormatter` 會拋 `KeyError` →
該批寫成 `DP_EMAIL_LOG.STATUS='FAILED'`、`queued_count=0`，**且不外拋**——呼叫方
看起來一切正常，只是沒有人收到信。把 params 組法散在三個 service 各寫一次，等於
把這個靜默失敗面複製三份。故集中於此，並由 `tests/unit/et/test_et_invitation_mail.py`
把 key 集合釘死。

## 信件時間為何要換算台北時區

`ET_COURSE.OPEN_START_AT` / `OPEN_END_AT` 為 `TIMESTAMPTZ`，前端以
`startAt.toISOString()`（UTC）送出、UI 以 `formatDateTime` 用**本地時區**顯示。
若比照 `dp/users/service.py` 直接 `strftime` UTC 值，信件會寫出比教師設定**早 8 小時**
的閱課期間——學員據此以為課程尚未開放或已經截止。輸出格式亦刻意對齊前端
`frontend/src/utils/date.ts` 之 `formatDateTime`（`YYYY/MM/DD HH:mm`），使教師在
ET02 看到的與學員信裡讀到的是同一串字。

> DP / DM 既有信件同樣直接輸出 UTC（多為僅日期、影響較小），本次不順手改動
> （最小變更原則）；已於 #273 列為 follow-up。
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.et.course.models import EtCourse

#: 使用者可見時間之呈現時區。EDMS 為單一組織、單一院區，不做逐使用者時區。
_DISPLAY_TZ: Final = ZoneInfo("Asia/Taipei")

#: 對齊 `frontend/src/utils/date.ts` 之 `formatDateTime`。
_DISPLAY_FORMAT: Final = "%Y/%m/%d %H:%M"

#: 起訖時間未填時的呈現。空字串會讓內文出現「閱課期間： ～ 」這種殘句。
_UNSET: Final = "未設定"

#: `COURSE_INVITE` 之佔位（`DP_NOTIFY_TEMPLATE.VARIABLES`，`MODULE='ET'`）。
COURSE_INVITE_PARAM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "USER_NAME",
        "TEACHER_NAME",
        "COURSE_NAME",
        "OPEN_START_AT",
        "OPEN_END_AT",
        "COURSE_URL",
        "INVITATION_CODE",
    }
)

#: `COURSE_INVITE_DIGEST` 之佔位。
DIGEST_PARAM_KEYS: Final[frozenset[str]] = frozenset({"USER_NAME", "COURSE_LIST"})

#: 預覽信中代替真實 token 的字樣——每位收件人之 token 於寄出當下才產生，
#: 預覽不得出現一條真的可以用的連結。
#: （命名避開 `TOKEN` 字樣：ruff `S105` 會把含該字的常數賦值視為硬編碼機密。）
_PREVIEW_LINK_MASK: Final = "…"


def _base_url() -> str:
    """前端站台根網址（去尾斜線）。

    設定值帶不帶尾斜線都可能（`.env` 由人手維護），不正規化會組出 `//et/...`。
    """
    return settings.FRONTEND_BASE_URL.rstrip("/")


def learn_link(course_id: int) -> str:
    """ET05 章節學習頁連結——收件人已在課程中時用（標籤帶入 / 彙整信）。"""
    return f"{_base_url()}/et/courses/{course_id}/learn"


def invite_link(token: str) -> str:
    """Email 邀請連結（帶明文 token）——收件人可能尚無帳號、也尚未加入課程。

    明文僅存在於信件連結中；`ET_INVITATION` 只存 `hash_token()` 之結果。
    """
    return f"{_base_url()}/et/invite?token={token}"


def preview_invite_link() -> str:
    """寄送預覽用之連結樣板（不含可用 token）。"""
    return invite_link(_PREVIEW_LINK_MASK)


def format_open_at(value: datetime | None) -> str:
    """閱課起訖時間 → 台北時間之可讀字串；未設定回 `未設定`。"""
    if value is None:
        return _UNSET
    return value.astimezone(_DISPLAY_TZ).strftime(_DISPLAY_FORMAT)


def build_course_invite_params(
    *,
    user_name: str,
    teacher_name: str,
    course: EtCourse,
    course_url: str,
    invitation_code: str | None,
) -> dict[str, str]:
    """組 `COURSE_INVITE` 之範本參數。

    Args:
        user_name: 收件人顯示名稱。Email 邀請之對象可能尚無帳號，此時由呼叫端傳入
            Email 原字串——範本開頭為「{USER_NAME} 您好：」，留空會變成「 您好：」。
        teacher_name: 課程擁有者姓名。
        course: 課程列（取名稱與起訖時間）。
        course_url: 學習連結或邀請連結，依觸發路徑而異（見模組 docstring）。
        invitation_code: 課程邀請碼；草稿課程為 None（理論上不會走到寄信）。

    Returns:
        七個佔位之 `dict[str, str]`，key 與 `COURSE_INVITE_PARAM_KEYS` 相同。
    """
    return {
        "USER_NAME": user_name,
        "TEACHER_NAME": teacher_name,
        "COURSE_NAME": course.course_name,
        "OPEN_START_AT": format_open_at(course.open_start_at),
        "OPEN_END_AT": format_open_at(course.open_end_at),
        "COURSE_URL": course_url,
        "INVITATION_CODE": invitation_code or "",
    }


def build_digest_params(*, user_name: str, courses: Sequence[EtCourse]) -> dict[str, str]:
    """組 `COURSE_INVITE_DIGEST` 之範本參數（貼標追溯：多門課彙整成一封）。

    `{COURSE_LIST}` 為多行純文字。平台渲染**內文時保留 LF**（僅主旨剝換行），
    故此處可安全使用換行排版。

    Args:
        user_name: 收件人顯示名稱。
        courses: 本次補加入之課程（順序即呈現順序）。

    Returns:
        兩個佔位之 `dict[str, str]`。
    """
    blocks = [
        f"・{c.course_name}（{format_open_at(c.open_start_at)} ～ {format_open_at(c.open_end_at)}）"
        f"\n  {learn_link(c.course_id)}"
        for c in courses
    ]
    return {"USER_NAME": user_name, "COURSE_LIST": "\n\n".join(blocks)}
