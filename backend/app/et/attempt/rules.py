"""ET06 測驗作答之純業務規則（US6 / #279）。

**完全不碰 DB**：計分、剩餘次數、逾時判定、洗牌都能以純函式表達，故全部以 unit test
涵蓋；integration 只驗接線與快照真的落地。

## 計分一律讀「快照」

本模組的 `score_question` 只吃 `OptionSnapshot`——那是 `ET_QUIZ_ATTEMPT_D.OPTIONS_SNAPSHOT`
的內容，不是 `ET_OPTION` 的當前值。這不只是參數形狀的選擇：**回頭查現況會讓「教師在
學員作答期間改了配分或正確答案」變成靜默算錯分**，而學員拿到的是一個看起來正常的分數。

## 計時一律以 `STARTED_AT` 為基準

wireframe 引導頁的作答注意事項明訂「點擊『開始作答』後立即計時，**中途離開或關閉視窗
仍持續扣時間**」。故剩餘秒數由 `STARTED_AT + 時限 − now` 推導，而不是每次載入重新起算
——後者會讓「關掉分頁再開」變成無限延長時間的手法。
"""

import random
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from app.et.constants import QUESTION_MULTIPLE

#: `ET_QUIZ_ATTEMPT_D.SCORE` 為 `DECIMAL(5,2)`。
_CENTS = Decimal("0.01")


class OptionSnapshot(NamedTuple):
    """`OPTIONS_SNAPSHOT` 中的一個選項（開始作答時凍結）。"""

    option_id: int
    text: str
    is_correct: bool


def score_question(question_type: str, selected: list[int], options: list[OptionSnapshot], *, points: int) -> Decimal:
    """單題得分（FR-ET-US6-07）。

    - **單選**：全有全無——答對得配分、答錯 0 分
    - **多選**：`max(0, (對 − 誤) ÷ 應選 × 配分)`

    Args:
        selected: 學員選的 `option_id`；空清單 = 未作答。
        options: **該次 attempt 的選項快照**，不是 `ET_OPTION` 的當前值。
    """
    correct_ids = {o.option_id for o in options if o.is_correct}
    chosen = set(selected)
    if question_type != QUESTION_MULTIPLE:
        # 單選收到多個選項＝前端壞了或有人繞過 UI。**不可**因為「其中一個對」就給分。
        hit = len(chosen) == 1 and chosen.issubset(correct_ids)
        return Decimal(points) if hit else Decimal(0)

    required = len(correct_ids)
    if required == 0:
        # 建題時強制至少 1 個正確選項（`data-model`），但資料異常不該讓提交 500
        return Decimal(0)
    hit = len(chosen & correct_ids)
    miss = len(chosen - correct_ids)
    # `max(0, ...)` 不是防呆而是規則——負分會讓這題倒扣其他題的分數
    raw = Decimal(max(0, hit - miss)) * Decimal(points) / Decimal(required)
    return raw.quantize(_CENTS, rounding=ROUND_HALF_UP)


def round_used_attempts(*, total: int, reset_base: int) -> int:
    """本輪已用作答次數（`data-model` §ET_QUIZ_RETRY_RESET）。

    Args:
        total: 該學員於該測驗之 attempt 總數（**永不刪除**，append-only）。
        reset_base: `MAX(ATTEMPT_COUNT_AT_RESET)`；無重置紀錄時為 0。

    「重置重考次數」不刪除任何 attempt——它記下「重置當下已有幾次」作為本輪的起算基準，
    這樣歷次作答明細才能永久回看（原「歸 0」若以刪除實作，與該保證互斥）。
    """
    return max(0, total - reset_base)


def can_start_attempt(*, total: int, reset_base: int, max_retry: int) -> bool:
    """是否還能開始新的作答。

    ⚠️ **`MAX_RETRY = 0` 是「只能作答 1 次」，不是「不能作答」**——總可作答次數
    = `MAX_RETRY + 1`（見 `quiz/models.py`）。把它讀成「不能作答」會讓所有未設重考
    次數的測驗全部打不開，而那是預設值最可能的樣子。
    """
    return round_used_attempts(total=total, reset_base=reset_base) <= max_retry


def remaining_attempts(*, total: int, reset_base: int, max_retry: int) -> int:
    """本輪剩餘可作答次數（含尚未開始的第一次）。"""
    used = round_used_attempts(total=total, reset_base=reset_base)
    return max(0, max_retry + 1 - used)


def remaining_seconds(*, started_at: datetime, time_limit_min: int | None, now: datetime) -> int | None:
    """剩餘作答秒數；`time_limit_min` 為 `None`（不限時）時回 `None`。

    **回 `None` 而不是回 0 或一個很大的數**：前端據此決定「不顯示倒數區塊」，而 0 會被
    渲染成「時間到」、大數會渲染成一個荒謬的倒數。
    """
    if time_limit_min is None:
        return None
    deadline = started_at + timedelta(minutes=time_limit_min)
    return max(0, int((deadline - now).total_seconds()))


def is_timed_out(*, started_at: datetime, time_limit_min: int | None, now: datetime) -> bool:
    """是否已超過作答時限。不限時者恆為 `False`。

    逾時**不是錯誤**——`spec_us6` 場景 10 要求「以當前作答狀態自動提交」。呼叫端據此把
    `STATUS` 記為 `TIMEOUT` 並**照常閱卷**，而不是拒收學員已經寫好的答案。
    """
    remaining = remaining_seconds(started_at=started_at, time_limit_min=time_limit_min, now=now)
    return remaining is not None and remaining <= 0


def shuffled(ids: list[int]) -> list[int]:
    """回傳重排後的**新** list（不改動輸入）。

    `random` 而非 `secrets`：這是呈現順序，不是安全邊界——猜到順序也拿不到答案，
    因為正確答案從不隨題目一起送給前端（僅提交後的明細才回）。

    不需要可重現的 seed：順序於開始作答時寫入 `QUESTION_ORDER` / `OPTION_ORDER` 快照，
    重現由快照達成。
    """
    out = list(ids)
    random.shuffle(out)  # noqa: S311 — 呈現順序，非密碼學用途（見 docstring）
    return out
