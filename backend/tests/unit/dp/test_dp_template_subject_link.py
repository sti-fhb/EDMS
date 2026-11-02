"""DP04 主旨禁用一次性連結類變數（#50 SA 2026-11-02 裁示 3）。

outbox 只遮罩 BODY，主旨會出現在寄送紀錄列表與 log、事後遮罩擋不完，故存檔時擋下。
檢核以 `_render` 實跑（與 `ensure_renderable` 同一姿態），本檔釘住判斷與實際渲染一致。
"""

import pytest

from app.core.exceptions import AppError
from app.dp.notify.redaction import ONE_TIME_LINK_VARIABLES
from app.dp.notify.service import ensure_subject_without_link

pytestmark = pytest.mark.unit

#: 對齊 DP 種子 VARIABLES 的真實格式（識別字 + 全形括號說明）
_PWD_RESET_VARS = "user_name（使用者姓名）, reset_link（密碼重設連結）, expiry_minutes（連結有效分鐘數）"


@pytest.mark.parametrize(
    ("variables", "subject"),
    [
        (_PWD_RESET_VARS, "【EDMS】密碼重設 {reset_link}"),
        ("user_name（使用者姓名）, verify_link（驗證連結）", "{verify_link}"),
        ("user_name（使用者姓名）, activate_link（啟用連結）", "請啟用 {activate_link} 謝謝"),
        (_PWD_RESET_VARS, "{reset_link!s}"),  # conversion 也會代入值
    ],
)
def test_subject_with_link_variable_rejected(variables, subject):
    with pytest.raises(AppError) as exc:
        ensure_subject_without_link(subject=subject, variables=variables)
    assert exc.value.status_code == 422
    assert exc.value.error_code == "DP_MAIL_013"
    # 訊息不嵌入變數名稱（sti-error-codes）
    assert all(name not in exc.value.detail for name in ONE_TIME_LINK_VARIABLES)


@pytest.mark.parametrize(
    "subject",
    [
        "【EDMS】密碼重設通知",  # 種子主旨
        "{user_name} 的密碼重設通知",  # 非連結變數
        "{{reset_link}}",  # 跳脫後是字面文字，不會代入連結
        "reset_link",  # 純文字
    ],
)
def test_subject_without_link_passes(subject):
    ensure_subject_without_link(subject=subject, variables=_PWD_RESET_VARS)


def test_non_one_time_link_variables_allowed():
    """一般頁面連結（ET COURSE_URL / DM dashboard_link）不在禁止範圍。"""
    ensure_subject_without_link(subject="{COURSE_URL}", variables="USER_NAME,COURSE_URL")
    ensure_subject_without_link(subject="{dashboard_link}", variables="reviewer_name,dashboard_link")


def test_no_declared_variables():
    ensure_subject_without_link(subject="主旨", variables=None)
