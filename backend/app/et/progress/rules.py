"""ET05 學習進度之純業務規則（US5 / #274）。

**完全不碰 DB**：覆蓋率、區段聯集、完成判定、解鎖判定都能以純函式表達，故全部以
unit test 涵蓋；integration 只驗接線與寫入。

## 三條覆蓋率規則其實是同一個決定

| 規則 | spec |
|---|---|
| 倍速照算（2 倍速看完全片 = 100%）| FR-ET-US5-07 |
| 直接拉到結尾不算看過 | FR-ET-US5-06 |
| 重複觀看不加成 | FR-ET-US5-06 |

合起來就是：**只計算「播放頭實際走過的影片時間軸範圍」的聯集**。

- **倍速**由前端上報 `currentTime`（影片時間軸）自然滿足——後端不需要知道倍速是多少
- **跳躍**由前端「`seeked` 時先送出跳之前那段、再從新位置重記起點」滿足
- **重複**由本模組的 `merge_segments` 滿足

## ⚠️ 覆蓋率一律先聯集再加總

`data-model` §ET_PROGRESS_INTERVAL 原寫「覆蓋率 = `SUM(END_SEC − START_SEC)`」，
**照字面實作是錯的**：`[0,50]` 看兩次會得到 100%，而學員從未看過後半段。
同一份文件的 §ET_PROGRESS_VIDEO 寫的是「區段**聯集去重後**聚合」——後者才對，
本 issue 一併修正前者的措辭。

推論：`normalize` 只是**儲存壓縮**（減少列數），不是正確性的前提。異常離開沒跑
normalize 時覆蓋率仍然正確（AC 7 因此自然成立）。
"""

from collections.abc import Container, Sequence
from typing import Final, NamedTuple

#: 解鎖門檻（FR-ET-US5-05）。
COVERAGE_THRESHOLD_PCT: Final = 80


class Segment(NamedTuple):
    """一段實際播放過的影片時間軸範圍（秒）。

    `ET_PROGRESS_INTERVAL.START_SEC` / `END_SEC` 為 `INT`，故一律以整數表示；
    浮點的 `currentTime` 於進入本模組前已 `floor`。
    """

    start: int
    end: int


def clamp_segment(segment: Segment, *, duration_sec: int) -> Segment | None:
    """把區段裁切進 `[0, duration_sec]`；完全落在範圍外或長度為零者回 `None`。

    `data-model` 明訂「`END_SEC` 不得超過該影片之 `DURATION_SEC`（應用層裁切，避免
    覆蓋率 > 100%）」。不裁切的話 `COVERAGE_PCT`（`DECIMAL(5,2)`）可能寫入失敗。

    長度為零者不寫入——`END_SEC > START_SEC` 是 `data-model` 的業務規則，且零長度
    區段對覆蓋率沒有貢獻，留著只是雜訊。
    """
    start = max(0, segment.start)
    end = min(duration_sec, segment.end)
    if end <= start:
        return None
    return Segment(start, end)


def merge_segments(segments: list[Segment]) -> tuple[Segment, ...]:
    """區段聯集去重：排序 → 合併重疊與相接。

    **只合併重疊與相接（gap = 0）**。任何正數的「鄰近」門檻都會把未觀看的秒數算進
    覆蓋率——`[0,30]` 與 `[31,60]` 中間那一秒他沒看過，合併就等於送他一秒。
    `data-model` 用「重疊 / 鄰近」的字眼，此處取無損的讀法。
    """
    if not segments:
        return ()
    ordered = sorted(segments)
    merged: list[Segment] = [ordered[0]]
    for current in ordered[1:]:
        last = merged[-1]
        if current.start <= last.end:  # 重疊或相接
            if current.end > last.end:
                merged[-1] = Segment(last.start, current.end)
        else:
            merged.append(current)
    return tuple(merged)


def coverage_pct(segments: list[Segment], *, duration_sec: int) -> int:
    """累計覆蓋率（%，四捨五入至整數）。

    **先聯集再加總**——見模組 docstring。`duration_sec` 非正數時回 0 而非除零：
    理論上影片必有長度（上傳時由 ffprobe 取得），但資料異常不該讓學員的頁面 500。

    上限 100：聯集去重後理論上不可能超過，但區段若未經 `clamp_segment` 就進來
    （例如日後有人繞過），這裡是最後一道。
    """
    if duration_sec <= 0:
        return 0
    watched = sum(seg.end - seg.start for seg in merge_segments(segments))
    return min(100, round(watched * 100 / duration_sec))


def is_video_completed(coverage: int) -> bool:
    """單支影片是否達標（FR-ET-US5-05）。"""
    return coverage >= COVERAGE_THRESHOLD_PCT


def is_material_completed(video_coverages: list[int]) -> bool:
    """含影片之教材是否完成。

    `data-model` §ET_PROGRESS：「該教材**所有未刪除影片**之 `COVERAGE_PCT` 皆 ≥ 80%
    （**缺任一支影片之進度紀錄視為 0%**）」——故呼叫端須為每支影片都給一個值，
    沒有進度紀錄的那支要傳 0，不能只傳有紀錄的那些。

    **沒有影片的教材**（純文件 / 說明文字）不走本函式——那類是「開啟即完成」。
    """
    return all(is_video_completed(c) for c in video_coverages)


def is_item_unlocked(*, previous_completed: bool | None, self_completed: bool) -> bool:
    """章節內的項目是否已解鎖（#274 SA Q2 裁示 A：依序解鎖）。

    Args:
        previous_completed: 同章節內前一項是否完成；`None` 表示本項為該章第一項。
        self_completed: 本項自身是否已完成。

    **已完成者不再上鎖**——依序解鎖擋的只有「還沒學過的」。少了這條，學員完成第 3 項
    之後想回頭複習第 1 項會被自己的進度擋住。

    裁示 A 真正要擋的是「還沒看教材就先點測驗」：`ET_QUIZ.MAX_RETRY` 有重考次數上限，
    讓學員能先點進測驗，會把那個限制變成陷阱。
    """
    if self_completed or previous_completed is None:
        return True
    return previous_completed


class ItemState(NamedTuple):
    """解鎖判定所需的單一項目狀態。

    Attributes:
        completed: 側欄顯示用的「已完成」。
        treat_as_done: 供**解鎖判定**使用的「視為完成」。多數情況等同 `completed`，
            例外只有**現在不可能完成的項目**——擋住那種項目等於永久鎖死。判斷點集中
            在此欄位，見 `build_item_state`。
    """

    item_id: int
    completed: bool
    treat_as_done: bool


def build_item_state(
    item_id: int, *, completed_ids: Container[int], zero_question_quiz_item_ids: Container[int]
) -> ItemState:
    """由完成集合組出 `ItemState`（`spec_us5` AC 12 之判斷點）。

    ⚠️ **讀取路徑（側欄旗標）與寫入路徑（擋下鎖定項目）必須共用本函式**。兩邊各自
    組一份的話，`treat_as_done` 這條規則就有兩個版本——而它們分岔的表現是「側欄顯示
    解鎖但後端擋下」，一個學員完全無法理解、也不會有測試自然抓到的狀態。

    ⭐ 兩個參數都是**必填的 keyword-only**，正是為此：呼叫端漏餵會當場 `TypeError`，
    而不是安靜地算出與另一邊不同的答案。⛔ 不要給它們預設值。

    ## 為何 0 題的測驗不當閘門

    AC 12 於 2026-09-22（#361）啟用——在此之前測驗恆視為通過，理由是「次數用盡即
    永久鎖死且無從補救」；`ET-9`（#329）交付 ET03 重置後該前提消失。

    但重置只解決**次數**用盡。0 題的測驗是另一種死路，重置完全救不了：

    - `attempt/service` 對 0 題測驗直接回 404（建一個零題 attempt 會白吃一次次數），
      學員**連考都考不了**，`IS_COMPLETED` 永遠拿不到
    - ET03 的重置鈕也不會出現——`can_reset_retry` 要求 `used > max_retry`，而他一次
      都用不掉，`used` 恆為 0

    發布檢核有 `BLOCK_QUIZ_NO_QUESTION`，但那是**發布當下**的一次性檢核；發布後教師
    仍可把題目全刪掉（`quiz/service.delete_question` 不擋最後一題）。

    故比照本模組 `locked_item_ids` 對「空章節」的處理——**不擋路**，由發布檢核在上游
    擋住。兩者是同一個形狀：一個現在不可能完成的容器，擋住它只會讓整門課後半段永久
    鎖死，而畫面上完全看不出原因。

    ⛔ 不要改成「擋住並在側欄提示」：教師把題目全刪掉重建的那段時間，全班會卡在一份
    開不起來的考卷前，而他不會知道自己做了這件事。

    Args:
        completed_ids: 該學員已完成的 `ITEM_ID`。
        zero_question_quiz_item_ids: 目前沒有任何未刪除題目之測驗的 `ITEM_ID`
            （由 `learning/repository.zero_question_quiz_item_ids` 查出）。**只含測驗
            項目**，故此處不需再比對 `ITEM_TYPE`。
    """
    completed = item_id in completed_ids
    return ItemState(
        item_id=item_id,
        completed=completed,
        treat_as_done=completed or item_id in zero_question_quiz_item_ids,
    )


def first_blocking_item(chapters: Sequence[Sequence[ItemState]]) -> int | None:
    """課程順序中**第一個未視為完成**的項目；全部完成則 `None`。

    供 ET05 對鎖定項目給出正確提示（`spec_us5` AC 12「阻擋**並提示**」）。AC 12 啟用
    前，鎖定的唯一成因是教材未看完，前端寫死「請先完成本章節之影片學習」即可；啟用後
    多了「測驗未通過」這個成因，同一句話會把學員指向錯的動作——叫他去看早就看完的
    影片，而他真正該做的是重考。

    ## 為何一個值就夠

    解鎖規則是嚴格依序的（章節依序 + 章節內依序），故**所有鎖定都追溯到同一項**——
    它就是學員的學習前緣。而前緣之前的項目全部已完成，所以它自己必然是解鎖的，也就是
    「他現在真的做得到的下一件事」。

    ⛔ 不要改成「擋住該項的緊鄰前一項」：跨章節時那會指向一個**他也還打不開**的項目。
    例：第一章教材沒看完 → 第一章的測驗也鎖著 → 若對第二章的項目提示「請通過本章節
    之測驗」，他點過去只會發現那個也是鎖的，反而更迷惑。

    Args:
        chapters: 已依 `SORT_ORDER` 排序的章節，每章為已排序的項目——與
            `locked_item_ids` 同一份輸入，**順序即規則**。
    """
    for items in chapters:
        for state in items:
            if not state.treat_as_done:
                return state.item_id
    return None


def locked_item_ids(chapters: Sequence[Sequence[ItemState]]) -> frozenset[int]:
    """依「章節依序 + 章節內依序」算出所有**鎖定**的項目（AC 5 / AC 6 + 裁示 Q2=A）。

    兩層規則：

    | 層 | 規則 | 來源 |
    |---|---|---|
    | 章節 | 前一章**所有**項目完成才解鎖下一章 | `spec_us5` AC 9 |
    | 章節內 | 前一項完成才解鎖下一項（依 `SORT_ORDER`）| #274 SA Q2 裁示 A |

    **已完成的項目永不鎖定**——回頭複習照常，依序解鎖擋的只有「還沒學過的」。這條
    優先於章節層：教師事後調整章節順序時，學員已學過的東西不該突然被鎖回去。

    ⚠️ **空章節不擋路**：沒有項目的章節視為已完成（`all([])` 為 `True`）。反過來會讓
    教師建了空章節之後，整門課程的後半段永久鎖死，而畫面上完全看不出原因。

    Args:
        chapters: 已依 `SORT_ORDER` 排序的章節，每章為已排序的項目。**順序即規則**，
            未排序的輸入會算出錯誤結果。

    Returns:
        鎖定項目的 `ITEM_ID` 集合；其餘皆解鎖。
    """
    locked: set[int] = set()
    previous_chapter_done = True
    for items in chapters:
        chapter_unlocked = previous_chapter_done
        previous_done: bool | None = None
        for state in items:
            unlocked = state.completed or (
                chapter_unlocked and is_item_unlocked(previous_completed=previous_done, self_completed=False)
            )
            if not unlocked:
                locked.add(state.item_id)
            previous_done = state.treat_as_done
        previous_chapter_done = all(s.treat_as_done for s in items)
    return frozenset(locked)
