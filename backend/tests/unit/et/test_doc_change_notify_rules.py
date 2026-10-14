"""引用之 DM 文件變動的比對規則（#231）。

排程每日取各引用文件的現況（SRVDM001），與簿記表上「上次通知這位擁有者時的版本與
狀態」比對，決定要不要寄信、寄哪一種。本檔只測純函式，不碰 DB。
"""

import pytest

from app.et.material.doc_change_rules import DocChangeEvent, classify_doc_change

pytestmark = pytest.mark.unit


class TestClassifyDocChange:
    """FR：發布新版與廢止各寄一種信；無變動不寄。"""

    def test_無簿記列且文件為已發布_只記基準不寄信(self) -> None:
        """🔴 #636 推翻 #231 當初的判斷。

        原本回 `NEW_VERSION`，理由寫著「正式環境由空的 migration 從頭建起，所有引用都在
        本功能上線後才產生，故『查無簿記列』只會發生在這份引用剛被教師加進來時」。

        **前半對、結論錯。** 「剛被教師加進來」正是**不該寄信**的時候——信裡寫著
        「您課程引用的訓練教材文件**已發布新版本**」，而那份文件根本沒改版，是教師自己
        剛加的。2026-10-14 手測實證：`DM-TRAINING-000004` 版本歷程只有一筆、從未上傳新版，
        教師卻收到「已發布新版本」。

        而且它**不是一次性的**——簿記鍵為 `(文件, 擁有者)`，每位教師第一次引用每一份文件
        都會再觸發一次，正式環境亦然。

        ⚠️ 代價：寫入基準到下一次排程之間若文件真的改版，那一次會漏通知（窗口最多一天，
        而教師剛剛才看過那份文件）。這是選擇，不是疏漏。
        """
        assert (
            classify_doc_change(
                last_notified_version_id=None,
                last_notified_status=None,
                current_version_id=7,
                current_status="PUBLISHED",
            )
            == DocChangeEvent.BASELINE_ONLY
        )

    def test_記下基準之後真的改版仍會通知(self) -> None:
        """正向錨點：少了這條，把「查無簿記」改成永遠不通知也會讓上一條通過。

        ⚠️ 上一條的修法**不可只讓規則回 None**——service 看到 None 會略過且不寫簿記，
        該組合會永遠停在「查無簿記」，連真正的改版也再不會通知。本條釘住基準寫入後
        仍然有效。
        """
        assert (
            classify_doc_change(
                last_notified_version_id=7,
                last_notified_status="PUBLISHED",
                current_version_id=8,
                current_status="PUBLISHED",
            )
            == DocChangeEvent.NEW_VERSION
        )

    def test_無簿記列且文件已廢止_視為廢止(self) -> None:
        assert (
            classify_doc_change(
                last_notified_version_id=None,
                last_notified_status=None,
                current_version_id=7,
                current_status="OBSOLETE",
            )
            == DocChangeEvent.OBSOLETED
        )

    def test_版本不同_寄新版(self) -> None:
        assert (
            classify_doc_change(
                last_notified_version_id=7,
                last_notified_status="PUBLISHED",
                current_version_id=8,
                current_status="PUBLISHED",
            )
            == DocChangeEvent.NEW_VERSION
        )

    def test_狀態轉廢止_寄廢止(self) -> None:
        """廢止時 DM 保留 `CURRENT_VERSION_ID` 不變、只翻 `doc.status`。

        見 `dm/review/center_service.py` 檔頭：「核准 → 文件轉 OBSOLETE 自文件庫下架
        （保留 CURRENT_VERSION_ID、原發布版維持 PUBLISHED 供 SRVDM001 廢止旗標）」。
        故廢止的指紋是「版本相同、狀態翻轉」——不可只比版本。
        """
        assert (
            classify_doc_change(
                last_notified_version_id=7,
                last_notified_status="PUBLISHED",
                current_version_id=7,
                current_status="OBSOLETE",
            )
            == DocChangeEvent.OBSOLETED
        )

    def test_同時改版與廢止_以廢止為準(self) -> None:
        """兩次掃描之間既出新版又被廢止：廢止的處置更急迫（課程再發布會被擋）。

        ⛔ 不可改成寄兩封——教師只需要做一件事（移除引用或換一份），
        收到「有新版，去確認測驗題」反而會把他引向錯的動作。
        """
        assert (
            classify_doc_change(
                last_notified_version_id=7,
                last_notified_status="PUBLISHED",
                current_version_id=8,
                current_status="OBSOLETE",
            )
            == DocChangeEvent.OBSOLETED
        )

    def test_完全相同_不寄(self) -> None:
        assert (
            classify_doc_change(
                last_notified_version_id=7,
                last_notified_status="PUBLISHED",
                current_version_id=7,
                current_status="PUBLISHED",
            )
            is None
        )

    def test_已通知過廢止且仍為廢止_不重複寄(self) -> None:
        """廢止是終態（退回只適用 `PENDING_OBSOLETE`，見 `center_service.py:473`）。

        少了這條，已廢止文件會天天寄一封。
        """
        assert (
            classify_doc_change(
                last_notified_version_id=7,
                last_notified_status="OBSOLETE",
                current_version_id=7,
                current_status="OBSOLETE",
            )
            is None
        )

    def test_已通知過廢止_即使版本不同也不再寄(self) -> None:
        """🔴 這條守的是「**不依賴 DM 把廢止文件的版本凍結**」。

        目前 DM 廢止時會保留 `CURRENT_VERSION_ID`（`center_service.py` 檔頭明載），
        所以上一條（版本相同）無論有沒有「已廢止就不再寄」這道判斷都會回 `None`
        ——兩條路同一個結果，變異檢查因此抓不到。實測：拿掉該判斷後上一條**照樣通過**。

        本條把版本改成不同，強迫結果只能由「已廢止就不再寄」那道判斷決定。
        少了它，哪天 DM 改成廢止時也動版本號，已廢止文件就會天天寄一封「有新版」。
        """
        assert (
            classify_doc_change(
                last_notified_version_id=7,
                last_notified_status="OBSOLETE",
                current_version_id=9,
                current_status="OBSOLETE",
            )
            is None
        )

    def test_版本倒退也視為變動(self) -> None:
        """以「不相等」而非「變大」判定。

        正常情況版本只會前進，本條不是為了已知情境而寫——而是選擇**失敗方向**：
        若版本因任何原因倒退，寄一封「有新版」雖不精確，但教師會去看；
        用 `>` 判定則會**靜默不寄**，而那正是本功能要消除的狀態。
        """
        assert (
            classify_doc_change(
                last_notified_version_id=8,
                last_notified_status="PUBLISHED",
                current_version_id=7,
                current_status="PUBLISHED",
            )
            == DocChangeEvent.NEW_VERSION
        )
