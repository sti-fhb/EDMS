"""et_remove_owner_self_enrollment

Revision ID: b4e7c9a1d2f3
Revises: 34da4449e681
Create Date: 2026-10-05 15:00:00.000000

把「課程擁有者在自己課程中」的選課列標為 `IS_REMOVED=true`（#520）。

## 為什麼會有這些列

標籤帶入的母體是「具 `ET_STUDENT` 角色且掛該標籤者」，而該角色於帳號建立時自動授予
（#89）——教師也在母體裡。只要他身上掛著自己課程的標籤，發布的瞬間就把自己加成了
學員。程式面已於本次一併修正（`enrollment/tag_invite.bulk_enroll_returning`），本
migration 清的是在那之前產生的既有資料。

## 兩個後果

1. `is_enrolled` 為真 → `is_preview` 為假 → **預覽對自己的已發布課程失效**
2. **被計入自己課程的完課率分母**，自己沒完課就把該課程的完成率拉低

第 2 項正是 `learning/rules.ensure_can_access` 的 docstring 明文要避開的事。

## 🔴 為何是 `IS_REMOVED=true`，不是 `DELETED=1`、也不是硬刪

| 做法 | 問題 |
|---|---|
| `DELETED=1` | `UQ_ET_ENROLLMENT_USER_COURSE` 是**全表唯一、不分 `DELETED`**。軟刪後 `get_enrollment` 看不到那一列、唯一鍵卻還佔著——日後若要以邀請碼加入，INSERT 會撞約束 |
| 硬刪除 | 違反專案刪除策略，且本情境不需要 |
| **`IS_REMOVED=true`** | ✅ 同時達成兩件事（見下） |

`IS_REMOVED=true` 一次解決兩個後果：

- `stats/repository._completion_base` 有 `EtEnrollment.is_removed.is_(False)` → **移出完課率分母**
- `learning/repository.is_enrolled` 同時要求 `is_removed=false` → **`is_preview` 恢復為真，預覽可用**

⚠️ 此操作**不可逆**：`enrollment/service._guard_not_removed` 會永久擋住已移除者重新
加入。2026-10-05 裁示**沒有「教師加入自己課程」的情境**，故可接受。

## ⚠️ 判準是 `USER_ID = OWNER_ID`，不是「這個人是教師」

教師以邀請碼 / Email 邀請加入**他人**課程是合法的，不在清理範圍。

`JOIN_SOURCE` 也不足以辨識：擁有者多半是 `TAG_DEFAULT` 被帶入，但其他學員同樣是
`TAG_DEFAULT`，而擁有者亦可能有其他歷史路徑。**唯一可靠的判準是兩個 ID 相等。**

## 只打 `IS_REMOVED = false` 的列

已被移除者不再改動——重複執行不會覆蓋 `UPDATED_*`，也不會把別人手動移除的紀錄
算成本次異動。

## downgrade

含資料操作且不可逆，**不實作**（依 `.claude/rules/sti-alembic-rules.md`：若 downgrade
不安全或無意義，留空並加註原因）。

還原需要「哪些列是本 migration 改的」，而 `IS_REMOVED=true` 無法與「教師本人或管理者
手動移除」區分——照 `USER_ID = OWNER_ID` 反向還原會把後者一併改回在籍，那是**製造**
一筆不該存在的資料，比留著不還原更糟。
"""

from collections.abc import Sequence
from typing import Union

from sqlalchemy import text

from alembic import op

revision: str = "b4e7c9a1d2f3"
down_revision: Union[str, None] = "34da4449e681"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: 擁有者在自己課程中的在籍列。
#:
#: ⚠️ `UPDATED_USER` 填 `SYSTEM`——這不是任何人按下的操作，稽核上要看得出是系統批次。
_REMOVE_OWNER_SELF_ENROLLMENT = text(
    'UPDATE "ET_ENROLLMENT" e '
    'SET "IS_REMOVED" = true, '
    '    "UPDATED_USER" = \'SYSTEM\', '
    '    "UPDATED_DATE" = NOW() '
    'FROM "ET_COURSE" c '
    'WHERE e."COURSE_ID" = c."COURSE_ID" '
    '  AND e."USER_ID" = c."OWNER_ID" '
    '  AND e."IS_REMOVED" = false '
    '  AND e."DELETED" = 0'
)

#: 殘留查詢：本 migration 跑完後應為 0。
#:
#: 與 `_REMOVE_OWNER_SELF_ENROLLMENT` 的 `WHERE` 刻意同義——測試以它驗「真的清乾淨了」，
#: 兩者若分岔，測試會對著一個比實際寬鬆的條件回報成功。
LEFTOVER_QUERY = text(
    'SELECT COUNT(*) FROM "ET_ENROLLMENT" e '
    'JOIN "ET_COURSE" c ON e."COURSE_ID" = c."COURSE_ID" '
    'WHERE e."USER_ID" = c."OWNER_ID" '
    '  AND e."IS_REMOVED" = false '
    '  AND e."DELETED" = 0'
)


def upgrade() -> None:
    op.execute(_REMOVE_OWNER_SELF_ENROLLMENT)


def downgrade() -> None:
    # 含資料操作且不可逆，downgrade 不實作（見模組 docstring「downgrade」段）：
    # `IS_REMOVED=true` 無法與「手動移除」區分，反向還原會製造不該存在的在籍列。
    pass
