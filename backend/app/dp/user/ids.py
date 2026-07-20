"""DP_USER 識別碼產生（US2 自助註冊 / US4 代建共用）。

DP_USER.USER_ID 為系統產生、永久不變之識別碼（VARCHAR(20)），ET / DM 各表 FK 一律指向此。
EMAIL 才是登入帳號（另有 UNIQUE）；USER_ID 僅為內部主鍵，故採不可預測的隨機短碼即可，
無需可讀序號。US2 與 US4 一律呼叫本函式，確保兩路徑產生規則一致。
"""

import uuid


def generate_user_id() -> str:
    """產生 20 字元的隨機 USER_ID（uuid4 hex 取前 20 碼，80 bits 不重複性足夠）。"""
    return uuid.uuid4().hex[:20]
