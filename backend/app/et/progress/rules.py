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
