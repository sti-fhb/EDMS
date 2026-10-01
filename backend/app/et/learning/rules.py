"""ET06 章節學習之純業務規則（US5 / #255）。

**完全不碰 DB**：授權判定與倍速限縮都能以純函式表達，故以 unit test 涵蓋；
integration 只驗接線與跨模組取檔。

## 為何本模組與 `material/` 分開

`material/` 是**教師端**的教材編輯（上傳、改名、綁 DM 文件），授權問的是**擁有權**；
本模組是**學員端**的內容取用，授權問的是**在籍**。兩者的授權模型相反，混在同一個
router 遲早有人把 dependency 掛錯層——而那種錯誤的表現是「學員能改教材」或「學員
看不到課程」，都不會在寫測試時自然浮現。
"""

from typing import Final

from app.core.exceptions import AppError

#: 播放器之倍速選項（FR-ET-US5-03）。**固定五段、前端寫死**。
PLAYBACK_RATE_OPTIONS: Final[tuple[float, ...]] = (0.75, 1.0, 1.25, 1.5, 2.0)

_NO_ACCESS = AppError(status_code=403, detail="您尚未加入此課程", error_code="ET_LEARN_002")
_REMOVED = AppError(status_code=403, detail="您已被該課程移除", error_code="ET_LEARN_004")


def ensure_can_access(
    *,
    enrolled: bool,
    is_owner: bool,
    is_course_manager: bool = False,
    course_published: bool = False,
    removed: bool = False,
) -> None:
    """學員端內容之存取判定：**在籍 OR 擁有者 OR 課程管理者預覽已發布課程**。

    影片與 DM 文件是**實體檔案**。少了這道判定，任何登入者（ET 學員角色人人都有）
    知道 `material_id` / `video_id` 就能抓走全站教材——包含他沒有權限看的課程。

    **擁有者亦放行**：教師在 ET05 看到的是編輯視角（上傳欄位、DM 文件下拉），與學員
    實際看到的呈現完全不同；不進 ET06 就無從確認影片能不能播、PDF 內嵌會不會爆版。
    而替代方案（自己加入自己的課）會讓他被計入該課程的完課率分母（US9 AC 22 僅排除
    已移除者），且依 #247 裁示 C，移除自己之後還不能自行加回。

    授權面並未因此擴大——擁有者本來就能在 ET05 看到該課程的全部教材，ET06 對他不多
    給任何一筆資料，只是換一種呈現。

    ## 課程管理者預覽**他人已發布**課程亦放行（#481）

    `spec_us7` 明訂「全部課程」分頁的用途是**供跨教師瀏覽觀摩**，而觀摩要看的是「這門
    課上起來像什麼」，不是編輯欄位長怎樣。

    **授權面同樣不擴大**，理由與上一段完全相同：`material/service.get_detail` 的
    docstring 已載明讀取端**不套擁有者判定**（#358 第 2 項，依 `FR-ET-US7-04` 與 US7
    場景 8「他人建立之課程可唯讀瀏覽」）。教師現在就看得到別人課程的全部教材內容，
    只是透過唯讀編輯頁。本路徑是換一種呈現，不多給任何一筆資料。

    放行的母體刻意與**編輯頁的路由守衛**（`RequireEtCourseManager` ＝ 教師或管理者）
    一致——那正是「現在就讀得到」的那組人。放寬到任一 ET 角色會真的擴大：ET 學員
    角色於帳號建立時自動授予，等同全體登入者。

    ⚠️ **`course_published` 必填**：草稿不在此列。草稿只有擁有者看得到，而那是由
    `structure` 的 `COURSE_DRAFT and owner_id != user_id → 404` 把關（「草稿的存在
    本身是秘密」）。本處是第二道，兩者不可互相取代。

    ⚠️ **給 `ET-5b`**：教師預覽**不得寫入** `ET_PROGRESS` / `_VIDEO` / `_INTERVAL`
    （#255 裁示 Q1 一併載明）。否則教師預覽完就出現在自己課程的完課統計裡，正好是
    本裁示要避開的後果。

    ## `removed` 為何是選填

    「曾加入但被移除」與「從未加入」對學員的意義完全不同：前者需要知道自己**發生了
    什麼事**（ET-MSG-ET07-006），後者只是走錯地方。但這個區別只在 ET06 的入口需要
    （`spec_us6` 場景 28 的 next navigation），其餘四個呼叫點問的都是「能不能拿這份
    資料」——那裡多傳一個參數只會讓每個呼叫點都要去查一次它不需要的東西。

    故預設 `False`：不傳就沿用既有行為，`ET_LEARN_002`。

    Raises:
        AppError: 被移除者 403 `ET_LEARN_004`；其餘兩者皆非 403 `ET_LEARN_002`。
    """
    if enrolled or is_owner:
        return
    # #481：具教師 / 管理者角色者可預覽**已發布**課程（「全部課程」分頁的觀摩入口）。
    # ⚠️ `course_published` 不可省——草稿只有擁有者看得到（`structure` 另有一道 404，
    # 那是「草稿的存在是秘密」；此處是第二道，兩者不可互相取代）。
    if is_course_manager and course_published:
        return
    raise _REMOVED if removed else _NO_ACCESS


def playback_rates(*, max_rate: float) -> tuple[float, ...]:
    """依 `DP_PARAM.ET_VIDEO_PLAYBACK_MAX_RATE` 限縮可選倍速（FR-ET-US5-03）。

    **參數只能往下限縮、不能往上新增選項**——選項清單為固定五段，設 3 不會多出 3x。
    這是 DP #171 將該參數列為不可編輯的理由；#459 起進一步改為 `HIDDEN`、不出現於 DP03。

    ⚠️ 不要改成動態產生（`range` / 等差數列）：那樣參數設 3 就會冒出一個播放器根本
    沒有的選項，而且沒有任何測試會自然抓到——寫測試的人會用預設值 2。

    上限低於最小選項時仍保留最慢的一段：那是設定錯誤，但不該讓播放器一個倍速都不能
    選（等於壞掉）。
    """
    allowed = tuple(rate for rate in PLAYBACK_RATE_OPTIONS if rate <= max_rate)
    return allowed or PLAYBACK_RATE_OPTIONS[:1]
