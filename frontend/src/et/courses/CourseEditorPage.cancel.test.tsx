import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtCourseEditorPage } from "./CourseEditorPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/**
 * ET05 按「取消」要先問一次的情形（#804 ① / #812）。
 *
 * ## 為何另開一個檔
 *
 * `CourseEditorPage.test.tsx` 已經到 800 行。#682 拆檔時的教訓是**單檔跑太久會把自己
 * 擠到逾時**——那不是負載造成的，乾淨機器上照樣紅。#812 要再加 4 條，不分檔就一定破線。
 * vitest 以**檔**為平行單位，分檔即分開排程。
 *
 * ## 本組守的是「按鈕上那兩個字有沒有說實話」
 *
 * 「取消」在這一頁有三種結果，而按鈕從頭到尾只有那兩個字：
 *
 * | 狀態 | 章節 / 教材 / 測驗 / 問卷 | 尚未送出的基本資料 |
 * |---|---|---|
 * | 新增 | 都在畫面的 state 裡，一個都沒寫進 DB | 跟著丟 |
 * | 草稿 | **已經寫進活表**（#631 只把已發布改成暫存），取消還原不了 | **靜默丟掉** |
 * | 已發布 / 已關閉 | 在暫存區，按生效鈕才對學員生效 | **靜默丟掉** |
 *
 * 2026-10-22 手測原話：「按取消和儲存草稿是一樣的，都會儲存」。同日裁示**按鈕不改名**
 *（已發布那邊的「取消」對暫存內容是真的會放棄，同一個字要維持同一個樣子），改為在
 * 基本資料有未送出的修改時先問一次。
 */

const { navigateSpy, paramsRef, locationRef } = vi.hoisted(() => ({
  navigateSpy: vi.fn(),
  paramsRef: { current: { courseId: "1" } as Record<string, string | undefined> },
  locationRef: { current: { pathname: "/et/courses/1", state: null } as { pathname: string; state: unknown } },
}))
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => paramsRef.current,
    useLocation: () => locationRef.current,
    // 離開攔截需要 data router，`renderWithProviders` 內建的是 MemoryRouter——真的
    // `useBlocker` 在此會拋錯。以「永不攔截」取代，站內離開的攔截屬 e2e 行為。
    useBlocker: () => ({ state: "unblocked", proceed: () => {}, reset: () => {} }),
  }
})

// 🔴 `navigateSpy` 由 `vi.hoisted` 建立、整個檔案共用同一個實例，必須逐條清掉：
// 本檔**每一條**都在斷言有沒有導航，殘留會讓「不該離開」那幾條假性通過。
beforeEach(() => {
  navigateSpy.mockClear()
  locationRef.current = { pathname: "/et/courses/1", state: null }
})

/** 編輯模式：帶 courseId 路由參數。 */
function renderEditor(courseId = "1") {
  paramsRef.current = { courseId }
  return renderWithProviders(<EtCourseEditorPage />)
}

/** 新增模式：無路由參數。**不可寫成 `renderNewEditor()`**——傳 undefined 會
 *  觸發預設參數而變成編輯模式，是難以察覺的假通過。 */
function renderNewEditor() {
  paramsRef.current = {}
  return renderWithProviders(<EtCourseEditorPage />)
}

/** 草稿課程。起訖放在遠未來：起始時間不可早於當下。 */
function mockScheduledDraft(overrides: Record<string, unknown> = {}) {
  server.use(
    http.get("/api/et/courses/:courseId", ({ params }) =>
      HttpResponse.json({
        course_id: Number(params.courseId),
        course_name: "採血作業訓練",
        description: "課程說明",
        status: "DRAFT",
        open_start_at: "2099-01-01T00:00:00Z",
        open_end_at: "2099-12-31T00:00:00Z",
        require_approval: false,
        version: 0,
        owner_id: "U1",
        owner_name: "王教師",
        is_owner: true,
        audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
        chapters: [
          { chapter_id: 11, chapter_name: "第一章", sort_order: 1, version: 0, items: [] },
          { chapter_id: 12, chapter_name: "第二章", sort_order: 2, version: 0, items: [] },
        ],
        ...overrides,
      }),
    ),
  )
}

describe("草稿按「取消」要先講清楚哪一半留著（#804 ①）", () => {
  // ## 「取消」在草稿與已發布是兩件事
  //
  // #631 只把**已發布 / 已關閉**的內容編輯改成暫存；草稿維持**即時寫入活表**
  //（`test_草稿課程的內容編輯仍直接寫活表` 釘住這件事）。於是草稿按「取消」之後：
  //
  // | | 結果 |
  // |---|---|
  // | 章節 / 教材 / 測驗 / 問卷 | **已經存進課程**，取消不會還原 |
  // | 尚未按「儲存草稿」的基本資料 | **靜默丟掉** |
  //
  // 兩半命運相反，而按鈕只說了「取消」。2026-10-22 手測原話：「按取消和儲存草稿是
  // 一樣的，都會儲存」。
  //
  // 2026-10-22 裁示：**按鈕不改名**（已發布那邊的「取消」是真的會放棄，維持同一個字），
  // 改為在基本資料有未存修改時補一個確認視窗。
  async function clickCancel() {
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "取消" }))
    return user
  }

  /**
   * 已發布（或已關閉）**且暫存區為空**的課程。
   *
   * 🔴 `has_pending_changes: false` 是**承重的**（#804 的教訓）：若 mock 成 `true`，
   * `requestCancel` 會在 `if (!hasPendingChanges)` 就分流走，**根本到不了**要驗的那段
   * 程式——測試會永遠綠，不管守門被拆成什麼樣。
   */
  function mockPublishedNoStage(overrides: Record<string, unknown> = {}) {
    server.use(
      http.get("/api/et/courses/:courseId", ({ params }) =>
        HttpResponse.json({
          course_id: Number(params.courseId),
          course_name: "採血作業訓練",
          description: "課程說明",
          status: "PUBLISHED",
          open_start_at: "2099-01-01T00:00:00Z",
          open_end_at: "2099-12-31T00:00:00Z",
          require_approval: false,
          version: 0,
          owner_id: "U1",
          owner_name: "王教師",
          is_owner: true,
          is_closed: false,
          has_pending_changes: false,
          audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
          chapters: [],
          ...overrides,
        }),
      ),
    )
  }

  it("🔴 草稿且基本資料有未存修改時，先跳視窗並把兩半分開講", async () => {
    mockScheduledDraft()
    const user = userEvent.setup()
    renderEditor()
    await user.type(await screen.findByDisplayValue("採血作業訓練"), "X")
    await user.click(screen.getByRole("button", { name: "取消" }))

    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText(/取消不會還原已存入的內容/)).toBeInTheDocument()
    // 🔴 兩半都要講到——只講其中一半就是把另一半的命運藏起來。
    //
    // ⚠️ #814 把這支排成兩行對照、主詞加粗，於是**同一句話被切到不同元素**，
    // `getByText(整句)` 會查不到。改以整個視窗的文字內容比對——它不受元素切分影響，
    // 而本條要守的本來就是「這兩句話有沒有講到」，不是它們被放在哪個標籤裡。
    const text = dialog.textContent ?? ""
    expect(text).toContain("章節、教材、測驗與課後問卷的編輯在草稿課程會即時存入，「取消」不會還原它們。")
    expect(text).toContain("尚未按「儲存草稿」的基本資料修改則不會保留。")
    // ⛔ 一概而論的說法對章節那一半是假的（#763 ② 修掉的同一種毛病）
    expect(text).not.toContain("變更將不會保留")
    expect(within(dialog).getByRole("button", { name: "離開" })).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "繼續編輯" })).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalledWith("/et/courses")
  })

  it("按「離開」才真的離開", async () => {
    mockScheduledDraft()
    const user = userEvent.setup()
    renderEditor()
    await user.type(await screen.findByDisplayValue("採血作業訓練"), "X")
    await user.click(screen.getByRole("button", { name: "取消" }))
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "離開" }))

    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith("/et/courses"))
  })

  it("草稿但基本資料未改動時維持現狀：直接離開、不跳視窗（正向錨點）", async () => {
    // 少了這條，把視窗改成無條件跳出也會讓上面兩條通過——而那會讓每一次單純的離開
    // 都多一次確認。⚠️ 判定用**快照比對**而非 dirty flag，所以「改了又改回原值」也算未改動。
    mockScheduledDraft()
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    await clickCancel()

    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith("/et/courses"))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("新增模式不跳視窗——那裡什麼都還沒存（範圍錨點）", async () => {
    // 🔴 視窗內文說「章節…會即時存入」，而**新增模式的章節放在 `stagedChapters` 這個
    // 畫面上的 state 裡、一個都沒寫進 DB**。對新增模式說那句話是假的。
    //
    // ⇒ 範圍是 `status === "DRAFT" && !isNew`。新增模式維持直接離開——那裡什麼都沒存，
    //「取消」這個字是誠實的。
    const user = userEvent.setup()
    renderNewEditor()
    await user.type(await screen.findByLabelText(/課程名稱/), "新課程")
    await user.click(screen.getByRole("button", { name: "取消" }))

    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith("/et/courses"))
    expect(screen.queryByText(/取消不會還原已存入的內容/)).not.toBeInTheDocument()
  })

  it("🔴 已發布且**沒有**暫存、基本資料有改時，不跳草稿那個視窗（守 `status === \"DRAFT\"`）", async () => {
    // ## 這條補的是 code review 找到的漏洞
    //
    // 下面那條已發布錨點 mock 的是 `has_pending_changes: true`，於是在
    // `if (!hasPendingChanges)` 就分流走了，**根本到不了新分支**——把 `status === "DRAFT"`
    // 拿掉，它照樣綠。
    //
    // 真正會被誤傷的是這個組合：**已發布、還沒有暫存、教師剛改了基本資料**。少了這道
    // 守門，他會看到「章節…在草稿課程會即時存入」——而對已發布課程那句話是假的：
    // 他的章節編輯在暫存區裡，按「更新」才生效。
    server.use(
      http.get("/api/et/courses/:courseId", ({ params }) =>
        HttpResponse.json({
          course_id: Number(params.courseId),
          course_name: "採血作業訓練",
          description: "課程說明",
          status: "PUBLISHED",
          open_start_at: "2099-01-01T00:00:00Z",
          open_end_at: "2099-12-31T00:00:00Z",
          require_approval: false,
          version: 0,
          owner_id: "U1",
          owner_name: "王教師",
          is_owner: true,
          is_closed: false,
          has_pending_changes: false,
          audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
          chapters: [],
        }),
      ),
    )
    const user = userEvent.setup()
    renderEditor()
    await user.type(await screen.findByDisplayValue("採血作業訓練"), "X")
    await user.click(screen.getByRole("button", { name: "取消" }))

    // ⚠️ #812 之後這個組合**會**跳視窗（只是不是草稿那個）。本條的守備範圍仍是
    // 「草稿那段文字不可出現在已發布課程」——那句「會即時存入」對暫存區是假的。
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).queryByText(/取消不會還原已存入的內容/)).not.toBeInTheDocument()
    expect(within(dialog).queryByText(/會即時存入/)).not.toBeInTheDocument()
  })

  it("🔴 已發布、無暫存、基本資料有改 → 先問，且講明章節那半沒有待處理的編輯（#812）", async () => {
    // ## #804 只補了草稿那一半
    //
    // 已發布／已關閉的各類編輯**進暫存的時機不同**：章節 / 教材 / 測驗 / 問卷是立即
    // 寫進暫存（`has_pending_changes` 因此為真、走既有的「放棄本次的編輯」），而
    // **基本資料只在按「更新」時才 `stageBasic()`**——在那之前它只是畫面上的 state。
    //
    // ⇒ 教師改完課名按「取消」，什麼都沒問就離開，改動消失。
    mockPublishedNoStage()
    const user = userEvent.setup()
    renderEditor()
    await user.type(await screen.findByDisplayValue("採血作業訓練"), "X")
    await user.click(screen.getByRole("button", { name: "取消" }))

    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText(/尚未按「更新」的基本資料不會保留/)).toBeInTheDocument()
    expect(within(dialog).getByText(/要按「更新」才會送出，離開不會保留/)).toBeInTheDocument()
    // 🔴 這一句是必要的：教師看到「不會保留」會擔心章節也沒了。此分支的前提就是
    // `has_pending_changes === false`，所以這句話在這裡恆真。
    expect(within(dialog).getByText(/目前沒有待生效的編輯/)).toBeInTheDocument()
    // ⛔ 草稿那段對已發布是假的（那邊的章節在暫存區，不是即時存入）
    expect(within(dialog).queryByText(/會即時存入/)).not.toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "離開" })).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalledWith("/et/courses")
  })

  // 生效鈕在這兩種課程上叫「更新並重開課」。寫死「更新」會把教師指向一顆畫面上
  // 不存在的按鈕——`applyLabel` 已經在處理這件事，這裡沿用。
  //
  // ℹ️ 兩個案例走的是**同一條程式路徑**：分流只看 `status === "DRAFT"`（兩者皆否）與
  // `reopening = course.is_closed`（兩者皆真），沒有一行程式碼區分它們。列兩筆是為了
  // 對上驗收條件的「已關閉／視同關閉」兩半各有正向證據，不是因為它們會分岔。
  //
  // 🔴 **「視同關閉」是 `PUBLISHED` + `is_closed: true`**（閱課期間已過），判定全在後端
  //（`schemas.ts` 的 `is_closed`）。前端不自行比對 `open_end_at`——複製一份規則過來，
  // 兩邊就會各自漂移。
  it.each([
    ["已關閉", { status: "CLOSED", is_closed: true }],
    ["視同關閉（已發布但閱課期間已過）", { status: "PUBLISHED", is_closed: true }],
  ])("%s 的同一個視窗指向「更新並重開課」，不是「更新」（#812）", async (_label, overrides) => {
    mockPublishedNoStage(overrides)
    const user = userEvent.setup()
    renderEditor()
    await user.type(await screen.findByDisplayValue("採血作業訓練"), "X")
    await user.click(screen.getByRole("button", { name: "取消" }))

    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText(/要按「更新並重開課」才會送出/)).toBeInTheDocument()
    // 🔴 **標題也要驗。** 第一版只有內文用 `applyLabel`、標題寫死「更新」，於是同一個
    // 視窗自己打架——而當時這條只斷言 `content`，所以它全綠（security review LOW 抓到）。
    //
    // ⚠️ 用**完整字串**而非 regex：「尚未按「更新並重開課」的…」本身就含「更新」二字，
    // 寫成 `/尚未按「更新」/` 會把正確的標題也判成錯的。
    expect(within(dialog).getByText("尚未按「更新並重開課」的基本資料不會保留")).toBeInTheDocument()
    expect(within(dialog).queryByText("尚未按「更新」的基本資料不會保留")).not.toBeInTheDocument()
  })

  it("已發布、無暫存、基本資料**未**改 → 直接離開，不跳視窗（正向錨點）", async () => {
    // 少了這條，把視窗改成「只要不是草稿就跳」也會讓上面兩條通過——而那會讓每一次
    // 單純的離開都多一道確認。
    mockPublishedNoStage()
    const user = userEvent.setup()
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    await user.click(screen.getByRole("button", { name: "取消" }))

    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith("/et/courses"))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("已發布課程的「取消」維持原本的放棄視窗，一字不動（正向錨點）", async () => {
    // 那邊的「取消」是真的會放棄（內容在暫存區），文案本來就正確。少了這條，把新視窗
    // 套用到所有狀態也會讓前面幾條通過——而那會對一門內容真的會被丟掉的課程說「不會還原」。
    server.use(
      http.get("/api/et/courses/:courseId", ({ params }) =>
        HttpResponse.json({
          course_id: Number(params.courseId),
          course_name: "採血作業訓練",
          description: "課程說明",
          status: "PUBLISHED",
          open_start_at: "2099-01-01T00:00:00Z",
          open_end_at: "2099-12-31T00:00:00Z",
          require_approval: false,
          version: 0,
          owner_id: "U1",
          owner_name: "王教師",
          is_owner: true,
          is_closed: false,
          has_pending_changes: true,
          audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
          chapters: [],
        }),
      ),
    )
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    await clickCancel()

    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText(/放棄本次的編輯/)).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "放棄並離開" })).toBeInTheDocument()
    expect(within(dialog).queryByText(/取消不會還原已存入的內容/)).not.toBeInTheDocument()
  })

  // ## 兩顆按鈕要真的接上去（#812 code review MEDIUM）
  //
  // 上面那幾條只驗了**文字**與按鈕的存在。草稿那個視窗有「按『離開』才真的離開」釘住
  // `onOk`，已發布這個沒有——`onOk` 寫錯、或 `okText` / `cancelText` 對調，那幾條
  // 照樣全綠，而教師按下「離開」會留在原地、按「繼續編輯」反而被踢走。
  //
  // 🔴 兩條要**成對**：只驗「離開會走」的話，把 `onOk` 改成無條件導航（連
  // `cancelText` 那顆也導）仍然通過。

  it("已發布的視窗按「離開」才真的離開（#812）", async () => {
    mockPublishedNoStage()
    const user = userEvent.setup()
    renderEditor()
    await user.type(await screen.findByDisplayValue("採血作業訓練"), "X")
    await user.click(screen.getByRole("button", { name: "取消" }))
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "離開" }))

    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith("/et/courses"))
  })

  it("已發布的視窗按「繼續編輯」留在原地，修改還在（#812）", async () => {
    mockPublishedNoStage()
    const user = userEvent.setup()
    renderEditor()
    await user.type(await screen.findByDisplayValue("採血作業訓練"), "X")
    await user.click(screen.getByRole("button", { name: "取消" }))
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "繼續編輯" }))

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(navigateSpy).not.toHaveBeenCalledWith("/et/courses")
    // 🔴 「繼續編輯」的意思是**那個修改還在**。少了這一句，把 `onCancel` 寫成
    // 重新載入課程（把教師改的字蓋掉）也會通過——而那正是這顆鈕要避免的事。
    expect(screen.getByDisplayValue("採血作業訓練X")).toBeInTheDocument()
  })

  it("🔴 快照被帶進新增模式時仍直接離開，不跳視窗（守 `isNew`，#812 code review）", async () => {
    // ## 這條讓一段原本測不到的程式變成測得到的
    //
    // `requestCancel` 的草稿分支裡有一道 `if (isNew) { navigate; return }`。從**現有的**
    // 路由永遠走不到它：新增模式沒有課程可載入，`loadedBasic` 從頭到尾是 `null`，
    // `isBasicDirty()` 先回 `false` 就分流走了。上面那條「新增模式不跳視窗」走的正是
    // 這條捷徑——**到不了**要守的那一行，把它刪掉照樣綠。
    //
    // 它防的是 `CourseEditorPage` 既有註解寫明的機制：
    //
    // > `courses/:courseId` 這條路由沒有 `key={courseId}`，React Router 只換參數時
    // > **不會重新掛載元件**，所以任何殘留的 state 都會跟著使用者
    //
    // 日後 `/courses/new` 與 `/courses/:courseId` 一旦共用同一個 element，參數從有變無
    // 時元件不重新掛載，`loadedBasic` 就會跟著進新增模式——此時 `isBasicDirty()` 為真，
    // 而兩段文案對新增模式**都是假的**：它的章節放在畫面的 state 裡、一個都沒寫進 DB。
    //
    // ⇒ 這裡用 `rerender` 重現那個機制（換參數、不 unmount），讓那一行有東西守著。
    mockScheduledDraft()
    const user = userEvent.setup()
    const { rerender } = renderEditor()
    await user.type(await screen.findByDisplayValue("採血作業訓練"), "X")

    paramsRef.current = {}
    rerender(<EtCourseEditorPage />)

    await user.click(screen.getByRole("button", { name: "取消" }))

    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith("/et/courses"))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("🔴 「基本資料」卡涵蓋快照追蹤的每一個欄位（#812 視窗文案的前提）", async () => {
    // ## 文案說「『基本資料』區的修改」，這條確保那句話不多不少
    //
    // 初版文案逐項列出「課程名稱、說明、起訖時間與受訓對象」，漏了「本課程需線下核可」
    //（code review LOW）。改成指畫面上的區塊名之後，正確性就靠一件事撐著：
    // **`serializeBasic` 追蹤的欄位全都在那張卡裡**。
    //
    // 那是版面決定的、沒有任何型別或執行期檢查擋著。有人把某個欄位搬出那張卡，文案
    // 就開始漏講，而所有文字斷言照樣綠——⇒ 用這條釘住。
    mockPublishedNoStage()
    renderEditor()

    const heading = await screen.findByText("基本資料")
    const card = heading.closest(".MuiPaper-root")
    expect(card).not.toBeNull()

    // `serializeBasic` 的 6 個欄位（`basicSnapshot.ts`）逐一對到畫面上的控制項。
    // ⚠️ 新增追蹤欄位時這裡要跟著加，否則文案會漏講它。
    // ⚠️ 用 `getAllBy*` 數數量而非 `getBy*`：MUI 的 `DateTimePicker` 一個 label 會對到
    // 多個元素（section list 與隱藏 input），`getByLabelText` 會以「找到多個」失敗——
    // 那是**元件長相**造成的紅，不是這條要驗的事。欄位被搬出卡時陣列為空，照樣紅。
    const inCard = within(card as HTMLElement)
    const present = (label: RegExp | string) => inCard.getAllByLabelText(label).length
    expect(present(/課程名稱/)).toBeGreaterThan(0)
    expect(present(/課程描述/)).toBeGreaterThan(0)
    expect(present("本課程需線下核可")).toBeGreaterThan(0)
    expect(present(/課程起始時間/)).toBeGreaterThan(0)
    expect(present(/課程訖止時間/)).toBeGreaterThan(0)
    expect(inCard.getByText("受訓對象")).toBeInTheDocument()
  })
})
