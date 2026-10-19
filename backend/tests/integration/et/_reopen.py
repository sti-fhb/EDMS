"""測試捷徑：以新的起訖時間「更新並重開課」（#720）。

## 為什麼需要它

`POST /courses/{id}/reopen` 自 #720 起**沒有 request body**。新的起訖時間是基本資料的
一部分、寫在暫存區，由 reopen 連同其餘編輯一起套用——留在 body 裡會變成「檢核一組、
套用另一組」，而那正是 #720 要消滅的「檢核通過但生效後不合格」。

⇒ 教師的實際操作變成兩步：在基本資料卡填新起訖（`PUT /courses/{id}`，進暫存）→ 按
「更新並重開課」。本工具把那兩步包起來，讓 21 處呼叫點不必各自重寫一遍。

## ⛔ 不要用它來測 reopen 的檢核

本工具會**先把起訖寫進暫存**，所以用它寫出來的測試對「沒設新起訖就按再開課」
（`ET_COURSE_008`）沒有任何覆蓋。那條路徑要直接 `client.post(.../reopen)`，不經本工具。
"""

from typing import Any

from tests.integration.et._tag_pairs import audiences_req

_COURSES = "/api/et/courses"


async def stage_schedule(client, headers: dict[str, str], course_id: int, *, start: str, end: str) -> None:
    """把新起訖寫進暫存（`PUT /courses/{id}` 是全量覆寫，故其餘欄位原樣回送）。

    ⚠️ `version` 取自**詳細頁**而非呼叫端手上的值：已發布 / 已關閉課程的詳細頁回的是
    暫存節點的版本（#720），而活表的版本在暫存開始之後就不再遞增——拿活表那個必然 409。
    """
    detail = (await client.get(f"{_COURSES}/{course_id}", headers=headers)).json()
    r = await client.put(
        f"{_COURSES}/{course_id}",
        json={
            "course_name": detail["course_name"],
            "description": detail["description"],
            "require_approval": detail["require_approval"],
            "audiences": audiences_req(detail),
            "open_start_at": start,
            "open_end_at": end,
            "version": detail["version"],
        },
        headers=headers,
    )
    assert r.status_code == 204, f"前置失敗（寫入新起訖）：{r.text}"


async def reopen_with_schedule(client, headers: dict[str, str], course_id: int, *, start: str, end: str) -> Any:
    """填新起訖 → 按「更新並重開課」。回傳 reopen 的回應供呼叫端斷言。"""
    await stage_schedule(client, headers, course_id, start=start, end=end)
    return await client.post(f"{_COURSES}/{course_id}/reopen", headers=headers)
