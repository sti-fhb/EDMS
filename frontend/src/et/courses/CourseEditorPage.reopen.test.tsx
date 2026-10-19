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
const { navigateSpy, paramsRef, locationRef } = vi.hoisted(() => ({
  navigateSpy: vi.fn(),
  paramsRef: { current: {} as Record<string, string | undefined> },
  // 自動存草稿（#335）跨了元件重新掛載——待開啟的項目由 navigate 的 state 帶過去，
  // 故 useLocation 也須可控。
  locationRef: { current: { pathname: "/et/courses/new", state: null } as { pathname: string; state: unknown } },
}))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => paramsRef.current,
    useLocation: () => locationRef.current,
    // 離開攔截（#631）需要 data router，`renderWithProviders` 內建的是 MemoryRouter
    // ——真的 `useBlocker` 在此會拋錯。以「永不攔截」取代，站內離開的攔截屬 e2e 行為
    //（比照 DM `DmEditorPage.test.tsx` 與 `QuizAnswerPage.test.tsx`）。
    useBlocker: () => ({ state: "unblocked", proceed: () => {}, reset: () => {} }),
  }
})

/** 編輯模式：帶 courseId 路由參數。 */
function renderEditor(courseId = "1") {
  paramsRef.current = { courseId }
  return renderWithProviders(<EtCourseEditorPage />)
}

beforeEach(() => {
  navigateSpy.mockClear()
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
  { isOwner = true, pending = false }: { isOwner?: boolean; pending?: boolean } = {},
) {
  server.use(
    http.get("/api/et/courses/:courseId", () =>
      HttpResponse.json({
        course_id: 1,
        course_name: "採血作業訓練",
        description: null,
        status,
        open_start_at: "2026-09-01T00:00:00Z",
        open_end_at: "2027-09-30T00:00:00Z",
        require_approval: false,
        version: 5,
        owner_id: "U1",
        owner_name: "王教師",
        is_owner: isOwner,
        audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
        chapters: [],
        invitation_code: isOwner ? "01234567" : null,
        has_pending_changes: pending,
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
  const field = screen.getAllByLabelText(label).find((el) => el.getAttribute("role") === "group")
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
 * 「進入再開課模式 → 填兩次 `DateTimePicker` → 送出 / 開關對話框」測試的個別 timeout（#687）。
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
  it("編輯頁的邀請碼不帶「發布後永久不可變更」的括號說明（#359 第 2 項）", async () => {
    useCourse("PUBLISHED")
    renderEditor()

    // 邀請碼本身與複製鈕行為不變（AC）
    expect(await screen.findByText("01234567")).toBeInTheDocument()
    // 規則改由 ET05 手冊承載（「邀請碼於發布當下產生，之後沿用同一組」）——畫面不寫、
    // 手冊寫「看不出來的規則」是刻意的分工。
    expect(screen.queryByText(/永久不可變更/)).not.toBeInTheDocument()
  })

  it("已發布課程顯示「關閉課程」，不顯示「再開課」", async () => {
    useCourse("PUBLISHED")
    renderEditor()
    expect(await screen.findByRole("button", { name: "關閉課程" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "再開課" })).not.toBeInTheDocument()
  })

  it("已關閉課程顯示「再開課」，不顯示「關閉課程」與「邀請學員」", async () => {
    // AC 5 / FR-ET-US11-07：關閉期間不可邀請學員，故按鈕一併收起（後端另以
    // ET_INVITE_004 把關）。再開課後 status 回 PUBLISHED，兩顆按鈕自然互換。
    useCourse("CLOSED")
    renderEditor()

    expect(await screen.findByRole("button", { name: "再開課" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "關閉課程" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "邀請學員" })).not.toBeInTheDocument()
  })

  it("已關閉提示明確寫出「課程內容仍可編輯」（AC 6）", async () => {
    // 少了這句，教師會以為關閉後這頁是唯讀的而不敢改——AC 6 的整個用意就是讓他能在
    // 關閉期間整理教材再開課。
    useCourse("CLOSED")
    renderEditor()
    expect(await screen.findByText(/此課程已關閉/)).toBeInTheDocument()
    expect(screen.getByText(/課程內容仍可編輯/)).toBeInTheDocument()
  })

  it("草稿不顯示關閉 / 再開課（草稿沒有學員也沒有邀請碼，關閉沒有語意）", async () => {
    useCourse("DRAFT")
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    expect(screen.queryByRole("button", { name: "關閉課程" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "再開課" })).not.toBeInTheDocument()
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

  it("非擁有者（檢視模式）不顯示關閉 / 再開課", async () => {
    useCourse("PUBLISHED", { isOwner: false })
    renderEditor()
    await screen.findByText(/檢視模式/)
    expect(screen.queryByRole("button", { name: "關閉課程" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "再開課" })).not.toBeInTheDocument()
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
    expect(await screen.findByText("課程已關閉")).toBeInTheDocument()
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
    expect(screen.queryByText("課程已關閉")).not.toBeInTheDocument()
  })

  // #428：再開課改為**就地清空編輯頁的起訖時間**，不再跳對話框。
  it("按再開課會清空起訖時間，但不動任何資料（#428）", async () => {
    const user = userEvent.setup()
    useCourse("CLOSED")
    renderEditor()
    // 進入前欄位有值
    expect(await screen.findByDisplayValue(FIXTURE_START_SHOWN)).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "再開課" }))

    expect(await screen.findByRole("button", { name: "確認再開課" })).toBeInTheDocument()
    // 🔴 本設計的核心：清空只發生在畫面上
    expect(screen.queryByDisplayValue(FIXTURE_START_SHOWN)).not.toBeInTheDocument()
    expect(screen.getByText(/按「取消再開課」即可還原/)).toBeInTheDocument()

    // 🔴 裁示原文是「清空…並用紅色框起來提醒使用者重新設定時間」——紅框本身就是提醒，
    // 等按下「確認再開課」才變紅等於少了一次提示。
    for (const label of [/課程起始時間/, /課程訖止時間/]) {
      const field = screen.getAllByLabelText(label).find((el) => el.getAttribute("role") === "group")
      expect(field?.className).toMatch(/Mui-error/)
    }
    // ⚠️ 紅框歸紅框：還沒動手的人不該看到錯誤訊息
    expect(screen.queryByText("請重新設定課程起始時間")).not.toBeInTheDocument()
    // #592：缺漏改以視窗列出（#509），底部說明不可再說「在上方列出」
    expect(screen.getByText(/有缺漏時會以視窗列出/)).toBeInTheDocument()
    expect(screen.queryByText(/會在上方列出缺漏/)).not.toBeInTheDocument()
  })

  it("取消再開課會把清掉的時間還原（#428）", async () => {
    // 🔴 「中途反悔」是本設計最容易漏的一塊——對話框有「取消」，就地編輯沒有。
    // 少了還原，教師反悔後畫面上是一門起訖時間被清掉的課程。
    const user = userEvent.setup()
    useCourse("CLOSED")
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await screen.findByRole("button", { name: "確認再開課" })

    await user.click(screen.getByRole("button", { name: "取消再開課" }))

    expect(await screen.findByDisplayValue(FIXTURE_START_SHOWN)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "確認再開課" })).not.toBeInTheDocument()
  })

  it("再開課模式未填時間即確認會逐欄標示必填（#428）", async () => {
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
    await user.click(await screen.findByRole("button", { name: "再開課" }))

    await user.click(await screen.findByRole("button", { name: "確認再開課" }))

    // #558：先在視窗列出，關閉後才逐欄出現訊息
    const dialog = await screen.findByRole("dialog", { name: "再開課" })
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
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202711010800")

    await user.click(screen.getByRole("button", { name: "確認再開課" }))

    const dialog = await screen.findByRole("dialog", { name: "再開課" })
    expect(within(dialog).getByText("課程訖止時間須晚於起始時間")).toBeInTheDocument()
    expect(called).toBe(0)
    await user.click(within(dialog).getByRole("button", { name: "關閉" }))
    // 仍停在再開課模式，教師可以就地改；訊息改掛在欄位下
    expect(await screen.findByRole("button", { name: "確認再開課" })).toBeInTheDocument()
    expect(screen.getByText("課程訖止時間須晚於起始時間")).toBeInTheDocument()
  })

  it("再開課模式全程不發出一般的課程更新（#428）", async () => {
    // 🔴 再開課模式下 `startAt` / `endAt` 是**刻意清空的畫面值**。一個帶 `null` 的
    // `PUT /courses/{id}` 會把課程的開放期間寫成 NULL 而後端不會擋——教師看到「已儲存」，
    // 學員卻再也進不來。且 `reopen` 是另一支端點（跑 `ensure_reopenable` 與發布檢核），
    // 走一般更新等於時間寫進去了而**課程仍是關閉的**。
    //
    // ⚠️ 斷言「整段流程一次 PUT 都沒有」而非只看按鈕在不在：程式裡另有一道
    // `if (reopening) return`（security review 的 MEDIUM-1），但它從 UI **到不了**——
    // 按鈕不顯示就沒有呼叫端。那道 guard 是給日後改動用的，本測試涵蓋不到它。
    let puts = 0
    server.use(
      http.put("/api/et/courses/:courseId", () => {
        puts += 1
        return HttpResponse.json({ course_id: 1, version: 6 })
      }),
      http.post("/api/et/courses/:courseId/reopen", () => HttpResponse.json(reopened)),
    )
    const user = userEvent.setup()
    useCourse("CLOSED")
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await screen.findByRole("button", { name: "確認再開課" })

    expect(screen.queryByRole("button", { name: "儲存" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "儲存草稿" })).not.toBeInTheDocument()

    // 進出一輪 + 真的送出一次，全程不得有任何一般更新
    await user.click(screen.getByRole("button", { name: "取消再開課" }))
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")
    await user.click(screen.getByRole("button", { name: "確認再開課" }))
    await screen.findByText("課程已再開課")

    expect(puts).toBe(0)
  }, REOPEN_FLOW_TIMEOUT)

  it("再開課送出的 body 只有後端 ReopenCourseReq 接受的三個欄位", async () => {
    // 🔴 迴歸測試。後端 `ReopenCourseReq` 原本繼承 `_CourseFields`，連 `course_name` 的
    // 必填性一起繼承了，而前端從不送它 → 真實操作每次都 422，AC 8 完全不可用。
    //
    // 這個缺陷躲過三層測試：後端整合測試自己多塞 `course_name`、MSW handler 不驗 body、
    // 當時的 `ReopenCourseDialog` 測試用假的 `onSubmit`（該元件已於 #428 移除）。
    // **沒有一層驗過「前端組出的 payload 與後端 schema 相符」**，所以這裡斷言鍵集合。
    //
    // 🔴 #428 改為**走真實 UI**。原本這條直接呼叫 `coursesApi.reopen`，理由寫的是
    // 「`DateTimePicker` 在 jsdom 無法以 userEvent 填值」——實測為誤（見 `fillDateTime`）。
    // 直接呼叫 service 的版本驗不到「頁面有沒有多塞欄位」，而那正是本缺陷的形狀。
    //
    // ⚠️ 對應的後端測試是
    // `test_et_course_close_reopen.py::TestReopen::test_以前端實際送出的欄位再開課`，
    // 兩者是同一份契約的兩端，改動任一邊請同步。
    const user = userEvent.setup()
    let body: Record<string, unknown> | undefined
    useCourse("CLOSED")
    server.use(
      http.post("/api/et/courses/:courseId/reopen", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(reopened)
      }),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")

    await user.click(screen.getByRole("button", { name: "確認再開課" }))

    await waitFor(() => expect(body).toBeDefined())
    expect(Object.keys(body ?? {}).sort()).toEqual(["open_end_at", "open_start_at", "version"])
    expect(body?.version).toBe(5)
    // #564：只改顯示格式，送出的仍是同一個瞬間的 ISO 值。預期值以**本機時區**解讀——測試
    // 不固定時區（本機台灣、CI 為 UTC），寫死字串會一邊綠一邊紅（#483）
    expect(body?.open_start_at).toBe(dayjs("2027-11-01T09:00").toISOString())
    expect(body?.open_end_at).toBe(dayjs("2027-12-31T17:00").toISOString())
  })

  it("再開課成功後畫面立即顯示新的起訖時間（#428 迴歸）", async () => {
    // 🔴 使用者 2026-09-24 手測回報：「選完時間後課程的起始時間沒有跟著變，儲存之後
    // 點回課程卡片才顯示正確的時間」。成因是表單初值的 guard 只在切換到**另一門**課程
    // 時才重設，`invalidate()` 重抓同一門課不會更新欄位。
    const user = userEvent.setup()
    useCourse("CLOSED")
    server.use(http.post("/api/et/courses/:courseId/reopen", () => HttpResponse.json(reopened)))
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")

    await user.click(screen.getByRole("button", { name: "確認再開課" }))

    expect(await screen.findByText("課程已再開課")).toBeInTheDocument()
    expect(screen.getByDisplayValue(/2027\/11\/01/)).toBeInTheDocument()
    expect(screen.getByDisplayValue(/2027\/12\/31/)).toBeInTheDocument()
    // 退出再開課模式，一般的儲存回來
    expect(screen.getByRole("button", { name: "儲存" })).toBeInTheDocument()
  })

  it("再開課遇發布檢核缺漏時以對話框列出，關閉後停在再開課模式（#428 / #509）", async () => {
    // 🔴 這條補的是刪掉 `ReopenCourseDialog.test.tsx` 一併失去的覆蓋（#428 AC 5）。缺漏不是
    // 一般的失敗：它要停在原地讓教師補內容，而非退出模式或跳 toast。
    //
    // #509：缺漏改以對話框呈現（原本是頁面最上方的紅色區塊）。
    const user = userEvent.setup()
    useCourse("CLOSED")
    useReopenBlocked("NO_MATERIAL", "課程至少須有 1 份教材")
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")

    await user.click(screen.getByRole("button", { name: "確認再開課" }))

    // AC 1：缺漏在對話框裡
    const dialog = await screen.findByRole("dialog", { name: "再開課" })
    expect(within(dialog).getByText(/課程至少須有 1 份教材/)).toBeInTheDocument()
    expect(within(dialog).getByText(/課程目前不符發布條件，無法再開課/)).toBeInTheDocument()
    // AC 4：只有一顆「關閉」——請求已經失敗，不是再問一次要不要送出
    expect(within(dialog).getAllByRole("button").map((b) => b.textContent)).toEqual(["關閉"])
    // AC 3：橙色的「請重新設定起訖時間」**不進**對話框（#428 的就地編輯提示）
    expect(within(dialog).queryByText(/請重新設定開放起訖時間/)).not.toBeInTheDocument()
    expect(screen.queryByText("課程已再開課")).not.toBeInTheDocument()
    // ⚠️ 缺漏走 422，但**不可**走成一般的錯誤 toast——對話框裡已逐條列出來了
    expect(screen.queryByText(/操作失敗/)).not.toBeInTheDocument()

    await user.click(within(dialog).getByRole("button", { name: "關閉" }))

    // AC 7：關閉後仍停在再開課模式，教師可直接去補內容。⚠️ 要驗**仍可按**——缺漏是
    // 「補完再送一次」而非終局失敗。關閉後背景要等 aria-hidden 解除，故用 `findByRole`。
    expect(await screen.findByRole("button", { name: "確認再開課" })).toBeEnabled()
    expect(screen.getByText(/請重新設定開放起訖時間/)).toBeInTheDocument()
    // 起訖時間保留剛填的值（不是被清空、也不是回到再開課前的舊值）
    expect(screen.getByDisplayValue(/2027\/11\/01/)).toBeInTheDocument()
    expect(screen.getByDisplayValue(/2027\/12\/31/)).toBeInTheDocument()
    // AC 2：頁面上**不再有**紅色缺漏區塊。與上方「對話框內查得到」用**同一種查法**——
    // 只寫這條反向斷言的話，文案一改它就恆真。
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(screen.queryByText(/課程目前不符發布條件，無法再開課/)).not.toBeInTheDocument()
    expect(screen.queryByText(/課程至少須有 1 份教材/)).not.toBeInTheDocument()
  })

  it("切換到另一門課程時會退出再開課模式（#428）", async () => {
    // 🔴 `courses/:courseId` 這條路由沒有 `key={courseId}`，React Router 只換參數時**不會
    // 重新掛載元件**（本檔開頭把 `useParams` 做成可變就是為了模擬這件事）。少了重置，
    // `reopening` 會跟著使用者從課程 A 帶到課程 B：一門根本不是關閉中的課程顯示著再開課
    // 模式，一般儲存被擋死，而按「確認再開課」是對**錯的課程**送出請求。
    //
    // 上一頁 / 下一頁與直接改網址都會走到這條路徑，不需要回列表頁。
    const user = userEvent.setup()
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
        })
      }),
    )
    const { rerender } = renderEditor("1")
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await screen.findByRole("button", { name: "確認再開課" })

    paramsRef.current = { courseId: "2" }
    rerender(<EtCourseEditorPage />)

    expect(await screen.findByDisplayValue("課程 2")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "確認再開課" })).not.toBeInTheDocument()
    expect(screen.queryByText(/請重新設定開放起訖時間/)).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "儲存" })).toBeInTheDocument()
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
      http.post("/api/et/courses/:courseId/reopen", async () => {
        calls += 1
        await gate
        return HttpResponse.json(reopened)
      }),
    )
    const user = userEvent.setup()
    useCourse("CLOSED")
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")

    const submit = screen.getByRole("button", { name: "確認再開課" })
    await user.click(submit)
    // 請求已抵達後端且尚未回應——下面兩個斷言因此必定落在「送出中」
    await waitFor(() => expect(calls).toBe(1))

    expect(submit).toBeDisabled()
    expect(screen.getByRole("button", { name: "取消再開課" })).toBeDisabled()
    release()
    await screen.findByText("課程已再開課")
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
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    await fillDateTime(/課程起始時間/, "202711010900")
    await fillDateTime(/課程訖止時間/, "202712311700")
    await user.click(screen.getByRole("button", { name: "確認再開課" }))
    const dialog = await screen.findByRole("dialog", { name: "再開課" })
    expect(within(dialog).getByText(/課程至少須有 1 份教材/)).toBeInTheDocument()

    await user.click(within(dialog).getByRole("button", { name: "關閉" }))
    await user.click(await screen.findByRole("button", { name: "取消再開課" }))
    await user.click(await screen.findByRole("button", { name: "再開課" }))

    expect(await screen.findByRole("button", { name: "確認再開課" })).toBeInTheDocument()
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
      await user.click(await screen.findByRole("button", { name: "再開課" }))
      await fillDateTime(/課程起始時間/, "202711010900")
      await fillDateTime(/課程訖止時間/, "202712311700")
      await user.click(screen.getByRole("button", { name: "確認再開課" }))
      return screen.findByRole("dialog", { name: "再開課" })
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

  it("再開課成功後接著按儲存不會被「不可再往前調整」誤擋（#428 迴歸）", async () => {
    // 🔴 承上，`originalStart` 也必須一併寫回，否則本頁仍以**再開課前**的起始時間當
    // 下限。教師若把課程補開在更早的日期（後端允許），接著編輯任何欄位按儲存，就會被
    // 擋在一條指著他剛剛才成功送出的時間的錯誤訊息上。
    //
    // ⚠️ 這條是三個寫回中唯一驗得到 `setOriginalStart` 的——起訖時間本來就停在使用者
    // 輸入的值上，光看畫面分不出有沒有寫回。
    const user = userEvent.setup()
    let saved = false
    useCourse("CLOSED")
    server.use(
      http.post("/api/et/courses/:courseId/reopen", () =>
        HttpResponse.json({ ...reopened, open_start_at: "2026-08-01T01:00:00Z" }),
      ),
      http.put("/api/et/courses/:courseId", () => {
        saved = true
        return HttpResponse.json({ course_id: 1, version: 7 })
      }),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "再開課" }))
    // 補開一段已經開始的期間：起始 2026-08-01，比再開課前的 2026-09-01 更早
    await fillDateTime(/課程起始時間/, "202608010900")
    await fillDateTime(/課程訖止時間/, "202712311700")
    await user.click(screen.getByRole("button", { name: "確認再開課" }))
    await screen.findByText("課程已再開課")

    await user.click(screen.getByRole("button", { name: "儲存" }))

    await waitFor(() => expect(saved).toBe(true))
    expect(screen.queryByText("課程已開課，起始時間不可再往前調整")).not.toBeInTheDocument()
  })

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
