// 本檔自 CourseEditorPage.test.tsx 拆出（#682）：原檔 2344 行，整組跑時檔內測試互相排擠
// 到超過 5 秒 timeout。本檔負責：課程關閉與再開課。檔頭的 router mock（含 useBlocker）與 helper
// 各檔各自完整一份，不依賴其他檔的執行順序。

import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import dayjs from "dayjs"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, onTestFinished, vi } from "vitest"

import { EtCourseEditorPage } from "./CourseEditorPage"
import { coursesApi } from "./coursesService"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

// useParams 可變（切換新增 / 編輯模式）；比照 DM `DmEditorPage.test.tsx`
// ——`renderWithProviders` 內建之 MemoryRouter 無法指定 initialEntries。
const { navigateSpy, paramsRef, locationRef, blockerRef } = vi.hoisted(() => ({
  navigateSpy: vi.fn(),
  paramsRef: { current: {} as Record<string, string | undefined> },
  // 自動存草稿（#335）跨了元件重新掛載——待開啟的項目由 navigate 的 state 帶過去，
  // 故 useLocation 也須可控。
  locationRef: { current: { pathname: "/et/courses/new", state: null } as { pathname: string; state: unknown } },
  // 🔴 **離開攔截改成可控**（#763）。原本固定回 `unblocked`，於是那個確認視窗的文案
  // **從來沒有任何測試覆蓋**——而 #763 的第 ② 條正是「那句文案在某個分支是假的、
  // 沒人發現」。寫死成永不攔截等於把它放進結構性的盲區。
  blockerRef: {
    current: { state: "unblocked", proceed: vi.fn(), reset: vi.fn() } as {
      state: string
      proceed: () => void
      reset: () => void
    },
  },
}))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => paramsRef.current,
    useLocation: () => locationRef.current,
    // 離開攔截（#631）需要 data router，`renderWithProviders` 內建的是 MemoryRouter
    // ——真的 `useBlocker` 在此會拋錯，故以 `blockerRef` 取代。
    //
    // ⚠️ 預設仍是 `unblocked`（其餘測試不受影響）；要驗那個確認視窗的測試自己把
    // `blockerRef.current.state` 設成 `"blocked"`。
    useBlocker: () => blockerRef.current,
  }
})

/** 編輯模式：帶 courseId 路由參數。 */
function renderEditor(courseId = "1") {
  paramsRef.current = { courseId }
  return renderWithProviders(<EtCourseEditorPage />)
}

beforeEach(() => {
  navigateSpy.mockClear()
  blockerRef.current = { state: "unblocked", proceed: vi.fn(), reset: vi.fn() }
  locationRef.current = { pathname: "/et/courses/new", state: null }
})

// ── ET05 關閉與再開課（US11 / #288）──────────────────────────────────────────

/**
 * 以指定狀態與擁有權覆蓋課程詳細——關閉 / 再開課按鈕全由這兩者決定。
 *
 * `pending` 對應後端的 `has_pending_changes`（#631）：有尚未按下「更新」的內容編輯。
 */
function useCourse(
  status: string,
  {
    isOwner = true,
    pending = false,
    // ⚠️ 預設由 `status` 推導只是**fixture 的方便**，不代表正式環境可以這樣推。
    // 期間已過的課程 `status` 仍是 `PUBLISHED` 而 `is_closed` 為真（#720）——要測那種
    // 課程就明確傳 `{ isClosed: true }`，⛔ 不要改成讓元件自己從 `status` 算。
    isClosed = status === "CLOSED",
    // ⚠️ #720 之後起訖**不再被模式清空**，所以「欄位空著」這個狀態只能由 fixture 造
    // （等同教師自己把它清掉）。
    schedule = true,
    //: 教師按過「保留編輯」（#763）——只影響離開提示的文案。
    kept = false,
  }: {
    isOwner?: boolean
    pending?: boolean
    isClosed?: boolean
    schedule?: boolean
    kept?: boolean
  } = {},
) {
  server.use(
    http.get("/api/et/courses/:courseId", () =>
      HttpResponse.json({
        course_id: 1,
        course_name: "採血作業訓練",
        description: null,
        status,
        open_start_at: schedule ? "2026-09-01T00:00:00Z" : null,
        open_end_at: schedule ? "2027-09-30T00:00:00Z" : null,
        require_approval: false,
        version: 5,
        owner_id: "U1",
        owner_name: "王教師",
        is_owner: isOwner,
        audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
        chapters: [],
        invitation_code: isOwner ? "01234567" : null,
        has_pending_changes: pending,
        is_closed: isClosed,
        has_kept_edits: kept,
      }),
    ),
  )
}

/**
 * `useCourse` 起始時間（`2026-09-01T00:00:00Z`）在選擇器上的顯示值——**依本機時區計算**。
 *
 * 測試不固定時區（本機台灣、CI 為 UTC）；寫死 `2026/09/01` 在 UTC-5 以西會變成 `08/31`
 * （#564 code review MEDIUM）。
 */
const FIXTURE_START_SHOWN = dayjs("2026-09-01T00:00:00Z").format("YYYY/MM/DD HH:mm")

/** `POST /reopen` 的成功回應——內容與本頁無關（欄位由送出的 payload 決定），只需 200。 */
const reopened = {
  course_id: 1,
  status: "PUBLISHED",
  open_start_at: "2027-11-01T01:00:00Z",
  open_end_at: "2027-12-31T09:00:00Z",
  closed_at: null,
  version: 6,
}

/** 讓 `POST /reopen` 回 422 `ET_PUBLISH_001` 並帶一條缺漏。 */
function useReopenBlocked(code: string, message: string) {
  server.use(
    http.post("/api/et/courses/:courseId/reopen", () =>
      HttpResponse.json(
        {
          error_code: "ET_PUBLISH_001",
          error_message: "課程不符發布條件",
          blockers: [{ code, message, target_id: null }],
        },
        { status: 422 },
      ),
    ),
  )
}

/**
 * 以鍵盤填 `DateTimePicker`。
 *
 * ⚠️ 不是點日曆——MUI 的欄位由五個 section 組成（YYYY/MM/DD HH:mm，24 小時制，#564），逐段
 * 接收按鍵並**自動跳下一段**，故 `keys` 一路打完即可（`"202711010900"` = 2027-11-01 09:00）。
 * ⛔ 不要插 `{ArrowRight}` 跳段，會多跳一格、時分錯位而仍組成一個合法日期（看起來只是
 * 「值不對」，很難連到跳段上）。
 *
 * ⚠️ 必須點在 section 上，點外層的 `role="group"` 不會讓任何一段取得焦點，打的字全部
 * 落空而**測試照樣往下跑**。
 */
async function fillDateTime(label: RegExp, keys: string) {
  // ⚠️ `findAll` 而非 `getAll`：#720 拿掉再開課模式之後，呼叫端不再需要先點一顆「再開課」
  // ——而那一下順便扮演了「等課程載入」。少了它，`getAll` 會在資料回來前就落空，測試在
  // 48ms 當場炸掉、錯誤訊息指向「找不到欄位」而與它要驗的事無關。
  const fields = await screen.findAllByLabelText(label)
  const field = fields.find((el) => el.getAttribute("role") === "group")
  if (!field) throw new Error(`找不到日期時間欄位：${label}`)
  const first = field.querySelector<HTMLElement>(".MuiPickersSectionList-section")
  if (!first) throw new Error(`欄位沒有可輸入的區段：${label}`)
  // ⚠️ 自備 `delay: null` 的 typist，不沿用測試的 `user`。一次填值是 12 個按鍵、兩個
  // 欄位就 24 個，照預設每鍵 await 一輪會讓單條測試逼近 5s 的預設 timeout——實測本檔
  // 最慢的一條在**單檔**跑就已經 4.5s，全套件並行時必爆（2026-09-24）。
  const typist = userEvent.setup({ delay: null })
  await typist.click(first)
  await typist.keyboard(keys)
}

/**
 * 「填兩次 `DateTimePicker` → 送出 / 開關對話框」測試的個別 timeout（#687）。
 *
 * ⚠️ **#720 之後適用的條數變多了**，而且原因不是負載：拿掉再開課模式之後，欄位帶著
 * 舊值進場，`fillDateTime` 從「對空欄位打 12 鍵」變成「覆寫既有值 12 鍵」——每一鍵都
 * 多一次既有 section 的重繪。原本剛好塞得進 5 秒的幾條因此擠不下，典型是
 * `再開課的時間不合規時擋在前端`（整組跑 5.0s 逾時、單檔跑綠）。
 *
 * ⛔ 判準仍是「它和已套用的那幾條做一樣多的事」，不是「它紅了就給」。
 *
 * - **成本來源**：兩個日期時間欄位各 12 鍵（MUI 每鍵重繪一次 section），加上再開課對話框、
 *   發布視窗的開關與切換課程的重新渲染。套用的 5 條單檔、機器閒置（當下無其他測試行程）實測
 *   （2026-10-19）：全程不發出一般更新 3735ms、殘留到下一次 3486ms、再開課留下的缺漏 3321ms、
 *   發布視窗留下的缺漏 2991ms、送出中停用 2666ms——離預設 5 秒只剩 1.3～2.3 秒；整組並行時
 *   其中 4 條實測 5.2～5.8 秒逾時（#682 驗收）。
 * - **為何不降成本**：`fillDateTime` 已用 `delay: null`。試過把整條測試的 userEvent 也改成
 *   `delay: null`，差異落在量測雜訊內——主要成本是元件重繪，不是按鍵之間的等待。
 * - ⛔ **只給下列幾條，不調全域 `testTimeout`**：全域放寬會讓真正卡住的測試要更久才失敗。
 * - ⚠️ 這個值只修掉「閒置時就逼近上限」。負載一來照樣可能紅，那是 worker 排不到 CPU，依
 *   `.claude/rules/sti-testing.md`「前端『假紅』判定」處理，**不要再往上調**。
 */
const REOPEN_FLOW_TIMEOUT = 15_000

describe("ET05 課程關閉與再開課", () => {
  // ℹ️ #836 移除了編輯頁常駐的邀請碼橫幅，原本釘在這裡的 #359 第 2 項守門隨之搬家：
  // 「編輯頁的邀請碼不帶『發布後永久不可變更』的括號說明」改在
  // `CourseEditorPage.inviteCodeBanner.test.tsx` 對「邀請學員」視窗驗——邀請碼現在只在
  // 那裡顯示，會有人補上那句說明的也是那裡。發布當下的結果視窗另有 `PublishDialog.test.tsx`。

  it("已發布課程顯示「關閉課程」，不顯示「再開課」", async () => {
    useCourse("PUBLISHED")
    renderEditor()
    expect(await screen.findByRole("button", { name: "關閉課程" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "再開課" })).not.toBeInTheDocument()
  })

  it("已關閉課程的動作列是「取消｜保留編輯｜更新並重開課」（#720）", async () => {
    // AC 5 / FR-ET-US11-07：關閉期間不可邀請學員，故按鈕一併收起（後端另以
    // ET_INVITE_004 把關）。
    //
    // 🔴 #720：再開課不再是標頭上一顆「先進入模式」的鈕，而是底部動作列的
    // 「更新並重開課」——教師改完起訖直接按它。
    useCourse("CLOSED")
    renderEditor()

    expect(await screen.findByRole("button", { name: "更新並重開課" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "保留編輯" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "再開課" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "關閉課程" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "邀請學員" })).not.toBeInTheDocument()
  })

  it("🔴 已關閉課程沒有獨立的「儲存」鈕（#720）", async () => {
    // 2026-10-19 手測回報的第一個 bug：那顆「儲存」寫的是基本資料、而且**存了就生效**
    // ——教師以為自己只是存個草稿，學員當場就看到了。基本資料現在隨教師按的那顆鈕
    // 一起送（`stageBasic`）。⛔ 不要為了「總該有個儲存吧」而加回來。
    useCourse("CLOSED")
    renderEditor()
    await screen.findByRole("button", { name: "更新並重開課" })

    expect(screen.queryByRole("button", { name: "儲存" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "儲存草稿" })).not.toBeInTheDocument()
  })

  it("🔴 已發布（運作中）課程沒有「保留編輯」（#720）", async () => {
    // 已發布的內容隨時對學員生效，多一個「留著不發」的狀態會讓教師以為自己已經處理
    // 完了。後端對運作中的課程回 409 `ET_COURSE_011`，前端也不該顯示這顆。
    //
    // 正向錨點：少了這條，把「保留編輯」寫成無條件顯示也會讓上面兩條通過。
    useCourse("PUBLISHED")
    renderEditor()
    await screen.findByRole("button", { name: "更新" })

    expect(screen.queryByRole("button", { name: "保留編輯" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "更新並重開課" })).not.toBeInTheDocument()
  })

  it("🔴 期間已過（is_closed 為真）的已發布課程走已關閉那一排（#720）", async () => {
    // 🥇 **判準是 `is_closed` 而非 `status`。**
    //
    // 期間已過時 `status` 仍是 `PUBLISHED`（到期自動轉 `CLOSED` 由後端 SCHET002 每日
    // 08:00 執行，每門課到期後都必經這個窗口，**不是邊角**）。前端若自己判 `status`，
    // 這門課會拿到一排錯的按鈕：
    // 教師按下「更新」，而後端走的是另一條路。
    useCourse("PUBLISHED", { isClosed: true })
    renderEditor()

    expect(await screen.findByRole("button", { name: "更新並重開課" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "保留編輯" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "更新" })).not.toBeInTheDocument()
  })

  it("🔴 期間已過的已發布課程，標題列不顯示「邀請學員」與「關閉課程」（#763）", async () => {
    // ## 這條是 #720 留下的不一致
    //
    // #762 把 `FR-ET-US11-01` 改成「僅於已發布**且尚在開放期間內**時顯示」，但那兩顆鈕
    // 的程式仍只判 `status === "PUBLISHED"`——而期間已過的課程狀態正是 `PUBLISHED`
    //（到期自動轉 `CLOSED` 由後端 SCHET002 每日 08:00 執行，每門課必經這個窗口）。
    //
    // 危害：
    // - **邀請學員**按下去會被後端以 `ET_INVITE_002 / 004` 擋掉（關閉期間不可邀請）
    //   ——看得到、按了失敗，是最糟的一種 UX
    // - **關閉課程**對一門已經視同關閉的課程再按，語意空洞
    //
    // ⛔ 判準必須與底部動作列**同一個來源**（`course.is_closed`）。#720 的 🔴 死局
    // 就是前後端各自判 `status` 造成的，不要在同一頁裡再製造一次。
    useCourse("PUBLISHED", { isClosed: true })
    renderEditor()
    await screen.findByRole("button", { name: "更新並重開課" })

    expect(screen.queryByRole("button", { name: "邀請學員" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "關閉課程" })).not.toBeInTheDocument()
  })

  it("運作中的已發布課程仍顯示「邀請學員」與「關閉課程」（#763 正向錨點）", async () => {
    // 少了這條，把那兩顆鈕整個拿掉也會讓上一條通過——而那會讓教師再也邀請不了學員、
    // 也關不了課。
    useCourse("PUBLISHED", { isClosed: false })
    renderEditor()

    expect(await screen.findByRole("button", { name: "邀請學員" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "關閉課程" })).toBeInTheDocument()
  })

  describe("離開提示的文案（#763 ②）", () => {
    // ## 為什麼這組測試到現在才有
    //
    // 離開攔截原本在本檔被 mock 成「永不攔截」，理由寫著「站內離開的攔截屬 e2e 行為」
    // ——那對**攔不攔得到**成立，但連帶讓那個視窗的**文案**也沒有任何覆蓋。
    //
    // 而 #763 ② 正是文案在某個分支是假的、靠人讀程式才發現。⇒ 攔截行為仍不在單元測試
    // 的範圍，但「攔到之後說什麼」要有守門。

    // ⚠️ 不在這裡呼叫 `useCourse`：ESLint 的 `rules-of-hooks` 看到 `use` 開頭就當成
    // React Hook，而具名的一般函式不是元件也不是 Hook——會報 error。fixture 由各條
    // 測試自己設好再進來。
    async function blockedLeaveDialog() {
      blockerRef.current = { state: "blocked", proceed: vi.fn(), reset: vi.fn() }
      renderEditor()
      return screen.findByRole("dialog")
    }

    it("🔴 已按過「保留編輯」時，不得說「離開後都會放棄」", async () => {
      // 旗標一旦設上就留到「更新」或「取消」，`discardUnkeptStage` 對它是 no-op
      // ——所以對這門課說「都會放棄」是假的。2026-10-20 裁示採文案分流。
      useCourse("CLOSED", { pending: true, kept: true })
      const dialog = await blockedLeaveDialog()

      expect(within(dialog).getByText(/離開後編輯仍會保留/)).toBeInTheDocument()
      expect(within(dialog).getByText(/會留到下次進來/)).toBeInTheDocument()
      expect(within(dialog).queryByText(/都會放棄/)).not.toBeInTheDocument()
      expect(within(dialog).getByRole("button", { name: "離開" })).toBeInTheDocument()
    })

    it("未按過「保留編輯」時，維持「離開將放棄本次的編輯」（正向錨點）", async () => {
      // 少了這條，把文案一律改成「會保留」也會讓上一條通過——而那會讓教師放心關掉
      // 分頁，然後編輯真的不見了。
      useCourse("CLOSED", { pending: true, kept: false })
      const dialog = await blockedLeaveDialog()

      expect(within(dialog).getByText(/離開將放棄本次的編輯/)).toBeInTheDocument()
      expect(within(dialog).getByText(/都會放棄/)).toBeInTheDocument()
      expect(within(dialog).getByRole("button", { name: "放棄並離開" })).toBeInTheDocument()
    })
  })

  it("已關閉提示明確寫出「課程內容仍可編輯」（AC 6）", async () => {
    // 少了這句，教師會以為關閉後這頁是唯讀的而不敢改——AC 6 的整個用意就是讓他能在
    // 關閉期間整理教材再開課。
    useCourse("CLOSED")
    renderEditor()
    expect(await screen.findByText(/此課程已關閉/)).toBeInTheDocument()
    expect(screen.getByText(/課程內容仍可編輯/)).toBeInTheDocument()
  })

  it("草稿不顯示關閉 / 重開課（草稿沒有學員也沒有邀請碼，關閉沒有語意）", async () => {
    useCourse("DRAFT")
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    expect(screen.queryByRole("button", { name: "關閉課程" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "更新並重開課" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "保留編輯" })).not.toBeInTheDocument()
  })

  // #698：編輯頁不提供預覽——預覽只從 ET01「全部課程」卡片進入。編輯頁的預覽以「已儲存」
  // 資料呈現，教師改了基本資料未存就按下去，導離本頁後未儲存的內容直接遺失。
  // ⚠️ 取捨（使用者裁示接受）：自己的草稿／已關閉／已過期課程因此沒有預覽入口。
  it.each(["DRAFT", "PUBLISHED", "CLOSED"] as const)("%s 課程的編輯頁不顯示「預覽課程」（#698）", async (status) => {
    useCourse(status)
    renderEditor()
    // 正向錨點：頁面已載入、動作列已出現——否則下面的否定斷言在載入中也成立
    expect(await screen.findByRole("button", { name: "取消" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /預覽課程/ })).not.toBeInTheDocument()
  })

  it("非擁有者（檢視模式）不顯示關閉 / 重開課", async () => {
    useCourse("PUBLISHED", { isOwner: false })
    renderEditor()
    await screen.findByText(/檢視模式/)
    expect(screen.queryByRole("button", { name: "關閉課程" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "更新並重開課" })).not.toBeInTheDocument()
  })

  it("關閉前先確認，且確認內容說明學員仍可唯讀回看與可再開課", async () => {
    // 關閉會立刻影響所有在籍學員。可逆這件事也要說，否則教師會誤以為這是不可回復的
    // 動作而不敢按。
    const user = userEvent.setup()
    useCourse("PUBLISHED")
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "關閉課程" }))

    expect(await screen.findByText(/已加入的學員仍可唯讀回看內容與成績/)).toBeInTheDocument()
    expect(screen.getByText(/課程內容於關閉期間仍可編輯，之後可再開課/)).toBeInTheDocument()
  })

  it("確認關閉時送出當前版本（樂觀鎖）", async () => {
    const user = userEvent.setup()
    let body: unknown
    useCourse("PUBLISHED")
    server.use(
      http.post("/api/et/courses/:courseId/close", async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({
          course_id: 1,
          status: "CLOSED",
          open_start_at: "2026-09-01T00:00:00Z",
          open_end_at: "2027-09-30T00:00:00Z",
          closed_at: "2026-09-09T03:00:00Z",
          version: 6,
        })
      }),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "關閉課程" }))
    await user.click(await screen.findByRole("button", { name: "確認關閉" }))

    await waitFor(() => expect(body).toEqual({ version: 5 }))
    // #814 B7：原本只有「課程已關閉」——只講物件、不講後果。補成帶後果的版本後，
    // 這裡的**完全比對**會失效，故一併更新。
    expect(await screen.findByText("課程已關閉，學員已無法加入")).toBeInTheDocument()
  })

  it("關閉遇版本衝突時顯示衝突視窗而非成功訊息", async () => {
    const user = userEvent.setup()
    useCourse("PUBLISHED")
    server.use(
      http.post("/api/et/courses/:courseId/close", () =>
        HttpResponse.json(
          { error_code: "ET_LOCK_001", error_message: "資料已被其他人修改" },
          { status: 409 },
        ),
      ),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "關閉課程" }))
    await user.click(await screen.findByRole("button", { name: "確認關閉" }))

    expect(await screen.findByText("內容已被其他裝置變更，請重新整理後再儲存。")).toBeInTheDocument()
    // ⚠️ #814 B7 改字後，這個否定斷言若維持 `"課程已關閉"` 會**永遠成立**（畫面上
    // 根本不存在那個完全相符的字串），變成恆真的假守門。改為比對新字串。
    expect(screen.queryByText("課程已關閉，學員已無法加入")).not.toBeInTheDocument()
  })

  // #428：再開課改為**就地清空編輯頁的起訖時間**，不再跳對話框。
  it("🔴 進入已關閉課程不清空起訖時間（#720 推翻 #428 的就地編輯模式）", async () => {
    // ## 這條是前兩條測試的**反向替身**
    //
    // #428 的設計是：按「再開課」進入一個模式，模式會把起訖**清空**並標紅框，逼教師
    // 重新設定；反悔則按「取消再開課」還原。原本有兩條測試釘住那個行為。
    //
    // #720 把模式整個拿掉（2026-10-19 裁示）：起訖就是基本資料卡上那兩格，教師改完
    // 直接按「更新並重開課」。所以「清空」與「還原」兩條都不再適用，改由本條釘住
    // **相反的**事：值要原樣留著。
    //
    // ⚠️ 少了本條，哪天有人把清空邏輯加回來不會有任何測試變紅——而那會讓教師一進頁
    // 就看到自己的起訖不見了，卻沒有「取消再開課」可按（那顆鈕也不存在了）。
    //
    // ℹ️ 「強制重新設定」改由後端承擔（2026-10-20 裁示）：期間已過時起訖仍是舊值，
    // 按下去會回 `ET_COURSE_008` 要教師先改。
    useCourse("CLOSED")
    renderEditor()

    expect(await screen.findByDisplayValue(FIXTURE_START_SHOWN)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "取消再開課" })).not.toBeInTheDocument()
    expect(screen.queryByText(/按「取消再開課」即可還原/)).not.toBeInTheDocument()
  })

  it("起訖留空時按「更新並重開課」會逐欄標示必填（#428 / #720）", async () => {
    let called = 0
    server.use(
      http.post("/api/et/courses/:courseId/reopen", () => {
        called += 1
        return HttpResponse.json(reopened)
      }),
    )
    const user = userEvent.setup()
    // ⚠️ `schedule: false` 造出「欄位空著」。#720 拿掉模式之後沒有任何東西會清空它們，
    // 所以這個狀態只能由 fixture 造（等同教師自己把兩欄都清掉）。
    useCourse("CLOSED", { schedule: false })
    renderEditor()

    await user.click(await screen.findByRole("button", { name: "更新並重開課" }))

    // #558：先在視窗列出，關閉後才逐欄出現訊息
    const dialog = await screen.findByRole("dialog", { name: "更新並重開課" })
    expect(within(dialog).getByText("請重新設定課程起始時間")).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "關閉" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.getByText("請重新設定課程起始時間")).toBeInTheDocument()
    expect(screen.getByText("請重新設定課程訖止時間")).toBeInTheDocument()
    // ⚠️ 顯式斷言而非靠「兩欄皆空時 `startAt!.toISOString()` 會自己拋例外」這個副作用——
    // 那是巧合式的保護（下一條測試的註解記著同一個教訓）。
    expect(called).toBe(0)
  })

  it("再開課的時間不合規時擋在前端，不送出請求（#428）", async () => {
    // ⚠️ 這裡刻意用「訖止早於起始」而非空白欄位。空白時 `startAt!.toISOString()` 會自己
    // 拋 TypeError，請求同樣沒發出去——斷言 `called === 0` 於是**在沒有那道 guard 的情況
    // 下照樣成立**（2026-09-24 變異檢查實測）。兩個欄位都有值才驗得到是 guard 擋下的。
    let called = 0
    server.use(
      http.post("/api/et/courses/:courseId/reopen", () => {
        called += 1
        return HttpResponse.json(reopened)
      }),
    )
    const user = userEvent.setup()
    useCourse("CLOSED")
    renderEditor()
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202711010800")

    await user.click(screen.getByRole("button", { name: "更新並重開課" }))

    const dialog = await screen.findByRole("dialog", { name: "更新並重開課" })
    expect(within(dialog).getByText("課程訖止時間須晚於起始時間")).toBeInTheDocument()
    expect(called).toBe(0)
    await user.click(within(dialog).getByRole("button", { name: "關閉" }))
    // 仍停在再開課模式，教師可以就地改；訊息改掛在欄位下
    expect(await screen.findByRole("button", { name: "更新並重開課" })).toBeInTheDocument()
    expect(screen.getByText("課程訖止時間須晚於起始時間")).toBeInTheDocument()
  }, REOPEN_FLOW_TIMEOUT)

  it("🥇 「更新並重開課」先把起訖寫進暫存，再呼叫沒有 body 的 reopen（#720）", async () => {
    // ## 這條取代了兩條方向相反的舊測試
    //
    // 舊的是「再開課模式全程**不發出**一般的課程更新」與「再開課送出的 body 只有三個
    // 欄位」。#720 之後兩者都反過來：
    //
    // | | #428（舊）| #720（現在）|
    // |---|---|---|
    // | 起訖怎麼送 | reopen 的 request body | `PUT /courses/{id}` → 暫存區 |
    // | 一般更新 | ⛔ 全程不得發出 | ✅ **必須**發出，它是第一步 |
    // | reopen 的 body | 三個欄位 | **沒有 body** |
    //
    // 🔴 **為什麼非這樣不可**：後端的 `ensure_reopen_schedule` 讀的是**暫存值**。前端若
    // 另把起訖塞進 reopen 的 body，就成了「檢核一組、套用另一組」——而那正是 #720 要
    // 消滅的「檢核通過但生效後不合格」。
    //
    // ⚠️ 對應的後端測試是 `TestReopen::test_夾帶的起訖不得被採信`，兩者是同一份契約的
    // 兩端，改動任一邊請同步。
    let putBody: Record<string, unknown> | undefined
    let reopenBody: unknown = "未呼叫"
    server.use(
      http.put("/api/et/courses/:courseId", async ({ request }) => {
        putBody = (await request.json()) as Record<string, unknown>
        return new HttpResponse(null, { status: 204 })
      }),
      http.post("/api/et/courses/:courseId/reopen", async ({ request }) => {
        reopenBody = await request.text()
        return HttpResponse.json(reopened)
      }),
    )
    const user = userEvent.setup()
    useCourse("CLOSED")
    renderEditor()
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")

    await user.click(await screen.findByRole("button", { name: "更新並重開課" }))

    await waitFor(() => expect(putBody).toBeDefined())
    // #564：只改顯示格式，送出的仍是同一個瞬間的 ISO 值。預期值以**本機時區**解讀——測試
    // 不固定時區（本機台灣、CI 為 UTC），寫死字串會一邊綠一邊紅（#483）
    expect(putBody?.open_start_at).toBe(dayjs("2027-11-01T09:00").toISOString())
    expect(putBody?.open_end_at).toBe(dayjs("2027-12-31T17:00").toISOString())
    // 🔴 空字串 ＝ 真的沒送 body。⛔ 不要放寬成「body 裡沒有 open_end_at」——那會讓
    // 「送了一個只有 version 的 body」也通過，而那同樣是第二個事實來源。
    await waitFor(() => expect(reopenBody).toBe(""))
  }, REOPEN_FLOW_TIMEOUT)

  it("🥇 更新並重開課成功後先出結果視窗，關掉才回課程列表（#720）", async () => {
    // ## 兩件事，缺一不可
    //
    // 1. **結果視窗**（AC：顯示帶入人數與邀請碼）。這一下會讓一批學員進到課程裡，而
    //    邀請碼是教師可能從未抄下來過的東西（#247）——toast 幾秒就消失，抄不及。
    // 2. **關掉才導走**（2026-10-19 裁示：所有成功動作一律回列表）。先導走就等於沒有
    //    視窗；而留在原地會讓教師分不出「我按過了」與「我還沒按」。
    //
    // ⚠️ 先斷言「此刻還沒導走」是本條的承重點：少了它，把 `navigate` 寫在 `onSuccess`
    // 裡（視窗一閃而過）也會讓後半段通過。
    //
    // ⚠️ 這條同時取代了舊的「再開課成功後畫面立即顯示新的起訖時間（#428 迴歸）」：
    // 那條驗的是**留在原地時**欄位有沒有跟著更新，而現在不留在原地了。
    const user = userEvent.setup()
    useCourse("CLOSED")
    server.use(
      http.put("/api/et/courses/:courseId", () => new HttpResponse(null, { status: 204 })),
      http.post("/api/et/courses/:courseId/reopen", () =>
        HttpResponse.json({ ...reopened, invited_count: 3, invitation_code: "01234567" }),
      ),
    )
    renderEditor()
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")

    await user.click(await screen.findByRole("button", { name: "更新並重開課" }))

    const dialog = await screen.findByRole("dialog", { name: "課程已重新開課" })
    expect(within(dialog).getByText(/已依受訓對象帶入 3 位學員/)).toBeInTheDocument()
    expect(within(dialog).getByText("01234567")).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalledWith("/et/courses")

    await user.click(within(dialog).getByRole("button", { name: "關閉" }))

    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith("/et/courses"))
  }, REOPEN_FLOW_TIMEOUT)

  it("🔴 重開課帶入 0 人時，不得宣稱「沒有任何學員符合受訓對象」（#763）", async () => {
    // ## 發布與重開課的 0，意思不一樣
    //
    // | | `invited_count == 0` 的意思 |
    // |---|---|
    // | 發布 | 真的沒人符合受訓對象——設定問題，要提醒教師去查 |
    // | **重開課** | **通常是符合的人早就在課程裡了**（`bulk_enroll_returning` 只回傳本次新加入者）|
    //
    // #762 把結果摘要抽成共用元件，理由是「兩份各自寫會漂移」——**版面共用是對的，
    // 但這一句的語意本來就不同**。照抄發布的說法，會讓教師去查一個不存在的設定問題。
    //
    // ⛔ 修法不是把元件拆回兩份，是讓 0 人的說法由呼叫端給。
    const user = userEvent.setup()
    useCourse("CLOSED")
    server.use(
      http.put("/api/et/courses/:courseId", () => new HttpResponse(null, { status: 204 })),
      http.post("/api/et/courses/:courseId/reopen", () =>
        HttpResponse.json({ ...reopened, invited_count: 0, invitation_code: "01234567" }),
      ),
    )
    renderEditor()
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")

    await user.click(await screen.findByRole("button", { name: "更新並重開課" }))

    const dialog = await screen.findByRole("dialog", { name: "課程已重新開課" })
    expect(within(dialog).getByText(/本次沒有新的學員被自動帶入/)).toBeInTheDocument()
    expect(within(dialog).queryByText(/沒有任何學員符合本課程的受訓對象/)).not.toBeInTheDocument()
    // 邀請碼仍要顯示：0 人時它更重要（教師只能靠它讓人進來）
    expect(within(dialog).getByText("01234567")).toBeInTheDocument()
  }, REOPEN_FLOW_TIMEOUT)

  it("再開課遇發布檢核缺漏時以對話框列出，關閉後停在再開課模式（#428 / #509）", async () => {
    // 🔴 這條補的是刪掉 `ReopenCourseDialog.test.tsx` 一併失去的覆蓋（#428 AC 5）。缺漏不是
    // 一般的失敗：它要停在原地讓教師補內容，而非退出模式或跳 toast。
    //
    // #509：缺漏改以對話框呈現（原本是頁面最上方的紅色區塊）。
    const user = userEvent.setup()
    useCourse("CLOSED")
    useReopenBlocked("NO_MATERIAL", "課程至少須有 1 份教材")
    renderEditor()
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")

    await user.click(screen.getByRole("button", { name: "更新並重開課" }))

    // AC 1：缺漏在對話框裡
    const dialog = await screen.findByRole("dialog", { name: "更新並重開課" })
    expect(within(dialog).getByText(/課程至少須有 1 份教材/)).toBeInTheDocument()
    expect(within(dialog).getByText(/課程目前不符發布條件，無法重新開課/)).toBeInTheDocument()
    // AC 4：只有一顆「關閉」——請求已經失敗，不是再問一次要不要送出
    expect(within(dialog).getAllByRole("button").map((b) => b.textContent)).toEqual(["關閉"])
    // AC 3：頁面上的「此課程已關閉」提示**不進**對話框——兩者講的是不同的事
    expect(within(dialog).queryByText(/此課程已關閉/)).not.toBeInTheDocument()
    expect(screen.queryByText("課程已更新並重新開課")).not.toBeInTheDocument()
    // ⚠️ 缺漏走 422，但**不可**走成一般的錯誤 toast——對話框裡已逐條列出來了
    expect(screen.queryByText(/操作失敗/)).not.toBeInTheDocument()

    await user.click(within(dialog).getByRole("button", { name: "關閉" }))

    // AC 7：關閉後仍停在本頁，教師可直接去補內容。⚠️ 要驗**仍可按**——缺漏是
    // 「補完再送一次」而非終局失敗。關閉後背景要等 aria-hidden 解除，故用 `findByRole`。
    expect(await screen.findByRole("button", { name: "更新並重開課" })).toBeEnabled()
    // 🔴 #720：缺漏時**不離開頁面**（成功才回列表）。少了這條，把失敗也寫成導走
    // 不會有測試紅，而教師會被丟回列表、剛填的時間全沒了。
    expect(navigateSpy).not.toHaveBeenCalledWith("/et/courses")
    // 起訖時間保留剛填的值（不是被清空、也不是回到按鈕前的舊值）
    expect(screen.getByDisplayValue(/2027\/11\/01/)).toBeInTheDocument()
    expect(screen.getByDisplayValue(/2027\/12\/31/)).toBeInTheDocument()
    // AC 2：頁面上**不再有**紅色缺漏區塊。與上方「對話框內查得到」用**同一種查法**——
    // 只寫這條反向斷言的話，文案一改它就恆真。
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    // ⚠️ 與上方 `within(dialog).getByText(...)` **刻意用同一個字串**：只改其中一邊的話，
    // 這條否定斷言會變成恆真（文案裡根本沒有那句話），而它正是本測試的 AC 2。
    expect(screen.queryByText(/課程目前不符發布條件，無法重新開課/)).not.toBeInTheDocument()
    expect(screen.queryByText(/課程至少須有 1 份教材/)).not.toBeInTheDocument()
  })

  it("切換到另一門課程時動作列跟著換（#428 / #720）", async () => {
    // 🔴 `courses/:courseId` 這條路由沒有 `key={courseId}`，React Router 只換參數時**不會
    // 重新掛載元件**（本檔開頭把 `useParams` 做成可變就是為了模擬這件事）。
    //
    // #428 當時防的是 `reopening` 這個**模式旗標**跟著使用者從課程 A 帶到課程 B：一門
    // 根本不是關閉中的課程顯示著再開課模式，按下去是對**錯的課程**送出請求。
    //
    // ⚠️ #720 拿掉了模式（動作列改由 `course.is_closed` 推導），所以那個旗標不存在了
    // ——但**本條仍然有價值**，它現在驗的是「推導真的跟著資料走」：少了它，哪天有人把
    // 動作列改回用 state 記憶，同一個缺陷會原封不動回來而沒有測試紅。
    //
    // 上一頁 / 下一頁與直接改網址都會走到這條路徑，不需要回列表頁。
    server.use(
      http.get("/api/et/courses/:courseId", ({ params }) => {
        const id = Number(params.courseId)
        return HttpResponse.json({
          course_id: id,
          course_name: `課程 ${id}`,
          description: null,
          status: id === 1 ? "CLOSED" : "PUBLISHED",
          open_start_at: "2026-09-01T00:00:00Z",
          open_end_at: "2027-09-30T00:00:00Z",
          require_approval: false,
          version: 5,
          owner_id: "U1",
          owner_name: "王教師",
          is_owner: true,
          audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
          chapters: [],
          invitation_code: "01234567",
          has_pending_changes: false,
          is_closed: id === 1,
        })
      }),
    )
    const { rerender } = renderEditor("1")
    await screen.findByRole("button", { name: "更新並重開課" })

    paramsRef.current = { courseId: "2" }
    rerender(<EtCourseEditorPage />)

    expect(await screen.findByDisplayValue("課程 2")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "更新並重開課" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "保留編輯" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "更新" })).toBeInTheDocument()
  })

  it("再開課送出中停用送出鈕，防連點造出兩次再開課（#428）", async () => {
    // 🔴 補刪除 `ReopenCourseDialog.test.tsx` 一併失去的覆蓋。後端有樂觀鎖兜底，但第二次
    // 請求仍會白跑一趟並吃掉一格限流（`reopen` 與 publish / close 共用 20 次/分鐘的桶）。
    //
    // ⚠️ 請求何時完成由**測試**決定（#687）：handler 停在 `gate` 上，直到下方 `release()`。
    // 原本是 handler 等 200ms 後回應，機器稍忙時點擊處理完之前那 200ms 就過了、按鈕已恢復，
    // `toBeDisabled()` 因此失敗——斷言的是「送出中」，卻沒有保證斷言時請求真的還在送。
    let calls = 0
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    // 斷言中途失敗時 `release()` 不會執行——仍要放行，不留一個永遠等不到回應的請求
    onTestFinished(() => release())
    server.use(
      http.put("/api/et/courses/:courseId", () => new HttpResponse(null, { status: 204 })),
      http.post("/api/et/courses/:courseId/reopen", async () => {
        calls += 1
        await gate
        return HttpResponse.json(reopened)
      }),
    )
    const user = userEvent.setup()
    useCourse("CLOSED")
    renderEditor()
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")

    const submit = screen.getByRole("button", { name: "更新並重開課" })
    await user.click(submit)
    // 請求已抵達後端且尚未回應——下面兩個斷言因此必定落在「送出中」
    await waitFor(() => expect(calls).toBe(1))

    expect(submit).toBeDisabled()
    // 「保留編輯」也要一起停用：它同樣會先送一次 `PUT`（`stageBasic`），在重開課送出中
    // 按下去會讓兩條路徑搶同一份暫存區（#720）。
    expect(screen.getByRole("button", { name: "保留編輯" })).toBeDisabled()
    release()
    // 成功的證據改成結果視窗（#720：不再是 toast），`calls` 仍須維持 1
    await screen.findByRole("dialog", { name: "課程已重新開課" })
    expect(calls).toBe(1)
  }, REOPEN_FLOW_TIMEOUT)

  it("上一次再開課的缺漏不會殘留到下一次（#428）", async () => {
    // ⚠️ 現行程式碼刻意把「再開課的缺漏」與「發布的缺漏」分成兩份 state，理由是避免
    // 互相污染。改成就地顯示之後，同一個位置會被重複進出，殘留的風險從「兩個視窗之間」
    // 變成「同一頁的前後兩次」——同一個問題換了形狀，故補這條。
    const user = userEvent.setup()
    useCourse("CLOSED")
    useReopenBlocked("NO_MATERIAL", "課程至少須有 1 份教材")
    renderEditor()
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")
    await user.click(screen.getByRole("button", { name: "更新並重開課" }))
    const dialog = await screen.findByRole("dialog", { name: "更新並重開課" })
    expect(within(dialog).getByText(/課程至少須有 1 份教材/)).toBeInTheDocument()

    await user.click(within(dialog).getByRole("button", { name: "關閉" }))

    expect(await screen.findByRole("button", { name: "更新並重開課" })).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(screen.queryByText(/課程至少須有 1 份教材/)).not.toBeInTheDocument()
  }, REOPEN_FLOW_TIMEOUT)

  describe("發布與再開課的缺漏 state 分離（#509 AC 6）", () => {
    // ⛔ #509 只共用**呈現元件**，不共用資料。兩份 state 的理由見 `reopenBlockers` 的宣告。
    //
    // ⚠️ 同一門課不可能同時是草稿（能發布）又是已關閉（能再開課），兩份 state 都有值的
    // 情境只能靠**切換課程**造出：本路由沒有 `key={courseId}`，只換參數時不重新掛載元件
    // （見「切換到另一門課程時會退出再開課模式」）。兩個方向各一條——它們是不同的路徑。
    function useTwoCourses() {
      server.use(
        http.get("/api/et/courses/:courseId", ({ params }) => {
          const id = Number(params.courseId)
          return HttpResponse.json({
            course_id: id,
            course_name: `課程 ${id}`,
            description: null,
            status: id === 1 ? "DRAFT" : "CLOSED",
            open_start_at: "2026-09-01T00:00:00Z",
            open_end_at: "2027-09-30T00:00:00Z",
            require_approval: false,
            version: 5,
            owner_id: "U1",
            owner_name: "王教師",
            is_owner: true,
            audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
            chapters: [],
            invitation_code: id === 1 ? null : "01234567",
            has_pending_changes: false,
            is_closed: id !== 1,
          })
        }),
        http.put("/api/et/courses/:courseId", ({ params }) =>
          HttpResponse.json({ course_id: Number(params.courseId), version: 6 }),
        ),
        http.get("/api/et/courses/:courseId/publish-check", () =>
          HttpResponse.json({
            can_publish: false,
            blockers: [{ code: "NO_TAG", message: "課程至少須設定 1 組受訓對象", target_id: null }],
          }),
        ),
      )
      useReopenBlocked("NO_MATERIAL", "課程至少須有 1 份教材")
    }

    async function failReopen(user: ReturnType<typeof userEvent.setup>) {
        await fillDateTime(/課程起始時間/, "202711010900")
      await fillDateTime(/課程訖止時間/, "202712311700")
      await user.click(screen.getByRole("button", { name: "更新並重開課" }))
      return screen.findByRole("dialog", { name: "更新並重開課" })
    }

    it("發布視窗留下的缺漏不出現在再開課的對話框", async () => {
      const user = userEvent.setup()
      useTwoCourses()
      const { rerender } = renderEditor("1")
      await user.click(await screen.findByRole("button", { name: "儲存並發布" }))
      const publish = await screen.findByRole("dialog", { name: "發布課程" })
      expect(await within(publish).findByText(/課程至少須設定 1 組受訓對象/)).toBeInTheDocument()
      await user.click(within(publish).getByRole("button", { name: "關閉" }))

      paramsRef.current = { courseId: "2" }
      rerender(<EtCourseEditorPage />)
      await screen.findByDisplayValue("課程 2")
      const reopen = await failReopen(user)

      expect(within(reopen).getByText(/課程至少須有 1 份教材/)).toBeInTheDocument()
      expect(within(reopen).queryByText(/課程至少須設定 1 組受訓對象/)).not.toBeInTheDocument()
    }, REOPEN_FLOW_TIMEOUT)

    it("再開課留下的缺漏不出現在發布視窗", async () => {
      // ⚠️ **這條守的是結果，不是「兩份 state 分開」**。2026-10-06 變異檢查：讓再開課
      // 失敗時一併寫進發布用的 `blockers`（等同兩份 state 被污染），本條**照樣綠**——
      // 發布視窗每次打開都會重跑預檢，預檢中顯示「檢核中」、回來就覆寫舊值，殘留的缺漏
      // 在這個方向上結構性地看不到。真正承重的是「開視窗即重跑預檢」。
      //
      // ⛔ 別因為「變異不會紅」就刪掉本條：它釘住的是教師看得到的結果。若日後發布視窗
      // 改成沿用上次的預檢結果（例如為了省一次請求），這條會變成唯一的防線。
      const user = userEvent.setup()
      useTwoCourses()
      const { rerender } = renderEditor("2")
      await screen.findByDisplayValue("課程 2")
      const reopen = await failReopen(user)
      await user.click(within(reopen).getByRole("button", { name: "關閉" }))

      paramsRef.current = { courseId: "1" }
      rerender(<EtCourseEditorPage />)
      await screen.findByDisplayValue("課程 1")
      await user.click(await screen.findByRole("button", { name: "儲存並發布" }))
      const publish = await screen.findByRole("dialog", { name: "發布課程" })

      expect(await within(publish).findByText(/課程至少須設定 1 組受訓對象/)).toBeInTheDocument()
      expect(within(publish).queryByText(/課程至少須有 1 份教材/)).not.toBeInTheDocument()
    }, REOPEN_FLOW_TIMEOUT)
  })

  // ⚠️ 這裡原本有一條「再開課成功後接著按儲存不會被『不可再往前調整』誤擋（#428 迴歸）」。
  //
  // 它驗的是：教師把課程補開在更早的日期之後**留在本頁**繼續編輯時，起始時間的下限
  // （`originalStart`）有沒有跟著更新——沒更新的話，再編任何欄位按儲存都會被一條指著
  // 他剛送出的時間的錯誤訊息擋住。
  //
  // #720 之後「更新並重開課」成功就**回課程列表**（2026-10-19 裁示），而且非草稿狀態
  // 也沒有「儲存」鈕了——「接著按儲存」這個情境從 UI 到不了，留著的測試會驗一條不存在
  // 的路徑。對應的 `setOriginalStart` 寫回也一併移除，理由寫在 `reopenMut.onSuccess`。
  //
  // ⛔ 若日後把「成功後留在原地」改回來，那段寫回**與本測試**都要一起回來。

  it("關閉送出的 body 只有 version", async () => {
    let body: Record<string, unknown> | undefined
    server.use(
      http.post("/api/et/courses/:courseId/close", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          course_id: 1,
          status: "CLOSED",
          open_start_at: null,
          open_end_at: null,
          closed_at: "2026-09-09T03:00:00Z",
          version: 6,
        })
      }),
    )

    await coursesApi.close(1, 5)

    expect(body).toEqual({ version: 5 })
  })
})
