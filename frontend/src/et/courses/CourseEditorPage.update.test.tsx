import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtCourseEditorPage } from "./CourseEditorPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/**
 * ET05「更新」：把暫存的內容編輯整批生效給學員（#631）。
 *
 * ## 為何另開一個檔，而不是加進 `CourseEditorPage.test.tsx`
 *
 * 那個檔已經是全專案最大的測試檔（#682：86 條 `it()`，整組跑時一檔獨佔 210~310 秒，
 * 檔內又用 vitest 預設的 5s timeout，於是自己把自己擠到逾時——**乾淨機器上照樣會紅**，
 * 不是負載造成的）。往裡面再塞 9 條只會讓它更糟，而且本組的結論會被那個雜訊蓋掉。
 * vitest 以**檔**為平行單位，分檔即分開排程。
 *
 * ## 本組守的是「教師知不知道學員看到了什麼」
 *
 * #631 把「編輯」與「學員看到」拆成兩個時點，而已發布課程的內容讀取回的是**暫存版**
 * ——教師在畫面上看得到自己剛加的章節，與「學員也看得到」在視覺上毫無分別。整個功能
 * 的新風險集中在這一點，所以提示文字與按鈕狀態都要有測試釘住。
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
    // `useBlocker` 在此會拋錯。以「永不攔截」取代，站內離開的攔截屬 e2e 行為
    //（比照 `DmEditorPage.test.tsx` 與 `QuizAnswerPage.test.tsx`）。
    useBlocker: () => ({ state: "unblocked", proceed: () => {}, reset: () => {} }),
  }
})

// 🔴 `navigateSpy` 必須逐條清掉——它由 `vi.hoisted` 建立，整個檔案共用同一個實例。
//
// ⚠️ 本檔是五個 `CourseEditorPage.*.test.tsx` 裡**唯一漏掉這段**的（其餘四檔都有），
// 而它一直沒出事：#720 之前本檔沒有任何測試會 `navigate`，所以「上一條留下的呼叫」
// 根本不存在。#720 讓「更新」成功後回列表，殘留才第一次有東西可殘。
//
// ⇒ 這類缺口的性質：**不是被改壞的，是本來就缺、只是沒有路徑到得了**。
beforeEach(() => {
  navigateSpy.mockClear()
})

/**
 * 以指定狀態、擁有權與暫存狀態覆蓋課程詳細。
 *
 * `pending` 對應後端的 `has_pending_changes`：有尚未按下「更新」的內容編輯。
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
        is_closed: false,
      }),
    ),
  )
}

function renderEditor() {
  paramsRef.current = { courseId: "1" }
  return renderWithProviders(<EtCourseEditorPage />)
}

/**
 * 項目列上「開啟」用的那顆按鈕。
 *
 * ⚠️ 不能直接 `getByRole("button", { name: /標題/ })`——同一列的**拖曳手把**也是
 * `role="button"`，而它的 `aria-label` 是「拖曳調整「標題」順序」，同一個正則會中兩個。
 * 症狀是 `Found multiple elements`，而不是找不到。
 */
async function _openItemButton(title: RegExp): Promise<HTMLElement> {
  const all = await screen.findAllByRole("button", { name: title })
  const opener = all.find((el) => !el.getAttribute("aria-label")?.startsWith("拖曳"))
  if (!opener) throw new Error(`找不到開啟項目的按鈕：${title}`)
  return opener
}

/**
 * 已發布課程 + 一個**本次編輯新增**的項目（教材與測驗的 id 都是負數）。
 *
 * 🔴 `-12` / `-13` 這種負數正是後端暫存模式回給教師的 id（`exposed_id`）。整份 MSW 的
 * 預設 fixture 全是正數，所以「教師建了東西 → 拿到負數 → 用它開視窗 → 存檔」這條路徑
 * 在本檔之前**一次都沒有被執行過**。
 */
function useCourseWithStagedItems() {
  server.use(
    http.get("/api/et/courses/:courseId", () =>
      HttpResponse.json({
        course_id: 1,
        course_name: "採血作業訓練",
        description: null,
        status: "PUBLISHED",
        open_start_at: "2026-09-01T00:00:00Z",
        open_end_at: "2027-09-30T00:00:00Z",
        require_approval: false,
        version: 5,
        owner_id: "U1",
        owner_name: "王教師",
        is_owner: true,
        audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
        invitation_code: "01234567",
        has_pending_changes: true,
        is_closed: false,
        chapters: [
          {
            chapter_id: -10,
            chapter_name: "暫存新章",
            sort_order: 1,
            version: 0,
            items: [
              {
                item_id: -11,
                item_type: "MATERIAL",
                title: "暫存教材",
                sort_order: 1,
                material_id: -12,
                quiz_id: null,
                version: 0,
                question_count: null,
              },
              {
                item_id: -13,
                item_type: "QUIZ",
                title: "暫存測驗",
                sort_order: 2,
                material_id: null,
                quiz_id: -14,
                version: 0,
                question_count: 0,
              },
            ],
          },
        ],
      }),
    ),
  )
}

describe("ET05 更新（#631）", () => {
  it.each([["PUBLISHED"], ["CLOSED"]])(
    "%s 課程顯示「更新」鈕（關閉期間的編輯同樣要按更新才生效）",
    async (status) => {
      useCourse(status, { pending: true })
      renderEditor()
      expect(await screen.findByRole("button", { name: "更新" })).toBeEnabled()
    },
  )

  it("草稿不顯示「更新」鈕——草稿的編輯直接寫活表，沒有要更新的東西", async () => {
    useCourse("DRAFT")
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")

    expect(screen.queryByRole("button", { name: "更新" })).not.toBeInTheDocument()
    // 正向錨點：草稿有自己那顆（少了它，上一條在「整列按鈕都沒畫出來」時也會通過）
    expect(screen.getByRole("button", { name: "儲存並發布" })).toBeInTheDocument()
  })

  it("🔴 沒有暫存變更時「更新」鈕**仍可按**，只是提示不說有變更（#720）", async () => {
    // ## 這條與 #631 當時的斷言**方向相反**
    //
    // #631：沒有暫存變更時「更新」鈕停用（理由是「按了也沒事做」）。
    //
    // #720 之後基本資料也由這顆鈕送出，於是出現 2026-10-19 手測回報的第二個現象：
    // **教師改了課名，暫存區還是空的，鈕卻按不下去**——他看得到自己的修改，卻沒有任何
    // 方法讓它生效，而畫面上沒有一句話解釋為什麼。
    //
    // ⇒ 停用條件整個拿掉。暫存區真的沒東西時後端是安全的 no-op（`applied_count = 0`，
    // 訊息為「目前沒有需要更新的變更」），不需要前端先擋。
    //
    // ⛔ 不要為了「按了沒事做很怪」而把 `disabled` 加回來：那會讓基本資料永遠送不出去。
    useCourse("PUBLISHED", { pending: false })
    renderEditor()

    expect(await screen.findByRole("button", { name: "更新" })).toBeEnabled()
    expect(screen.getByText(/按「更新」才整批對學員生效/)).toBeInTheDocument()
    expect(screen.queryByText(/有尚未更新的變更/)).not.toBeInTheDocument()
  })

  it("🔴 編輯問卷之後「有尚未更新的變更」立即出現——不需離開頁面再進來", async () => {
    // 2026-10-19 手測回報：改了問卷，「更新」維持灰色按不下去，要先離開編輯頁再進來。
    //
    // 根因是 `invalidateSurvey` 只刷了問卷查詢、沒刷課程詳細，而 `has_pending_changes`
    // 住在課程詳細裡。後端其實已經翻成 true 了，前端讀的是過期快取。
    //
    // ⚠️ **#720 換了可觀察的症狀，根因與守的東西不變。** 「更新」鈕不再因為旗標而變灰
    // （那個停用條件本身就是手測回報的第二個現象，已拿掉），所以改以提示文字斷言——
    // 它由**同一個** `has_pending_changes` 驅動，過期快取一樣會讓它不出現。
    //
    // ⛔ 不要因為「鈕已經不會變灰了」就刪掉本條：那會讓 `invalidateSurvey` 的刷新範圍
    // 失去唯一的守門，而那正是當初那個 bug 的所在。
    //
    // ⚠️ 本條的 fixture 必須讓旗標**真的會變**（`pending` 隨 POST 翻成 true），否則不論
    // 有沒有刷新都讀到同一個值，測試會恆綠——那就驗不到任何東西了。
    let pending = false
    server.use(
      http.get("/api/et/courses/:courseId", () =>
        HttpResponse.json({
          course_id: 1,
          course_name: "採血作業訓練",
          description: null,
          status: "PUBLISHED",
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
          has_pending_changes: pending,
          is_closed: false,
        }),
      ),
      http.post("/api/et/courses/:courseId/survey", () => {
        pending = true // 後端：問卷進了暫存區，旗標翻成 true
        return HttpResponse.json(
          { survey_id: -7, survey_name: "訓後滿意度", is_active: true, version: 0, questions: [] },
          { status: 201 },
        )
      }),
    )
    const user = userEvent.setup()
    renderEditor()
    // 正向錨點：旗標翻轉**之前**提示不在，否則「之後它出現」無法歸因於刷新
    expect(await screen.findByRole("button", { name: "更新" })).toBeEnabled()
    expect(screen.queryByText(/有尚未更新的變更/)).not.toBeInTheDocument()

    await user.click(await screen.findByRole("button", { name: "新增問卷" }))
    await user.type(await screen.findByRole("textbox", { name: /問卷名稱/ }), "訓後滿意度")
    await user.click(screen.getByRole("button", { name: "建立" }))
    // ⚠️ 建立成功後問卷視窗會開著，整個背景被 `aria-hidden`——此時查不到「更新」，
    // 而 `getByRole` 落空會讓 `waitFor` 一路重試到逾時（看起來像功能壞了）。
    // 關掉視窗是教師本來就會做的下一步，不是為了遷就測試。
    await user.click(await screen.findByRole("button", { name: "關閉視窗" }))

    // ⚠️ 關閉時問卷還有未存的題目編輯器展開著，頁面會先跳一次確認（SurveyDialog 的
    // `onClose(dirty)` 契約）。背景同樣被 `aria-hidden`，所以要先把它關掉。
    await user.click(await screen.findByRole("button", { name: "確定" }))

    expect(await screen.findByText(/有尚未更新的變更/)).toBeInTheDocument()
  })

  it("🔴 有暫存變更時提示明寫「只有你看得到」——本功能的新風險就在這句話上", async () => {
    // 少了它，教師編完直接離開會以為學員已經看到了，而下一次知道真相的時機是學員反映
    // 「課程沒有更新」。反向斷言（上一條的 queryByText）與這條用同一種查法。
    useCourse("PUBLISHED", { pending: true })
    renderEditor()

    expect(await screen.findByText(/有尚未更新的變更/)).toBeInTheDocument()
    expect(screen.getByText(/目前只有你看得到/)).toBeInTheDocument()
  })

  it("按下「更新」先二次確認，確認後才送出；確認內容說明刪除會連帶移除學員進度", async () => {
    // 這一下會同時影響所有在籍學員，且被刪掉的章節 / 項目會連帶移除其進度與作答。
    const user = userEvent.setup()
    let applies = 0
    useCourse("PUBLISHED", { pending: true })
    server.use(
      http.post("/api/et/courses/:courseId/content/apply", () => {
        applies += 1
        return HttpResponse.json({ course_id: 1, applied_count: 3 })
      }),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "更新" }))

    expect(await screen.findByText(/學習進度與測驗作答會一併移除/)).toBeInTheDocument()
    expect(applies).toBe(0) // 確認前不送出

    await user.click(screen.getByRole("button", { name: "確認更新" }))

    await waitFor(() => expect(applies).toBe(1))
    expect(await screen.findByText("課程內容已更新，學員已可看到")).toBeInTheDocument()
  })

  it("暫存區是空的（applied_count 0）時不報「已更新」——那是一件沒發生的事", async () => {
    // 按鈕平時由 `has_pending_changes` 擋著按不到，但那個旗標會過期：另一個分頁剛按過
    // 更新時就會走到這條路。後端此時是安全的 no-op，訊息也要照實講。
    const user = userEvent.setup()
    useCourse("PUBLISHED", { pending: true })
    server.use(
      http.post("/api/et/courses/:courseId/content/apply", () =>
        HttpResponse.json({ course_id: 1, applied_count: 0 }),
      ),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "更新" }))
    await user.click(await screen.findByRole("button", { name: "確認更新" }))

    expect(await screen.findByText("目前沒有需要更新的變更")).toBeInTheDocument()
    expect(screen.queryByText("課程內容已更新，學員已可看到")).not.toBeInTheDocument()
  })

  it("檢核未通過（422 ET_PUBLISH_001）時列出缺漏，並說明編輯仍保留在暫存區", async () => {
    // 🔴 「編輯仍保留」是這個視窗與發布那個最大的差別：教師按下更新被擋，第一個念頭是
    // 「我剛才改的東西還在嗎」。不講，他會從頭再改一次。
    const user = userEvent.setup()
    useCourse("PUBLISHED", { pending: true })
    server.use(
      http.post("/api/et/courses/:courseId/content/apply", () =>
        HttpResponse.json(
          {
            error_code: "ET_PUBLISH_001",
            error_message: "更新條件未滿足",
            blockers: [{ code: "CHAPTER_EMPTY", message: "章節至少須有 1 份教材或測驗", target_id: 11 }],
          },
          { status: 422 },
        ),
      ),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "更新" }))
    await user.click(await screen.findByRole("button", { name: "確認更新" }))

    const dialog = await screen.findByRole("dialog", { name: "更新未生效" })
    expect(await within(dialog).findByText(/章節至少須有 1 份教材或測驗/)).toBeInTheDocument()
    expect(within(dialog).getByText(/編輯仍保留在暫存區/)).toBeInTheDocument()
    expect(screen.queryByText("課程內容已更新，學員已可看到")).not.toBeInTheDocument()
  })

  /** 讓「更新」固定以問卷凍結被擋下。 */
  function useFrozenSurvey() {
    server.use(
      http.post("/api/et/courses/:courseId/content/apply", () =>
        HttpResponse.json(
          { error_code: "ET_SURVEY_003", error_message: "已有學員填答，題目與選項不可修改" },
          { status: 422 },
        ),
      ),
    )
  }

  it("🔴 問卷凍結（422 ET_SURVEY_003）開的是**帶出口的視窗**，不是一則訊息", async () => {
    // 原本它走 handleError 變成一則 toast——那是告訴教師他卡住了，卻不告訴他怎麼出來。
    // 而他真的出不來：把題目改回原樣也沒用（選項是全量覆寫、識別碼換新），整門課的
    // 更新都過不去（#712）。
    const user = userEvent.setup()
    useCourse("PUBLISHED", { pending: true })
    useFrozenSurvey()
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "更新" }))
    await user.click(await screen.findByRole("button", { name: "確認更新" }))

    expect(await screen.findByRole("button", { name: "放棄問卷的編輯" })).toBeInTheDocument()
    expect(screen.getByText(/把題目改回原樣/)).toBeInTheDocument()
    // 用與缺漏那條**同一種查法**：凍結不是「少了什麼」，不該混進缺漏清單
    expect(screen.queryByRole("dialog", { name: "更新未生效" })).not.toBeInTheDocument()
  })

  it("🔴 按「放棄問卷的編輯」只打問卷那支，不打放棄全部那支", async () => {
    // ⚠️ 兩支端點只差一個路徑段（`/content/stage` vs `/content/stage/survey`），打錯的
    // 後果是教師**丟掉整門課這一輪的全部編輯**——而畫面上看起來一樣成功。
    const user = userEvent.setup()
    const 打過的 : string[] = []
    useCourse("PUBLISHED", { pending: true })
    useFrozenSurvey()
    server.use(
      http.delete("/api/et/courses/:courseId/content/stage/survey", () => {
        打過的.push("survey")
        return new HttpResponse(null, { status: 204 })
      }),
      http.delete("/api/et/courses/:courseId/content/stage", () => {
        打過的.push("all")
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "更新" }))
    await user.click(await screen.findByRole("button", { name: "確認更新" }))

    await user.click(await screen.findByRole("button", { name: "放棄問卷的編輯" }))

    await waitFor(() => expect(打過的).toEqual(["survey"]))
    expect(await screen.findByText(/其餘編輯仍保留/)).toBeInTheDocument()
    // 留在原地——教師接下來要做的是再按一次「更新」，不是被導走
    expect(navigateSpy).not.toHaveBeenCalled()
  })

  it("凍結視窗按「關閉」什麼都不放棄", async () => {
    // 🔴 正向錨點：少了它，把「關閉」接到放棄的 mutation 上也會讓上一條通過，
    // 而那會讓一個只想看清楚狀況的教師丟掉問卷的編輯。
    const user = userEvent.setup()
    const 打過的: string[] = []
    useCourse("PUBLISHED", { pending: true })
    useFrozenSurvey()
    server.use(
      http.delete("/api/et/courses/:courseId/content/stage/survey", () => {
        打過的.push("survey")
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "更新" }))
    await user.click(await screen.findByRole("button", { name: "確認更新" }))

    await user.click(await screen.findByRole("button", { name: "關閉" }))

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "放棄問卷的編輯" })).not.toBeInTheDocument(),
    )
    expect(打過的).toEqual([])
  })

  it("🔴 按「取消」會放棄暫存的編輯——編輯工作階段的第二個出口", async () => {
    // 暫存模式讓編輯有兩個出口：按「更新」套用，或按「取消」放棄。原本只做了前者，
    // 教師編到一半想整個丟掉沒有任何入口（2026-10-16 使用者裁示補上）。
    const user = userEvent.setup()
    let discards = 0
    useCourse("PUBLISHED", { pending: true })
    server.use(
      http.delete("/api/et/courses/:courseId/content/stage", () => {
        discards += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "取消" }))

    // 放棄是不可復原的，確認視窗要講清楚，並指出「只是想離開」該怎麼做
    expect(await screen.findByText(/回到學員目前看到的版本/)).toBeInTheDocument()
    expect(discards).toBe(0) // 確認前不送出

    await user.click(screen.getByRole("button", { name: "放棄並離開" }))

    await waitFor(() => expect(discards).toBe(1))
    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith("/et/courses"))
  })

  it("沒有暫存變更時按「取消」直接離開，不跳確認也不打 API", async () => {
    // 正向錨點：少了它，讓確認視窗無條件跳出也會讓上一條通過——而那會變成
    // 「每次想離開編輯頁都被問一次要不要放棄」。
    const user = userEvent.setup()
    let discards = 0
    useCourse("PUBLISHED", { pending: false })
    server.use(
      http.delete("/api/et/courses/:courseId/content/stage", () => {
        discards += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderEditor()
    await user.click(await screen.findByRole("button", { name: "取消" }))

    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith("/et/courses"))
    expect(discards).toBe(0)
    expect(screen.queryByText(/回到學員目前看到的版本/)).not.toBeInTheDocument()
  })

  it("草稿按「取消」只離開——草稿沒有暫存可放棄", async () => {
    // ⚠️ 草稿的章節與項目直接寫活表，按「取消」本來就不還原（issue 原文：草稿維持
    // 現行、不需版本化）。打了那支端點後端會回 409，所以前端這裡就不該打。
    const user = userEvent.setup()
    let discards = 0
    useCourse("DRAFT")
    server.use(
      http.delete("/api/et/courses/:courseId/content/stage", () => {
        discards += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderEditor()
    await screen.findByDisplayValue("採血作業訓練")
    await user.click(screen.getByRole("button", { name: "取消" }))

    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith("/et/courses"))
    expect(discards).toBe(0)
  })

  it("🔴 開啟本次新增的教材：以負數 id 取詳細、存檔也送負數", async () => {
    // review 當初指出的缺陷就是這個形狀：後端對已發布課程回負數 `material_id`，而
    // `/materials/{id}` 的 `Path(ge=1)` 把它擋成 422 ⇒ **教師打不開自己剛建的教材**。
    // 後端那側已放寬，本條釘住前端真的會用那個負數去打（而不是自己過濾掉或取絕對值）。
    const user = userEvent.setup()
    const seen: string[] = []
    useCourseWithStagedItems()
    server.use(
      // 🔴 **字面路徑必須排在動態路徑前面**：`server.use()` 是前插，`:materialId` 會把
      // `/materials/video-upload-limits` 一起吃掉，`MaterialDialog` 就拿不到上傳限制而
      // 整個元件崩潰（`describeVideoLimits` 對 undefined 呼叫 `.join`）。
      // 症狀是「找不到那個 dialog」，很像元件寫錯。
      http.get("/api/et/materials/video-upload-limits", () =>
        HttpResponse.json({ allowed_formats: ["mp4", "webm"], max_size_mb: 500 }),
      ),
      http.get("/api/et/materials/:materialId", ({ params }) => {
        seen.push(`GET ${params.materialId}`)
        return HttpResponse.json({
          material_id: Number(params.materialId),
          material_name: "暫存教材",
          description_html: "<p>說明</p>",
          version: 0,
          videos: [],
          docs: [],
        })
      }),
      http.put("/api/et/materials/:materialId", ({ params }) => {
        seen.push(`PUT ${params.materialId}`)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderEditor()

    await user.click(await _openItemButton(/暫存教材/))

    await waitFor(() => expect(seen).toContain("GET -12"))
    expect(await screen.findByRole("dialog", { name: /教材/ })).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "儲存" }))

    await waitFor(() => expect(seen).toContain("PUT -12"))
  })

  it("🔴 開啟本次新增的測驗：以負數 id 取詳細", async () => {
    const user = userEvent.setup()
    const seen: string[] = []
    useCourseWithStagedItems()
    server.use(
      http.get("/api/et/quizzes/:quizId", ({ params }) => {
        seen.push(`GET ${params.quizId}`)
        return HttpResponse.json({
          quiz_id: Number(params.quizId),
          quiz_name: "暫存測驗",
          description: null,
          pass_score: 60,
          time_limit_min: null,
          max_retry: 3,
          version: 0,
          points_total: 0,
          answers_visible: true,
          affected_count: 0,
          questions: [],
        })
      }),
    )
    renderEditor()

    await user.click(await _openItemButton(/暫存測驗/))

    await waitFor(() => expect(seen).toContain("GET -14"))
  })

  it("正向錨點：既有內容仍以正數 id 取詳細", async () => {
    // 少了這條，前端若把**所有** id 都加上負號（或都取絕對值）也會讓上面兩條通過。
    const user = userEvent.setup()
    const seen: string[] = []
    useCourse("PUBLISHED", { pending: true })
    server.use(
      http.get("/api/et/courses/:courseId", () =>
        HttpResponse.json({
          course_id: 1,
          course_name: "採血作業訓練",
          description: null,
          status: "PUBLISHED",
          open_start_at: "2026-09-01T00:00:00Z",
          open_end_at: "2027-09-30T00:00:00Z",
          require_approval: false,
          version: 5,
          owner_id: "U1",
          owner_name: "王教師",
          is_owner: true,
          audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
          invitation_code: "01234567",
          has_pending_changes: true,
          is_closed: false,
          chapters: [
            {
              chapter_id: 10,
              chapter_name: "既有章節",
              sort_order: 1,
              version: 0,
              items: [
                {
                  item_id: 11,
                  item_type: "MATERIAL",
                  title: "既有教材",
                  sort_order: 1,
                  material_id: 12,
                  quiz_id: null,
                  version: 0,
                  question_count: null,
                },
              ],
            },
          ],
        }),
      ),
      // 字面路徑排在動態路徑前面（理由見上一條測試的註解）
      http.get("/api/et/materials/video-upload-limits", () =>
        HttpResponse.json({ allowed_formats: ["mp4", "webm"], max_size_mb: 500 }),
      ),
      http.get("/api/et/materials/:materialId", ({ params }) => {
        seen.push(`GET ${params.materialId}`)
        return HttpResponse.json({
          material_id: Number(params.materialId),
          material_name: "既有教材",
          description_html: null,
          version: 0,
          videos: [],
          docs: [],
        })
      }),
    )
    renderEditor()

    await user.click(await _openItemButton(/既有教材/))

    await waitFor(() => expect(seen).toContain("GET 12"))
  })

  it("非擁有者（檢視模式）看不到「更新」鈕", async () => {

    // ⚠️ 刻意餵 `pending: true`（後端對他人恆回 false）：要驗的是**前端自己那道
    // `readOnly` 閘**，不是「旗標剛好是 false 所以按鈕沒亮」。餵 false 的話，把
    // `readOnly` 拿掉這條照樣通過。
    useCourse("PUBLISHED", { isOwner: false, pending: true })
    renderEditor()
    await screen.findByText(/檢視模式/)

    expect(screen.queryByRole("button", { name: "更新" })).not.toBeInTheDocument()
  })
})
