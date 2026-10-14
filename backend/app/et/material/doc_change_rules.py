"""引用之 DM 文件變動的比對規則（#231）。

ET 教材引用的 DM 文件**恆取當前發布版**（`FR-ET-US3-05`、`spec_us3` AC 10），學員下次
開啟章節即看到新內容。本模組不改變該行為，只負責判斷「要不要通知課程擁有者」。

## 為何需要簿記才判斷得出來

`ET_MATERIAL_DOC` 依 `data-model` 明訂**只存 `DOC_ID`、不存版本號**（理由：不存版本號
→「恆取最新版」不可能出錯）。所以 ET 自己無從得知「上次是哪一版」。

#231 裁示 B′：把「上次通知這位擁有者時的版本與狀態」放在**獨立的簿記表**
（`ET_MATERIAL_DOC_NOTIFY`），供本模組比對。⛔ **內容解析路徑永不讀那張表**——
`data-model` 那條規則的保證因此完全未被動到。

## 為何不是在 DM 發布當下通知（掛鉤機制 A）

A 需要一套跨模組事件登記，而本專案既有的 `module_assign_registry` 已經踩過它的失效
模式：找不到 provider 時 fallback 是 no-op，**不報錯、不留紀錄**。本功能存在的目的正是
消除無聲的漂移，若通知機制自己會無聲失效，教師會把「沒收到信」讀成「沒事」。
排程失敗則會進 `DP_SCHEDULE_LOG`、DP06 排程總覽看得見（#231 裁示，見該 issue 留言）。
"""

from enum import Enum
from typing import Final

#: DM 文件已廢止之狀態值（`DmCurrentVersion.status`）。
DOC_OBSOLETE: Final = "OBSOLETE"


class DocChangeEvent(Enum):
    """比對結果。`None` 代表無變動、不寄信。"""

    #: 當前發布版換了一版——教師要去確認測驗題是否仍對得上新內容。
    NEW_VERSION = "NEW_VERSION"
    #: 文件已廢止——教師要移除引用或換一份，否則該課程再發布時會被 `BLOCK_OBSOLETE_DOC` 擋下。
    OBSOLETED = "OBSOLETED"
    #: 第一次看到這組 `(文件, 擁有者)`：**記下基準、不寄信**（#636）。
    #:
    #: 🔴 呼叫端收到此值時**必須寫入簿記**。若比照 `None` 一併略過，該組合會永遠
    #: 停在「查無簿記」，連日後真正的改版也再不會通知——那是把一個吵雜的缺陷換成
    #: 一個靜默的缺陷。`test_記下基準之後真的改版仍會通知` 釘住這件事。
    BASELINE_ONLY = "BASELINE_ONLY"


def classify_doc_change(
    *,
    last_notified_version_id: int | None,
    last_notified_status: str | None,
    current_version_id: int,
    current_status: str,
) -> DocChangeEvent | None:
    """判斷某份文件對某位擁有者而言是否有「需通知的變動」。

    Args:
        last_notified_version_id: 簿記表上次通知時的 `CURRENT_VERSION_ID`；`None` = 查無簿記列。
        last_notified_status: 簿記表上次通知時的文件狀態；`None` = 查無簿記列。
        current_version_id: SRVDM001 回傳之當前 `current_version_id`。
        current_status: SRVDM001 回傳之 `status`（`PUBLISHED` / `OBSOLETE`）。

    Returns:
        `DocChangeEvent`，或 `None`（無變動、不寄信也不寫簿記）。

        ⚠️ `BASELINE_ONLY` 與 `None` **不可同路處理**：前者要求呼叫端寫入簿記。
    """
    now_obsolete = current_status == DOC_OBSOLETE
    was_obsolete = last_notified_status == DOC_OBSOLETE

    # 廢止優先於改版：兩次掃描之間若既出新版又被廢止，教師只需要做一件事
    # （移除引用或換一份）。寄「有新版，去確認測驗題」會把他引向錯的動作。
    if now_obsolete:
        return None if was_obsolete else DocChangeEvent.OBSOLETED

    # 查無簿記列 = 這位擁有者第一次引用這份文件 ⇒ 只記基準、不寄信（#636）。
    #
    # 🔴 原本此處回 `NEW_VERSION`，理由是「裁示 Q1 = C 不回填，正式環境由空的 migration
    # 從頭建起，查無簿記只會發生在引用剛被加進來時」。**前提對、結論錯**——「引用剛被
    # 加進來」正是最不該寄「已發布新版本」的時候：那份文件一版都沒換過，是教師自己剛加的。
    # 2026-10-14 手測實證：`DM-TRAINING-000004` 版本歷程只有一筆、從未上傳新版，教師仍收到信。
    #
    # 且它**不是一次性的**：簿記鍵為 `(文件, 擁有者)`，每位教師第一次引用每一份文件都會
    # 再觸發一次，正式環境亦然。虛驚的通知會訓練教師忽略這一類信，連帶讓真正要緊的
    # `OBSOLETED` 那封也被忽略——這正是 #231 裁定 `PENDING_OBSOLETE` 不通知時用的判準。
    #
    # ⚠️ 代價：記下基準到下一次排程（每日 08:00）之間，文件若真的改版，那一次會漏通知。
    # 窗口最多一天，且教師剛剛才看過那份文件。**這是取捨，不是疏漏。**
    if last_notified_version_id is None:
        return DocChangeEvent.BASELINE_ONLY

    # 以「不相等」而非「變大」判定——這是**失敗方向**的選擇，不是防禦性程式碼：
    # 版本若因任何原因倒退，寄一封「有新版」雖不精確但教師會去看；用 `>` 判定
    # 則會靜默不寄，而靜默正是本功能要消除的東西。
    return DocChangeEvent.NEW_VERSION if current_version_id != last_notified_version_id else None
