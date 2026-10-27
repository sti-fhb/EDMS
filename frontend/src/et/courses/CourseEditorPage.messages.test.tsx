import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtCourseEditorPage } from "./CourseEditorPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/**
 * ET05 視窗與提示訊息的**內容安全網**（#814）。
 *
 * ## 這個檔為什麼必須在改排版「之前」就全綠
 *
 * #814 的界線是 **⛔ 一個字都不刪，只改視覺層級**。那幾段之所以長，是因為每一句都有
 * 被加入的理由（刪除的連帶後果、2026-10-17 裁示把「要求重測」延到按更新才執行、檢核
 * 不通過的保證）。砍掉任一條都會讓某個教師踩到沒預期的副作用。
 *
 * 🔴 **先改再補測試＝沒有安全網**：那樣寫出來的斷言是照著「改完的結果」寫的，刪掉的
 * 句子不會出現在斷言裡，「有沒有刪字」這件事就沒有任何東西在驗。本檔因此先對**現況**
 * 程式碼建立、確認全綠，之後才動 `content` 的排版。
 *
 * ## 斷言為什麼比對 `textContent` 而不是 `getByText`
 *
 * 排版改成 JSX（`<strong>`、`<li>`、`<Typography>`）之後，**同一句話會被切到不同元素**，
 * `getByText("整句")` 會查不到而失敗——那是查詢方式的問題，不是文案少了字。⇒ 一律對
 * 整個 dialog 的 `textContent` 做 `toContain`，它不受元素切分影響。
 *
 * ## 兩支視窗原本完全沒有測試
 *
 * 「更新課程內容」（A1）與「停用課後問卷」（A10）在本檔之前**零覆蓋**。這與 #763 的
 * 離開提示是同一種結構性盲區：沒人寫得到的東西，改壞了也沒人會紅。
 */

const { navigateSpy, paramsRef, locationRef, blockerRef } = vi.hoisted(() => ({
  navigateSpy: vi.fn(),
  paramsRef: { current: { courseId: "1" } as Record<string, string | undefined> },
  locationRef: { current: { pathname: "/et/courses/1", state: null } as { pathname: string; state: unknown } },
  // 🔴 離開攔截可控（比照 `CourseEditorPage.reopen.test.tsx`）——固定回 `unblocked`
  // 會讓 A4 / A5 那支視窗結構性地測不到。
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
    useBlocker: () => blockerRef.current,
  }
})

beforeEach(() => {
  navigateSpy.mockClear()
  locationRef.current = { pathname: "/et/courses/1", state: null }
  blockerRef.current = { state: "unblocked", proceed: vi.fn(), reset: vi.fn() }
})

function renderEditor(courseId = "1") {
  paramsRef.current = { courseId }
  return renderWithProviders(<EtCourseEditorPage />)
}

function mockCourse(
  status: string,
  {
    pending = false,
    isClosed = status === "CLOSED",
    kept = false,
    survey = null as null | Record<string, unknown>,
  } = {},
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
        is_owner: true,
        audiences: [{ unit_tag_id: 101, tag_id: 2, label: "護理師" }],
        chapters: [],
        invitation_code: "01234567",
        has_pending_changes: pending,
        is_closed: isClosed,
        has_kept_edits: kept,
      }),
    ),
    http.get("/api/et/courses/:courseId/survey", () => HttpResponse.json(survey)),
  )
}

/** 開啟視窗後回傳它的純文字內容——排版改 JSX 後仍可用。 */
async function dialogText() {
  const dialog = await screen.findByRole("dialog")
  return dialog.textContent ?? ""
}

/**
 * 每支視窗的「必須留著的句子」。
 *
 * ⛔ **刪句子就是刪這裡的一行**——#814 的全部價值在「同樣的資訊更好讀」，改版面時順手
 * 精簡掉一句，這個陣列就是唯一會攔下它的地方。
 */
const SENTENCES = {
  A1: [
    "更新後，自上次更新以來的所有編輯會同時對學員生效。",
    "本次若刪除了章節或項目，學員在其中的學習進度與測驗作答會一併移除，完課狀態隨之重算。",
    "本次若曾選擇「要求重測」，作答過的學員會在此刻重新計算作答次數、退回未完成並各收到一封通知信。",
    "系統會重跑一次發布檢核，未通過時不會更新任何內容。",
  ],
  A2: [
    "關閉後學員無法加入、累積學習進度、開始新的測驗作答或填寫課後問卷，邀請碼與 Email 邀請一併暫時失效。",
    "已加入的學員仍可唯讀回看內容與成績，作答中的測驗可完成並計分。課程內容於關閉期間仍可編輯，之後可再開課。",
  ],
  A2_PENDING: [
    "您有尚未按「更新」的編輯，關閉後這些編輯不會保留。",
    "若要保留，請先關閉此視窗，再按頁面上的「更新」。",
  ],
  A3: [
    "取消後，自上次更新以來的所有編輯會全部放棄，課程回到學員目前看到的版本。此動作無法復原。",
    "離開本頁同樣會放棄這些編輯；要讓學員看到，請按「更新」。",
  ],
  A3_CLOSED: ["若只是想先離開、下次再繼續，請改按「保留編輯」。"],
  A4: ["離開後，自上次更新以來的所有編輯都會放棄，課程維持學員目前看到的版本。要讓學員看到這些編輯，請先按「更新」。"],
  A4_CLOSED: ["離開後，自上次更新以來的所有編輯都會放棄。若想留著下次再繼續，請先按「保留編輯」；要讓學員看到，請按「更新並重開課」。"],
  A5: ["你先前按過「保留編輯」，這些編輯會留到下次進來。要讓學員看到，請按「更新並重開課」；要整份丟掉，請按「取消」。"],
  A7: [
    "確定刪除這門草稿課程？其下的章節、教材、測驗與課後問卷會一併移除，且無法復原。",
    "草稿尚未發布，沒有學員受影響。",
  ],
  // 🔴 A10 是 A 區**唯一會改字**的一支（#814 Q1 裁示：與 #804 的卡片提示對齊）。
  // 後半「已填寫的內容仍保留。確定停用？」不變，前半換成卡片的講法。
  A10: ["停用後學員看不到此問卷，已填寫的內容仍保留。確定停用？"],
} as const

const ACTIVE_SURVEY = {
  survey_id: 31,
  survey_name: "訓後滿意度調查",
  is_active: true,
  version: 0,
  questions: [{ question_id: 1, question_text: "整體滿意度", question_type: "SINGLE", sort_order: 1, options: [] }],
}

describe("ET05 視窗訊息內容安全網（#814）", () => {
  describe("A1 更新課程內容——🔴 本檔之前零覆蓋", () => {
    async function openApplyDialog() {
      mockCourse("PUBLISHED", { pending: true })
      server.use(
        http.put("/api/et/courses/:courseId", () => HttpResponse.json({ course_id: 1, version: 6 })),
        http.get("/api/et/courses/:courseId/publish-check", () => HttpResponse.json({ blockers: [] })),
      )
      const user = userEvent.setup()
      renderEditor()
      await user.click(await screen.findByRole("button", { name: "更新" }))
      return dialogText()
    }

    // ⚠️ 顯式 15 秒：本組每條都要跑 `stageBasic` 的 PUT → 課程詳細 refetch →
    // `publish-check` 三次往返才開得出視窗，乾淨機器上第一條實測 2982ms（整檔第一條
    // 還要吃冷啟動），預設 5 秒的餘裕不足以撐過 CI 的完整負載。
    // 比照本目錄既有的 `}, 15000)` 與 `REOPEN_FLOW_TIMEOUT`。
    it.each(SENTENCES.A1)(
      "保留原句：%s",
      async (sentence) => {
        expect(await openApplyDialog()).toContain(sentence)
      },
      15000,
    )
  })

  describe("A2 關閉課程", () => {
    async function openCloseDialog(pending = false) {
      mockCourse("PUBLISHED", { pending })
      const user = userEvent.setup()
      renderEditor()
      await user.click(await screen.findByRole("button", { name: "關閉課程" }))
      return dialogText()
    }

    it.each(SENTENCES.A2)("保留原句：%s", async (sentence) => {
      expect(await openCloseDialog()).toContain(sentence)
    })

    it.each(SENTENCES.A2_PENDING)("有待更新編輯時另外保留：%s", async (sentence) => {
      expect(await openCloseDialog(true)).toContain(sentence)
    })
  })

  describe("A3 放棄本次的編輯", () => {
    async function openCancelDialog(status = "PUBLISHED") {
      mockCourse(status, { pending: true })
      const user = userEvent.setup()
      renderEditor()
      await user.click(await screen.findByRole("button", { name: "取消" }))
      return dialogText()
    }

    it.each(SENTENCES.A3)("保留原句：%s", async (sentence) => {
      expect(await openCancelDialog()).toContain(sentence)
    })

    it.each(SENTENCES.A3_CLOSED)("已關閉課程另外保留：%s", async (sentence) => {
      expect(await openCancelDialog("CLOSED")).toContain(sentence)
    })
  })

  describe("A4 / A5 離開提示——同一個 confirm 的三個分支", () => {
    // 🔴 A4 與 A5 **不是兩支視窗**：同一處（`CourseEditorPage.tsx` 的離開攔截）由
    // `hasKeptEdits` 分流，而 A4 自己又有 `reopening` 二分。改 A4 的排版必然動到 A5 的
    // 渲染結構 ⇒ 三個分支各要一組安全網。
    async function openLeaveDialog(opts: { status?: string; kept?: boolean }) {
      mockCourse(opts.status ?? "PUBLISHED", { pending: true, kept: opts.kept ?? false })
      blockerRef.current = { state: "blocked", proceed: vi.fn(), reset: vi.fn() }
      renderEditor()
      return dialogText()
    }

    it.each(SENTENCES.A4)("A4 已發布版保留原句：%s", async (sentence) => {
      expect(await openLeaveDialog({})).toContain(sentence)
    })

    it.each(SENTENCES.A4_CLOSED)("A4 已關閉版保留原句：%s", async (sentence) => {
      expect(await openLeaveDialog({ status: "CLOSED" })).toContain(sentence)
    })

    it.each(SENTENCES.A5)("🔴 A5 一字不改（逐字完整比對，2026-10-27 裁示）：%s", async (sentence) => {
      // ⚠️ 裁示要求**逐字完整比對**，⛔ 不用 regex 片段——片段比對會讓「刪掉後半句」
      // 照樣通過，而 A5 被列為「不動」，正向錨點必須守得住整句。
      const text = await openLeaveDialog({ status: "CLOSED", kept: true })
      expect(text).toContain(sentence)
      expect(within(await screen.findByRole("dialog")).getByText("離開後編輯仍會保留")).toBeInTheDocument()
    })
  })

  describe("A7 刪除草稿", () => {
    async function openDeleteDraftDialog() {
      mockCourse("DRAFT")
      const user = userEvent.setup()
      renderEditor()
      await user.click(await screen.findByRole("button", { name: "刪除草稿" }))
      return dialogText()
    }

    it.each(SENTENCES.A7)("保留原句：%s", async (sentence) => {
      expect(await openDeleteDraftDialog()).toContain(sentence)
    })
  })

  describe("A10 停用課後問卷——🔴 本檔之前零覆蓋", () => {
    async function openDeactivateDialog() {
      mockCourse("PUBLISHED", { survey: ACTIVE_SURVEY })
      const user = userEvent.setup()
      renderEditor()
      await user.click(await screen.findByRole("button", { name: "停用問卷" }))
      return dialogText()
    }

    it.each(SENTENCES.A10)("改為與卡片對齊的講法：%s", async (sentence) => {
      expect(await openDeactivateDialog()).toContain(sentence)
    })

    it("🔴 舊的「不再顯示填寫入口」已不再出現（負向錨點）", async () => {
      // 少了這條，把新句**加在**舊句旁邊也會讓上一條通過——而那是兩種講法並存，
      // 正是本案要消除的狀態。
      expect(await openDeactivateDialog()).not.toContain("不再顯示填寫入口")
    })

    it("⛔ SurveySection 卡片那句不動——方向是視窗向卡片對齊，不是反過來", async () => {
      // #804 有測試釘住卡片那句；這裡再加一道，避免日後有人為了「統一」而去動它。
      const { default: surveySource } = await import("./SurveySection.tsx?raw")
      expect(surveySource).toContain("停用中，學員看不到此問卷")
    })
  })

  describe("B 區訊息——⛔ 不在本案改動範圍者的正向錨點", () => {
    // issue #814 只改 B2、B7 兩條，其餘**一字不改**。少了這組，改版時順手統一語氣
    // 把別條也改掉不會有任何測試紅。
    //
    // ⚠️ 這幾條散在各 mutation 的 `onSuccess`，要渲染到得各自造一次成功的 API 往返，
    // 成本與脆弱度都高；而本組要守的只是「**字沒被改**」⇒ 以原始碼字面比對即足夠。
    // `?raw` 是 Vite 內建的匯入方式，不需額外設定。
    const UNCHANGED = [
      '"草稿已儲存"', // B1
      '"教材已儲存"', // B3
      '"測驗已儲存"', // B3
      '"課程內容已更新，學員已可看到"', // B4
      '"目前沒有需要更新的變更"', // B5
      '"編輯已保留，學員看到的仍是關閉前的內容"', // B6
      '"草稿已刪除"', // B8
      "已放棄課後問卷的編輯，其餘編輯仍保留。請再按一次", // B9（含 `${applyLabel}` 插值，只比對固定段）
      '"可能有上次未更新的編輯殘留，請先確認畫面內容再按「更新」"', // B10
    ]

    it.each(UNCHANGED)("原始碼中逐字保留：%s", async (literal) => {
      const { default: source } = await import("./CourseEditorPage.tsx?raw")
      expect(source).toContain(literal)
    })

    it("🔴 B2 / B7 已改掉，且舊字串不再殘留", async () => {
      const { default: source } = await import("./CourseEditorPage.tsx?raw")
      expect(source).toContain('"已先將課程存成草稿"') // B2
      expect(source).toContain('"課程已關閉，學員已無法加入"') // B7

      // 🔴 負向錨點：少了這兩行，**把新字串加在舊的旁邊**也會讓上面通過。
      // ⚠️ B7 的舊字串是新字串的前綴，所以要連右引號一起比對——寫成
      // `not.toContain("課程已關閉")` 會把正確的新字串也判成殘留。
      expect(source).not.toContain('"已自動儲存草稿"')
      expect(source).not.toContain('"課程已關閉"')
    })
  })
})
