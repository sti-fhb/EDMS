import ArrowBackIcon from "@mui/icons-material/ArrowBack"
import ContentCopyIcon from "@mui/icons-material/ContentCopy"
import LockIcon from "@mui/icons-material/Lock"
import LockOpenIcon from "@mui/icons-material/LockOpen"
import PersonAddIcon from "@mui/icons-material/PersonAdd"
import VisibilityIcon from "@mui/icons-material/Visibility"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogContentText from "@mui/material/DialogContentText"
import DialogTitle from "@mui/material/DialogTitle"
import FormControlLabel from "@mui/material/FormControlLabel"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Switch from "@mui/material/Switch"
import Tooltip from "@mui/material/Tooltip"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs"
import { DateTimePicker } from "@mui/x-date-pickers/DateTimePicker"
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider"
import { zhTW } from "@mui/x-date-pickers/locales"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import dayjs from "dayjs"
import type { Dayjs } from "dayjs"
import "dayjs/locale/zh-tw"
import { useEffect, useRef, useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router-dom"

import { ChapterSection } from "./ChapterSection"
import { MaterialDialog } from "./MaterialDialog"
import { InviteStudentsDialog } from "./InviteStudentsDialog"
import { NewItemDialog } from "./NewItemDialog"
import { PublishDialog } from "./PublishDialog"
import { QuizDialog } from "./QuizDialog"
import { RequireRetestDialog } from "./RequireRetestDialog"
import { SurveyDialog } from "./SurveyDialog"
import { SurveySection } from "./SurveySection"
import { BlockerDialog } from "./BlockerDialog"
import { coursesApi } from "./coursesService"
import { validateReopenSchedule } from "./reopenSchedule"
import {
  blockerHighlights,
  checkCourseForm,
  FORM_BLOCKER,
  mergeBlockers,
  PUBLISH_FORM_OWNED,
  REOPEN_FORM_OWNED,
} from "./publishCheck"
import type { MaterialSavePayload } from "./MaterialDialog"
import type { ItemRow, ItemType, QuestionFormValues, QuestionRow } from "./itemSchemas"
import { itemsApi, materialsApi, quizzesApi } from "./itemsService"
import { publishApi, surveyApi } from "./surveyService"
import type {
  PublishBlocker,
  PublishResult,
  SurveyQuestionFormValues,
  SurveyQuestionRow,
} from "./surveySchemas"
import {
  COURSE_STATUS_LABEL,
  ChapterNameSchema,
  DESCRIPTION_MAX_LEN,
  audienceKey,
  validateAudiences,
  type AudienceDraft,
  type ChapterItem,
  type CourseDetail,
  type CoursePayload,
} from "./schemas"
import { CourseAudiencePairs } from "./CourseAudiencePairs"
import { ownerLabel } from "./schemas"
import { ScreenHeader } from "../../components/ScreenHeader"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"

/** 樂觀鎖衝突之 error code——後端 `ensure_version_matched` 於版本不符時回此碼。 */
const LOCK_CONFLICT = "ET_LOCK_001"

const EMPTY_FORM = {
  course_name: "",
  description: "",
  require_approval: false,
  // 新增課程預帶一列空白配對（比照 #476 DM03）：一進畫面就看得到要成對設定，而非一顆「新增」鈕
  audiences: [{ unit_tag_id: null, tag_id: null }] as AudienceDraft[],
}

/**
 * ET05 課程建立與編輯（US3；骨架 #202、教材 / 測驗 #203、問卷與發布 #204）。
 *
 * 動作列：取消 / 儲存草稿 / **儲存並發布**（僅草稿狀態顯示——已發布課程的編輯即時
 * 生效、不需重新發布，見 AC 28）。
 *
 * **非擁有者為唯讀**（`spec.md` §擁有權判定）：顯示檢視模式提示，所有輸入停用、
 * 操作按鈕不顯示。後端另以 `ET_COURSE_002` 把關，前端隱藏僅為 UX。
 */
/** 自動存草稿後要接著建立的項目（#335）——由 navigate state 跨元件重新掛載帶過去。 */
interface PendingAddItem {
  chapterIndex: number
  itemType: ItemType
  /**
   * 項目名稱（#414）。
   *
   * ⚠️ **名稱在導向之前就問完**，不是到了編輯頁再問——後者等於在使用者眼前先換一次
   * 頁再跳視窗，而且重新整理就遺失。名稱隨 navigate state 一起過去。
   */
  title: string
}

/**
 * 自動存草稿後要接著建立的問卷（#435）——與 `PendingAddItem` 同一個機制、不同的 key。
 *
 * ⚠️ 刻意不與 `pendingAddItem` 合併成一個帶 `kind` 的聯合型別：兩者到達後要做的事
 * 不同（項目要依索引反查 `chapter_id`、問卷直接掛 `course_id`），合併只會讓接手的
 * effect 變成一個對兩種形狀分岔的函式，而它們之間沒有共用邏輯。
 */
interface PendingAddSurvey {
  /** 問卷名稱。理由同 `PendingAddItem.title`：在導向之前就問完。 */
  surveyName: string
}

/**
 * 起訖時間選擇器的顯示格式（#564）——與 `utils/date.ts` 的 `formatDateTime` 相同：
 * 年/月/日、24 小時制。
 *
 * MUI 預設是 `MM/DD/YYYY hh:mm A`：月日年順序與系統其他地方相反，而 `12:00 AM` 是**午夜**、
 * 容易被看成中午。訖止時間決定課程何時自動關閉，看錯就設錯。
 *
 * ⚠️ 只改**顯示**：選擇器的值仍是 `Dayjs`，送出時照舊 `toISOString()`。
 *
 * ⚠️ **這個格式有兩條獨立的來源**：本常數，以及 `adapterLocale="zh-tw"`（dayjs 的 zh-tw
 * 語系本身就是 `YYYY/MM/DD` + 24 小時制 `HH:mm`）。2026-10-08 變異檢查：單獨拿掉任一條，
 * 畫面不變、測試全綠；兩條都拿掉才變回 `MM/DD/YYYY hh:mm A`。故顯示測試守的是「至少留一條」。
 * 仍明寫本常數：格式是本系統的決定，不該依賴語系資料的預設值（語系若改了，這裡撐住）。
 * `ampm={false}` 同理——zh-tw 下為 no-op，留給時間面板在語系換成 12 小時制時仍維持 24 小時。
 */
const PICKER_FORMAT = "YYYY/MM/DD HH:mm"

/** 選擇器的介面文字（月曆的月份與星期、「取消／確認」按鈕等）用繁體中文（#564）。 */
const PICKER_LOCALE_TEXT = zhTW.components.MuiLocalizationProvider.defaultProps.localeText

export function EtCourseEditorPage() {
  const { courseId: courseIdParam } = useParams<{ courseId: string }>()
  const courseId = courseIdParam ? Number(courseIdParam) : undefined
  const navigate = useNavigate()
  const location = useLocation()
  const qc = useQueryClient()
  /*
    #455：教材視窗的上傳說明與 `accept` 改讀 `DP_PARAM`。

    ⚠️ 查詢放在**頁面**而非 `MaterialDialog`——後者是純呈現元件，既有測試直接以
    props 渲染它，在裡面加查詢會讓每一條測試都得準備 MSW handler。
  */
  const { data: videoLimits } = useQuery({
    queryKey: QUERY_KEYS.etMaterial.videoUploadLimits(),
    queryFn: materialsApi.getVideoUploadLimits,
  })
  const { message, confirm } = useNotification()

  const [form, setForm] = useState(EMPTY_FORM)
  const [startAt, setStartAt] = useState<Dayjs | null>(null)
  const [endAt, setEndAt] = useState<Dayjs | null>(null)
  // 載入時的原值——「起始須 ≥ 當下」只對**使用者這次改動的值**成立（SA 裁示）。
  // 已發布課程的起始必然落在過去，無條件檢核會讓它之後永遠存不了檔。
  const [originalStart, setOriginalStart] = useState<string | null>(null)
  // 新增模式之章節暫存：章節有 COURSE_ID 外鍵、課程不存在時掛不上去，
  // 故先存在畫面上，儲存時連同課程一次送出（後端於同一交易內建立）。
  //
  // ⚠️ **id 必須穩定、不可由索引推導**：`ChapterRow` 以 `chapter_id` 當 React key 且
  // 內部以 state 保存章節名草稿。若 id 為 `-(index + 1)`，拖拉後陣列順序變了但 key 仍
  // 照位置排列，React 會重用同一批元件實例、其內部草稿不更新——畫面看起來「拖了沒動」。
  const [stagedChapters, setStagedChapters] = useState<{ id: number; name: string }[]>([])
  const nextStagedId = useRef(-1)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [audienceErrors, setAudienceErrors] = useState<Record<number, string>>({})
  const [conflictOpen, setConflictOpen] = useState(false)
  const [chapterDialogOpen, setChapterDialogOpen] = useState(false)
  const [chapterDraft, setChapterDraft] = useState("")
  const [chapterError, setChapterError] = useState("")
  /** 目前開啟的項目視窗——`null` 表示未開啟。 */
  const [openItem, setOpenItem] = useState<ItemRow | null>(null)
  const [itemError, setItemError] = useState<string | null>(null)
  /** 上傳影片的錯誤與其他錯誤分開——它要顯示在上傳區旁邊，不是視窗頂端。 */
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  /**
   * 剛建立、**尚未儲存過**的項目 ID。
   *
   * 新增項目會於 DB 建立項目（教材 / 測驗與 `ET_ITEM` 同交易），使用者若直接取消，那個
   * 只有名稱、沒有內容的項目會留在章節裡。取消時把它刪掉，章節才不會長出一排幽靈項目。
   * 儲存成功後清除此標記——之後的取消就只是「不存這次的修改」。
   *
   * ⚠️ #414 起**名稱已於建立前取得**，故此處清理的不再是「沒有名稱的空殼」，而是
   * 「有名稱但沒有內容的項目」。清理本身仍然需要。
   */
  const [unsavedNewItemId, setUnsavedNewItemId] = useState<number | null>(null)
  /**
   * 等待教師決定「是否要求已通過學員重測」的動作（#361）。
   *
   * ⚠️ `useState` 把函式參數當成 updater，存函式一定要包一層 `() => fn`，
   * 否則 React 會呼叫它、把回傳值存進 state。
   */
  const [pendingRetestAction, setPendingRetestAction] = useState<((requireRetest: boolean) => void) | null>(null)
  /**
   * 已選好型別、等待命名的新項目（#414）。
   *
   * ⚠️ 名稱問完才呼叫 `itemsApi.add`——在此之前 DB 裡什麼都沒有，取消即真的什麼都
   * 沒發生。這正是本 issue 要的：空殼原本在按下「新增項目」的當下就落地了。
   */
  const [namingItem, setNamingItem] = useState<{ chapter: ChapterItem; itemType: ItemType } | null>(null)
  const [creatingItem, setCreatingItem] = useState(false)
  /** 問卷區塊的錯誤（凍結、選項不足等）——與項目視窗的錯誤分開顯示於問卷卡片內。 */
  const [surveyError, setSurveyError] = useState<string | null>(null)
  const [surveyOpen, setSurveyOpen] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)
  const [blockers, setBlockers] = useState<PublishBlocker[]>([])
  const [publishResult, setPublishResult] = useState<PublishResult | null>(null)
  /**
   * 再開課「就地編輯」模式（#428）。
   *
   * 🔴 **進入模式時只清空畫面上的欄位，DB 完全不動。** 教師中途反悔時按「取消再開課」
   * 即可還原（值從 `course` 取回），不會留下一門起訖時間被清掉的課程——這是本設計最
   * 容易漏的一塊，原本的對話框有「取消」，就地編輯沒有。
   *
   * ⛔ 不要改成「進入模式就先送一次清空的更新」：那會讓反悔變成需要補救的狀態，而且
   * 中途關掉瀏覽器就回不去了。
   */
  const [reopening, setReopening] = useState(false)
  /**
   * 再開課重跑發布檢核的缺漏——與 `blockers`（發布用）分開。
   *
   * 共用一份會讓兩個視窗互相污染：發布視窗殘留的缺漏會在再開課視窗一開就顯示，
   * 而那可能是上一次發布嘗試留下的，跟這次再開課無關。
   */
  const [reopenBlockers, setReopenBlockers] = useState<PublishBlocker[]>([])
  /**
   * 標示模式（#558）：缺漏視窗關閉後，缺漏處以紅框標示，**補好即消失**。
   *
   * 值表示是哪一條流程的缺漏——兩者要框的欄位不同（再開課的起訖時間規則與發布**相反**，
   * 見 `submitReopen`）。`null`＝不標示。
   *
   * ⚠️ 紅框一律依**目前的資料即時重算**，不是記住視窗開啟那一刻的清單：表單欄位每次
   * render 重跑 `checkCourseForm`，章節以下的內容由 `publishCheckQuery` 隨每次寫入重抓。
   */
  const [highlight, setHighlight] = useState<null | "publish" | "reopen">(null)

  const {
    data: course,
    error: courseError,
    isLoading: courseLoading,
    isFetching: courseFetching,
  } = useQuery({
    queryKey: QUERY_KEYS.etCourses.detail(courseId ?? 0),
    queryFn: () => coursesApi.getDetail(courseId as number),
    enabled: courseId !== undefined,
    // 403 / 404 重試沒有意義，只會延後畫面上的錯誤呈現
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })
  const { data: tagOptions = [] } = useQuery({
    queryKey: QUERY_KEYS.etCourses.tags(courseId),
    queryFn: () => coursesApi.listTags(courseId),
  })
  /**
   * 課程之課後問卷。**尚未建立時後端回 `null`（200）**，不是錯誤。
   *
   * `data` 為 `undefined` 代表尚在載入，`null` 代表確定沒有問卷——`SurveySection`
   * 靠這個區別決定要不要讓「新增問卷」可按。
   */
  const { data: survey } = useQuery({
    queryKey: QUERY_KEYS.etCourses.survey(courseId ?? 0),
    queryFn: () => surveyApi.get(courseId as number),
    enabled: courseId !== undefined,
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })
  /**
   * 內建問卷模板清單（#238）。
   *
   * 只在問卷視窗開著時才抓——模板是純靜態資料，但沒必要在每次進課程編輯頁時
   * 都多送一個請求；教師多數時候根本不會開問卷視窗。
   */
  const { data: surveyTemplates = [] } = useQuery({
    queryKey: QUERY_KEYS.etCourses.surveyTemplates(),
    queryFn: surveyApi.listTemplates,
    enabled: surveyOpen,
    staleTime: Infinity,
  })
  /**
   * 標示模式下的發布預檢（#558）——章節以下的紅框依它即時更新。
   *
   * 重抓由 `refreshLiveCheck` 觸發（`invalidate` / `invalidateQuiz` / `invalidateSurvey` 都會
   * 呼叫它），不靠 query 的自動重抓：預檢與發布 / 再開課共用後端每人每分鐘 20 次的限流
   * （security review MEDIUM），故
   * - 不在切回分頁時重抓、不自動重試（429 / 403 重試只會再吃掉配額）
   * - 短時間內的多次寫入合併成一次重抓（見 `refreshLiveCheck`）
   * - 非擁有者不啟用（縱深防禦：正常操作到不了這裡，後端也會 403）
   */
  const { data: liveCheck } = useQuery({
    queryKey: QUERY_KEYS.etCourses.publishCheck(courseId ?? 0),
    queryFn: () => publishApi.check(courseId as number),
    enabled: highlight !== null && courseId !== undefined && course?.is_owner === true,
    refetchOnWindowFocus: false,
    retry: false,
  })

  // 由查詢結果衍生表單初值——**於 render 期間同步，不放 useEffect**。
  // 除了 effect 內 setState 會造成串聯 render 之外，更實際的問題是：每次 refetch
  // （新增章節後 invalidate 即會觸發）都重設表單，會把使用者正在輸入的內容蓋掉。
  // 只在「載入到另一門課程」時同步，重新整理既有課程不動使用者已改的欄位。
  //
  // 🔴 **必須等 `courseFetching` 落定才預帶**（#578 手測回報）。重進編輯頁時
  // TanStack Query（staleTime 0）會先**同步**吐出快取裡的舊課程、同時在背景 refetch；
  // 此時若就預帶，上面這個一次性 guard 會被舊值填滿並從此鎖住，稍後回來的新值再也
  // 寫不進表單——使用者改完名稱存檔、列表已是新的，點進編輯頁卻仍是舊值。
  // DM 編輯頁的 #377 是同一個形狀（見 `DmEditorPage.tsx` 的標籤預帶）。
  const [loadedCourseId, setLoadedCourseId] = useState<number | null>(null)
  if (course && !courseFetching && loadedCourseId !== course.course_id) {
    setLoadedCourseId(course.course_id)
    setForm({
      course_name: course.course_name,
      description: course.description ?? "",
      require_approval: course.require_approval,
      audiences: course.audiences.map(({ unit_tag_id, tag_id }) => ({ unit_tag_id, tag_id })),
    })
    setAudienceErrors({})
    setStartAt(course.open_start_at ? dayjs(course.open_start_at) : null)
    setEndAt(course.open_end_at ? dayjs(course.open_end_at) : null)
    setOriginalStart(course.open_start_at)
    // 🔴 **再開課模式也要跟著退出**（#428 code review 的 HIGH）。
    //
    // `courses/:courseId` 這條路由沒有 `key={courseId}`，React Router 只換參數時**不會
    // 重新掛載元件**，故 `reopening` 會跟著使用者從課程 A 帶到課程 B（上一頁 / 下一頁、
    // 直接改網址都會走到）。結果是一門根本不是關閉中的課程顯示著再開課模式：一般儲存
    // 被擋死，而按下「確認再開課」是對**錯的課程**送出請求。
    setReopening(false)
    setReopenBlockers([])
    setHighlight(null)
  }

  const isNew = courseId === undefined
  const readOnly = course !== undefined && !course.is_owner
  const [inviteOpen, setInviteOpen] = useState(false)
  // 新增模式以負數 id 表示暫存章節（尚未寫入 DB）；index = -id - 1
  const chapters: ChapterItem[] = isNew
    ? stagedChapters.map((c, i) => ({
        chapter_id: c.id,
        chapter_name: c.name,
        sort_order: i + 1,
        version: 0,
        // 暫存章節尚未寫入 DB，項目要等課程存檔後才掛得上（#335 之自動存草稿接手）
        items: [],
      }))
    : (course?.chapters ?? [])
  const status = course?.status ?? "DRAFT"


  /** 版本衝突以 Dialog 呈現而非 snackbar——使用者必須確實知道自己的編輯沒存進去。 */
  const handleError = (err: unknown) => {
    const { errorCode, errorMessage } = toApiError(err)
    if (errorCode === LOCK_CONFLICT) {
      setConflictOpen(true)
      return
    }
    message.error(errorMessage)
  }

  /**
   * 標示模式下，課程內容有寫入就重查預檢——**合併 400ms 內的多次呼叫**。
   *
   * 一個動作常會連續觸發兩次失效（例如儲存測驗設定同時呼叫 `invalidateQuiz` 與
   * `invalidate`），而已送出的 HTTP 請求取消不了、後端照樣計入限流。不在標示模式時，
   * 失效一個停用中的 query 不會發出請求。
   */
  const liveCheckTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const refreshLiveCheck = () => {
    if (courseId === undefined) return
    if (liveCheckTimer.current !== null) clearTimeout(liveCheckTimer.current)
    liveCheckTimer.current = setTimeout(() => {
      liveCheckTimer.current = null
      void qc.invalidateQueries({ queryKey: QUERY_KEYS.etCourses.publishCheck(courseId) })
    }, 400)
  }
  useEffect(
    () => () => {
      if (liveCheckTimer.current !== null) clearTimeout(liveCheckTimer.current)
    },
    [],
  )

  const invalidate = () => {
    if (courseId !== undefined) {
      void qc.invalidateQueries({ queryKey: QUERY_KEYS.etCourses.detail(courseId) })
    }
    refreshLiveCheck()
  }

  /** 起始時間是否被使用者改動——決定送出前要不要驗「不得早於當下」。 */
  const startChanged = (startAt?.toISOString() ?? null) !== originalStart

  /**
   * 起始時間可選範圍的下限——**一開始就套用**，過去的時間即為灰底不可選。
   *
   * 例外：課程已開課（原起始落在過去）時，下限放寬到**原值**而非當下。否則已開課課程
   * 一進編輯頁，既有的起始時間就落在不可選範圍內，教師無從沿用（AC 28 允許已發布課程
   * 繼續編輯）。放寬到原值仍擋住「把開課時間再往前挪」。
   */
  const startedInPast = originalStart !== null && dayjs(originalStart).isBefore(dayjs())
  const startFloor = startedInPast ? dayjs(originalStart) : dayjs()

  /**
   * 再開課模式下**一進入就是紅框**（欄位空著即為未完成），不等按下「確認再開課」。
   *
   * 裁示原文是「清空課程開始和結束的時間，並用紅色框起來提醒使用者重新設定時間」——
   * 紅框本身就是提醒，等送出才變紅等於少了一次提示。
   *
   * ⚠️ 紅框歸紅框，**helperText 仍只在送出後才出現**：一進畫面就跳「請重新設定…」是對
   * 還沒動手的人報錯，看起來像自己做錯了什麼。
   */
  const reopenStartEmpty = reopening && startAt === null
  const reopenEndEmpty = reopening && endAt === null

  const formInput = { form, startAt, endAt, startChanged, startFloor, startedInPast }
  /**
   * 畫面上實際顯示的欄位錯誤。
   *
   * 標示模式下**每次 render 依目前的值重算**（補好即消失，使用者裁示 4）；其餘時候沿用
   * 「按下儲存草稿那一刻」記下的 `errors`（草稿的行為不變，裁示 3）。
   */
  const publishLive = highlight === "publish" ? checkCourseForm(formInput, { forPublish: true }) : null
  const fieldErrors = publishLive?.fieldErrors ?? errors
  const audienceRowErrors = publishLive?.audienceRowErrors ?? audienceErrors
  // ⚠️ 再開課用自己的時間規則（起始可早於當下），不可套 `checkCourseForm`——見 `submitReopen`
  const reopenFieldErrors = highlight === "reopen" ? validateReopenSchedule(startAt, endAt, dayjs()) : {}

  const toPayload = (): CoursePayload => ({
    course_name: form.course_name.trim(),
    description: form.description.trim() || null,
    // Dayjs → ISO 8601（含時區）；後端欄位為 TIMESTAMPTZ，送 naive 值會被以連線時區
    // 解讀而靜默位移，使「起始時間前學員不可見」等時間判定算錯。
    open_start_at: startAt?.toISOString() ?? null,
    open_end_at: endAt?.toISOString() ?? null,
    require_approval: form.require_approval,
    // 只送完整配對；不完整 / 重複的列已由 `validateForm` 擋在送出前
    audiences: validateAudiences(form.audiences).payload,
  })

  const saveMut = useMutation({
    mutationFn: async () => {
      if (isNew) return coursesApi.create({ ...toPayload(), chapters: stagedChapters.map((c) => c.name) })
      await coursesApi.update(courseId, { ...toPayload(), version: course?.version ?? 0 })
      return undefined
    },
    onSuccess: () => {
      message.success("草稿已儲存")
      // 對齊 wireframe「儲存後：回到課程列表卡片網格」；新增 / 編輯皆同。
      // 章節是各自即時儲存的，不會因離開編輯頁而遺失。
      navigate("/et/courses")
    },
    onError: handleError,
  })

  const chapterMut = useMutation({
    mutationFn: async (action: () => Promise<unknown>) => action(),
    onSuccess: invalidate,
    onError: (err) => {
      handleError(err)
      invalidate() // 還原樂觀更新（如重排失敗）
    },
  })

  const invalidateSurvey = () => {
    if (courseId !== undefined) {
      void qc.invalidateQueries({ queryKey: QUERY_KEYS.etCourses.survey(courseId) })
    }
    // 問卷不經 `invalidate()`，要另外觸發，問卷的紅框才會補好即消失（#558）
    refreshLiveCheck()
  }

  /**
   * 問卷相關操作統一經此執行。
   *
   * 錯誤顯示在**問卷卡片內**而非 snackbar：凍結（`ET_SURVEY_003`）與選項不足
   * （`ET_SURVEY_004`）都是「這一區塊的狀態不允許」，訊息貼著出問題的地方才看得懂。
   * 版本衝突仍走 `handleError` 的 Dialog——那要使用者確實知道編輯沒存進去。
   */
  const surveyMut = useMutation({
    mutationFn: async (action: () => Promise<unknown>) => action(),
    onSuccess: () => {
      setSurveyError(null)
      invalidateSurvey()
    },
    onError: (err) => {
      const { errorCode, errorMessage } = toApiError(err)
      if (errorCode === LOCK_CONFLICT) {
        handleError(err)
      } else {
        setSurveyError(errorMessage)
      }
      invalidateSurvey() // 還原樂觀更新（如重排失敗）
    },
  })

  /**
   * 問後端缺漏，與前端缺漏合併成同一份清單（#558，使用者裁示 1）。
   *
   * `formBlockers` 非空時表單**沒有存檔**——後端讀的是已存檔版本，`mergeBlockers` 會以前端
   * 判定取代後端的起訖／受訓對象兩項，避免清單與畫面矛盾。
   */
  const checkMut = useMutation({
    mutationFn: async (formBlockers: PublishBlocker[]) => ({
      result: await publishApi.check(courseId as number),
      formBlockers,
    }),
    onSuccess: ({ result, formBlockers }) => {
      seedLiveCheck(result.blockers)
      setBlockers(mergeBlockers(formBlockers, result.blockers, PUBLISH_FORM_OWNED))
    },
    onError: (err, formBlockers) => {
      handleError(err)
      // 後端問不到時，前端那份仍要讓教師看到——否則按了發布什麼都沒發生
      if (formBlockers.length > 0) setBlockers(formBlockers)
      else setPublishOpen(false)
    },
  })

  /** 把剛拿到的後端缺漏放進標示模式的快取——關掉視窗的當下紅框就在，不必等重抓。 */
  const seedLiveCheck = (backend: PublishBlocker[]) => {
    if (courseId === undefined) return
    qc.setQueryData(QUERY_KEYS.etCourses.publishCheck(courseId), {
      can_publish: backend.length === 0,
      blockers: backend,
    })
  }

  const publishMut = useMutation({
    mutationFn: () => publishApi.publish(courseId as number),
    onSuccess: (result) => {
      setPublishResult(result)
      invalidate()
    },
    onError: (err) => {
      // 發布端點會重跑檢核——若在預檢之後條件變了，這裡會拿到帶 blockers 的 422。
      // 直接把它顯示出來，使用者不必再按一次才知道哪裡不對。
      const { errorCode, payload } = toApiError(err)
      const returned = (payload as { blockers?: PublishBlocker[] } | undefined)?.blockers
      if (errorCode === "ET_PUBLISH_001" && returned) {
        seedLiveCheck(returned)
        setBlockers(returned)
        return
      }
      handleError(err)
      setPublishOpen(false)
    },
  })

  /**
   * 「儲存並發布」的第一步——**先把當前編輯存檔**，成功後才開視窗跑檢核。
   *
   * 少了這步，教師剛在畫面上填好起訖時間、還沒存就按發布，檢核讀到的是資料庫裡
   * **尚未更新**的舊值，會回報「課程起訖時間須填寫完整」——而欄位裡明明填著。
   * 按鈕寫的是「儲存並發布」，行為也該如此。
   *
   * 與 `saveMut` 分開是因為那條成功後會導回課程列表（對齊 wireframe「儲存後回到
   * 卡片網格」），發布流程要留在原頁把結果視窗開起來。
   */
  const saveThenCheckMut = useMutation({
    mutationFn: () => coursesApi.update(courseId as number, { ...toPayload(), version: course?.version ?? 0 }),
    onSuccess: () => {
      invalidate()
      setBlockers([])
      setPublishResult(null)
      setPublishOpen(true)
      checkMut.mutate([])
    },
    onError: handleError,
  })

  /**
   * 「儲存並發布」（#558）：按下 → 視窗列出全部缺漏 → 關閉後缺漏處標紅框。
   *
   * - 表單沒問題：照舊先存檔再預檢（理由見 `saveThenCheckMut`）
   * - 表單有問題：**不存檔**（存不進去），直接以已存檔版本預檢，兩邊合併成一份清單
   *
   * ⚠️ 此刻**不寫入 `errors`**：紅框在視窗關閉後才出現（標示模式），視窗開著的時候
   * 背景先紅一片，等於同一件事講兩次。
   */
  const openPublish = () => {
    const { blockers: formBlockers } = checkCourseForm(formInput, { forPublish: true })
    if (formBlockers.length === 0) {
      setErrors({})
      setAudienceErrors({})
      saveThenCheckMut.mutate()
      return
    }
    setBlockers([])
    setPublishResult(null)
    setPublishOpen(true)
    checkMut.mutate(formBlockers)
  }

  // ── 關閉 / 再開課（US11 / #288）──────────────────────────────────────────

  /**
   * 關閉前的確認——關閉會立刻影響**所有在籍學員**，不是只影響操作者自己。
   *
   * 內容列出會停掉的四件事：學員無從得知課程為何突然不能操作，教師按下去之前就該
   * 知道自己關掉了什麼。可逆這件事也要說，否則教師會誤以為這是不可回復的動作而不敢按。
   *
   * ⚠️ 錯誤在 `onOk` 內就地 catch（比照 `handleDeleteChapter`）——讓 rejection 逃出去
   * 會使 `NotificationContext` 刻意保留確認視窗，而版本衝突另有自己的 Dialog，
   * 兩個視窗會疊在一起。
   */
  const requestClose = () => {
    confirm({
      title: "關閉課程",
      content:
        "關閉後學員無法加入、累積學習進度、開始新的測驗作答或填寫課後問卷，邀請碼與 Email 邀請一併暫時失效。" +
        "已加入的學員仍可唯讀回看內容與成績，作答中的測驗可完成並計分。課程內容於關閉期間仍可編輯，之後可再開課。",
      // 「確認關閉」而非「關閉課程」：與標題列那顆同名會讓畫面上同時存在兩個同名
      // 按鈕（無障礙名稱重複）。措辭亦與「確認發布」/「確認再開課」一致。
      okText: "確認關閉",
      onOk: async () => {
        try {
          await coursesApi.close(courseId as number, course?.version ?? 0)
          message.success("課程已關閉")
          invalidate()
        } catch (err) {
          handleError(err)
        }
      },
    })
  }

  /**
   * 刪除草稿（#457）。
   *
   * ⚠️ 措辭寫「**無法復原**」是誠實的：後端確實是軟刪（`DELETED=1`，#202 SA 裁示 Q1），
   * 但**沒有任何還原入口**——對教師而言就是不可逆。寫「可還原」會是假承諾。
   *
   * ⚠️ 錯誤在 `onOk` 內就地 catch（比照 `requestClose` 與 `handleDeleteChapter`）——
   * 讓 rejection 逃出去會使 `NotificationContext` 刻意保留確認視窗，與其他錯誤 Dialog
   * 疊在一起。
   *
   * 導回列表而非留在原頁：課程已經不存在，留下來只會是一個查詢失敗的空殼。
   */
  const requestDeleteDraft = () => {
    confirm({
      title: "刪除草稿",
      content:
        "確定刪除這門草稿課程？其下的章節、教材、測驗與課後問卷會一併移除，且無法復原。" +
        "草稿尚未發布，沒有學員受影響。",
      okText: "確認刪除",
      onOk: async () => {
        try {
          await coursesApi.remove(courseId as number)
          message.success("草稿已刪除")
          navigate("/et/courses")
        } catch (err) {
          handleError(err)
        }
      },
    })
  }

  const reopenMut = useMutation({
    /**
     * 422 `ET_PUBLISH_001` 在 `mutationFn` 內就地轉成「顯示缺漏」，**不往外拋**。
     *
     * 走 `onError` 的話 `mutateAsync` 仍會 reject，而缺漏並不是一個需要 toast 的失敗
     * ——視窗裡已經逐條列出來了。#284 在問卷送出的 409 上踩過這個坑：`onError` 處理
     * 完之後 promise 照樣 reject，外層看到的是「操作失敗」。
     */
    mutationFn: async (payload: { openStartAt: string; openEndAt: string }) => {
      try {
        return await coursesApi.reopen(courseId as number, {
          open_start_at: payload.openStartAt,
          open_end_at: payload.openEndAt,
          version: course?.version ?? 0,
        })
      } catch (err) {
        const { errorCode, payload: body } = toApiError(err)
        const returned = (body as { blockers?: PublishBlocker[] } | undefined)?.blockers
        if (errorCode === "ET_PUBLISH_001" && returned) {
          seedLiveCheck(returned)
          setReopenBlockers(returned)
          return undefined
        }
        throw err
      }
    },
    onSuccess: (result, variables) => {
      // `undefined` = 檢核未通過，缺漏已以對話框顯示（#509），模式要留著讓教師處理
      if (result === undefined) return
      message.success("課程已再開課")
      setReopening(false)
      setReopenBlockers([])
      setHighlight(null)
      // 🔴 **起始時間的基準值要跟著走**（#428 順帶修掉的既有缺陷）。
      //
      // 表單初值的 guard 是 `loadedCourseId !== course.course_id`——只在載入到**另一門**
      // 課程時才重設。`invalidate()` 重抓的是同一門課，故 `originalStart` 會停在再開課
      // **之前**的值，本頁便繼續以它當起始時間的下限：教師把課程補開在更早的日期
      // （後端允許）之後，再編任何欄位按儲存就會被「不可再往前調整」擋住，而錯誤訊息
      // 指的正是他剛剛才成功送出的時間。
      //
      // ⛔ 不可改成放寬那道 guard：它擋的是「每次 refetch 都把使用者正在輸入的內容蓋掉」
      // （見其註解）。本路徑知道新值是什麼，直接寫回即可。
      //
      // ⚠️ 刻意取 `variables` 而非 `result.open_start_at`：`originalStart` 是拿去跟
      // `startAt?.toISOString()` 做**字串**比較的（見 `startChanged`），而伺服器格式
      // （`...T01:00:00Z`）與 dayjs 的（`...T01:00:00.000Z`）不相等，改用回應值會讓
      // `startChanged` 恆真。要換來源必須一併正規化格式。
      //
      // ℹ️ 起訖時間**不需要**在此寫回——值是教師在本頁上輸入的，本來就停在畫面上
      //（2026-09-24 變異檢查：拿掉 `setStartAt` / `setEndAt` 全部測試照樣綠）。
      setOriginalStart(variables.openStartAt)
      invalidate()
    },
    onError: handleError,
  })

  /** 進入再開課模式：**只清空畫面**，DB 不動（#428）。 */
  const enterReopen = () => {
    setReopenBlockers([])
    setHighlight(null)
    setStartAt(null)
    setEndAt(null)
    setReopening(true)
  }

  /** 取消再開課：把欄位還原成伺服器上的值。 */
  const cancelReopen = () => {
    setReopening(false)
    setReopenBlockers([])
    setHighlight(null)
    setStartAt(course?.open_start_at ? dayjs(course.open_start_at) : null)
    setEndAt(course?.open_end_at ? dayjs(course.open_end_at) : null)
  }

  /**
   * 確認再開課。
   *
   * ⚠️ 用 `validateReopenSchedule` 而非本頁的 `validateForm`——兩者的起始時間規則**相反**：
   * 本頁擋「起始早於當下」，而再開課刻意允許（「補開一段已經開始的期間」是合理操作，
   * 見 `reopenSchedule.ts`）。用錯會擋掉後端允許的合法操作，而畫面上沒有任何線索。
   */
  const submitReopen = () => {
    const next = validateReopenSchedule(startAt, endAt, dayjs())
    const formBlockers: PublishBlocker[] = []
    if (next.start) formBlockers.push({ code: FORM_BLOCKER.start, message: next.start, target_id: null })
    if (next.end) formBlockers.push({ code: FORM_BLOCKER.end, message: next.end, target_id: null })
    if (formBlockers.length === 0) {
      reopenMut.mutate({ openStartAt: startAt!.toISOString(), openEndAt: endAt!.toISOString() })
      return
    }
    // 時間有錯就不送再開課，但仍問後端其餘缺漏，一次列完（#558，使用者裁示 1、5）
    reopenCheckMut.mutate(formBlockers)
  }

  /** 再開課版的「前端有錯時仍問後端」——結果放進 `reopenBlockers`，不與發布那份共用。 */
  const reopenCheckMut = useMutation({
    mutationFn: async (formBlockers: PublishBlocker[]) => ({
      result: await publishApi.check(courseId as number),
      formBlockers,
    }),
    onSuccess: ({ result, formBlockers }) => {
      seedLiveCheck(result.blockers)
      // 再開課只判過時間——受訓對象的缺漏要照後端的列（見 `REOPEN_FORM_OWNED`）
      setReopenBlockers(mergeBlockers(formBlockers, result.blockers, REOPEN_FORM_OWNED))
    },
    onError: (err, formBlockers) => {
      handleError(err)
      setReopenBlockers(formBlockers)
    },
  })

  /**
   * 缺漏項目所指的測驗名稱——後端只回 `target_id`，名稱由前端自課程詳細對照。
   *
   * `items` 以 `?? []` 兜底：後端恆回此欄位，但少一個欄位不該讓整個編輯頁白畫面
   * （比照 `ItemList` 的同名預設值，#203 已踩過一次）。
   */
  const quizNames: Record<number, string> = {}
  for (const chapter of chapters) {
    for (const item of chapter.items ?? []) {
      if (item.quiz_id !== null && item.quiz_id !== undefined) quizNames[item.quiz_id] = item.title
    }
  }

  // `CHAPTER_EMPTY` 的 target_id 是 chapter_id，與 quiz_id 是兩個獨立序號——
  // 各自一份對照表，`PublishDialog` 依 code 決定查哪一份（#358 第 3 項）。
  const chapterNames: Record<number, string> = {}
  for (const chapter of chapters) {
    chapterNames[chapter.chapter_id] = chapter.chapter_name
  }

  /**
   * `ITEM_NO_TITLE` 的 target_id 是 item_id，但**那個項目依定義沒有名字可顯示**
   * （#384）——所以這裡對照的不是項目名稱，是**它所屬的章節名稱**。
   *
   * 查 `itemNames` 會永遠落空、永遠退回裸訊息，教師就看不出是哪一個項目；改標章節
   * 至少把他帶到正確的段落。
   */
  const itemChapterNames: Record<number, string> = {}
  for (const chapter of chapters) {
    for (const item of chapter.items ?? []) {
      itemChapterNames[item.item_id] = chapter.chapter_name
    }
  }

  /** 章節以下要框的元素（#558）；非標示模式一律不框。 */
  const highlights = blockerHighlights(highlight !== null ? (liveCheck?.blockers ?? []) : [], chapters)

  /**
   * 儲存草稿前的基本資料驗證——有錯時寫進 `errors`（逐欄標示）並回 `false`。
   *
   * 不檢「發布才必填」的項目（使用者裁示 3）；發布走 `openPublish`。
   * 規則本體在 `checkCourseForm`，與發布、標示模式共用同一份。
   */
  const validateForm = (): boolean => {
    const { fieldErrors: next, audienceRowErrors: rows } = checkCourseForm(formInput, { forPublish: false })
    setErrors(next)
    setAudienceErrors(rows)
    return Object.keys(next).length === 0 && Object.keys(rows).length === 0
  }

  const handleSave = () => {
    // 🔴 **再開課模式下絕不走一般更新。**
    //
    // `enterReopen()` 把 `startAt` / `endAt` 清成 `null`，而這兩個正是 `toPayload()` 送給
    // `PUT /courses/{id}` 的 `open_start_at` / `open_end_at`。後端這兩欄是選填（草稿允許
    // 留空）且為全量覆寫，故一個帶 `null` 的 PUT 會把課程的開放期間**寫成 NULL**——而且
    // 不會報錯：教師看到「已儲存」，學員卻再也進不來。
    //
    // ⛔ 不可只靠「再開課模式不顯示儲存鈕」擋（本次 security review 的 MEDIUM-1）。那是
    // 把資料寫入的防線放在呈現層，日後任何人加回一顆儲存鈕、加自動存草稿（#335 的機制
    // 已存在於新增模式）或把動作列抽成共用元件，都會靜默打開這條路。
    if (reopening) return
    if (validateForm()) saveMut.mutate()
  }

  /**
   * 新增章節（對齊 wireframe 之 modal）。
   *
   * `keepOpen` 對應 wireframe 的「儲存並繼續新增」——留在對話框並重設欄位，
   * 讓教師一次建完多個章節而不必反覆開關。
   */
  const submitChapter = async (keepOpen: boolean) => {
    const parsed = ChapterNameSchema.safeParse(chapterDraft)
    if (!parsed.success) {
      setChapterError(parsed.error.issues[0].message)
      return
    }
    setChapterError("")
    if (isNew) {
      setStagedChapters((prev) => [...prev, { id: nextStagedId.current--, name: parsed.data }])
      setChapterDraft("")
      if (!keepOpen) setChapterDialogOpen(false)
      return
    }
    try {
      await coursesApi.addChapter(courseId, parsed.data)
      invalidate()
      setChapterDraft("")
      if (!keepOpen) setChapterDialogOpen(false)
    } catch (err) {
      handleError(err)
    }
  }


  const handleDeleteChapter = (chapter: ChapterItem) => {
    if (isNew) {
      // 暫存章節尚未寫入 DB，也就沒有學員紀錄可連帶處理——直接移除，不必 confirm
      setStagedChapters((prev) => prev.filter((c) => c.id !== chapter.chapter_id))
      return
    }
    confirm({
      title: "刪除章節",
      content: "確定刪除此章節？學員於本章節之學習與成績將一併移除，且不再計入完課率。",
      okText: "刪除",
      onOk: async () => {
        try {
          await coursesApi.deleteChapter(chapter.chapter_id)
          invalidate()
        } catch (err) {
          handleError(err)
        }
      },
    })
  }

  // ── 章節項目（教材 / 測驗，#203）────────────────────────────────────────

  const openMaterialId = openItem?.item_type === "MATERIAL" ? openItem.material_id : null
  const openQuizId = openItem?.item_type === "QUIZ" ? openItem.quiz_id : null

  // 用 `isLoading`（首次載入）而非 `isFetching`——後者在存檔後的 refetch 也會是 true，
  // 視窗內容會被換成轉圈再換回來，看起來就是「儲存完視窗跳一下」。
  const { data: material, isLoading: materialLoading } = useQuery({
    queryKey: QUERY_KEYS.etCourses.material(openMaterialId ?? 0),
    queryFn: () => materialsApi.getDetail(openMaterialId as number),
    enabled: openMaterialId !== null,
  })

  const { data: quiz, isLoading: quizLoading } = useQuery({
    queryKey: QUERY_KEYS.etCourses.quiz(openQuizId ?? 0),
    queryFn: () => quizzesApi.getDetail(openQuizId as number),
    enabled: openQuizId !== null,
  })

  // DM 文件下拉只在教材視窗開著時才查——課程編輯頁本身不需要這份清單
  const { data: dmOptions = [] } = useQuery({
    queryKey: QUERY_KEYS.etCourses.dmDocuments(),
    queryFn: () => materialsApi.listDmDocuments(),
    enabled: openMaterialId !== null,
  })

  const invalidateMaterial = () => {
    if (openMaterialId !== null) {
      void qc.invalidateQueries({ queryKey: QUERY_KEYS.etCourses.material(openMaterialId) })
    }
  }
  const invalidateQuiz = () => {
    if (openQuizId !== null) {
      void qc.invalidateQueries({ queryKey: QUERY_KEYS.etCourses.quiz(openQuizId) })
    }
    // 題目增刪改不經 `invalidate()`，而「配分須等於 100」「至少 1 題」的紅框要跟著題目走（#558）
    refreshLiveCheck()
  }

  /**
   * 項目視窗內的操作統一經此執行。
   *
   * 錯誤呈現在**視窗內的 Alert** 而非 snackbar：使用者的注意力在視窗裡，
   * 而「教材須至少提供⋯」這類訊息需要指出是哪一個教材出問題，飄一則 toast 說不清楚。
   */
  const runItemAction = async (
    action: () => Promise<unknown>,
    after?: () => void,
    /** 錯誤的呈現位置——上傳相關的要落在上傳區旁，其餘落在視窗頂端。 */
    setError: (message: string | null) => void = setItemError,
  ) => {
    setError(null)
    try {
      await action()
      after?.()
    } catch (err) {
      const { errorCode, errorMessage } = toApiError(err)
      if (errorCode === LOCK_CONFLICT) {
        setConflictOpen(true)
        return
      }
      setError(errorMessage)
    }
  }

  const closeItemDialog = () => {
    setOpenItem(null)
    setItemError(null)
    setUploadError(null)
    setUnsavedNewItemId(null)
  }

  /** 丟棄尚未儲存過的新項目——連同其空殼教材 / 測驗一併刪除。 */
  const discardUnsavedItem = async () => {
    const itemId = unsavedNewItemId
    closeItemDialog()
    if (itemId === null) return
    try {
      await itemsApi.remove(itemId)
      invalidate()
    } catch (err) {
      handleError(err)
    }
  }

  /**
   * 關閉項目視窗。
   *
   * | 情境 | 行為 |
   * |------|------|
   * | 新項目、沒填任何東西 | **直接刪掉**，不問——他只是點開看看 |
   * | 新項目、填了東西 | 確認後刪掉 |
   * | 既有項目、沒改過 | 直接關 |
   * | 既有項目、改過 | 確認後關（項目本身保留） |
   *
   * ## 🔴 既有教材的已上傳影片**不在「放棄」的範圍內**（#442）
   *
   * 影片是選檔即上傳（`MaterialDialog` 模組 docstring 記著理由：檔案傳輸沒辦法暫存在
   * 請求裡），所以按取消它仍在伺服器上。原本兩種情境共用「尚未儲存的變更將不會保留」
   * 一句，對既有教材是**不成立**的宣稱——教師據此以為自己取消掉了。
   *
   * 兩種情境不可合併成一句更含糊的話：新項目那邊取消是連項目帶空殼一起刪，影片跟著
   * 消失，原句成立且該保持；含糊化等於把一句正確的話也弄成不精確的。
   */
  const requestCloseItem = (dirty: boolean) => {
    const isUnsavedNew = unsavedNewItemId !== null
    if (!dirty) {
      if (isUnsavedNew) void discardUnsavedItem()
      else closeItemDialog()
      return
    }
    // 只在「既有教材且真的有影片」時才提——沒有影片還講一句影片，對他同樣不成立。
    const keepsUploadedVideos = !isUnsavedNew && (material?.videos.length ?? 0) > 0
    confirm({
      title: "放棄變更",
      content: isUnsavedNew
        ? "變更內容不會儲存，此項目也不會建立。確定取消？"
        : keepsUploadedVideos
          ? "尚未儲存的變更將不會保留。已上傳的影片不在此列——它在選擇檔案時就已保存，取消不會移除。確定關閉？"
          : "尚未儲存的變更將不會保留，確定關閉？",
      okText: "確定",
      onOk: isUnsavedNew ? discardUnsavedItem : closeItemDialog,
    })
  }

  // 自動存草稿後由 navigate state 帶進來的待辦項目（#335）：課程與章節此時已寫入 DB，
  // 依索引取真正的 `chapter_id` 再建項目並開視窗。只執行一次——ref 守衛在 state 被
  // 清掉之前就攔住重入（`navigate(..., { replace: true, state: null })` 會再觸發一次 render）。
  const pendingAddItem = (location.state as { pendingAddItem?: PendingAddItem } | null)?.pendingAddItem
  const pendingHandled = useRef(false)

  useEffect(() => {
    if (!pendingAddItem || pendingHandled.current || isNew) return
    const target = course?.chapters?.[pendingAddItem.chapterIndex]
    if (!target) return // 等課程載入；載入後本 effect 會再跑一次
    pendingHandled.current = true
    // 清掉 state：否則使用者在本頁重新整理會再建一個空項目
    navigate(location.pathname, { replace: true, state: null })
    void (async () => {
      try {
        const created = await itemsApi.add(target.chapter_id, pendingAddItem.itemType, pendingAddItem.title)
        invalidate()
        setUnsavedNewItemId(created.item_id)
        setOpenItem(created)
      } catch (err) {
        handleError(err)
      }
    })()
    // deps 完整列出：`handleError` / `invalidate` 每次 render 都是新函式，本 effect 因此
    // 會隨 render 重跑——但 `pendingHandled` ref 在首次真正執行時就設旗標，重入被擋在
    // 最前面，故不需要 eslint-disable 來掩蓋依賴。
  }, [pendingAddItem, course?.chapters, isNew, handleError, invalidate, location.pathname, navigate])

  // 同上，問卷版（#435）。問卷掛課程層級，不需要等章節載入——拿到 `courseId` 即可建立。
  const pendingAddSurvey = (location.state as { pendingAddSurvey?: PendingAddSurvey } | null)?.pendingAddSurvey
  const pendingSurveyHandled = useRef(false)

  useEffect(() => {
    if (!pendingAddSurvey || pendingSurveyHandled.current || isNew || courseId === undefined) return
    pendingSurveyHandled.current = true
    navigate(location.pathname, { replace: true, state: null })
    void (async () => {
      try {
        await surveyApi.create(courseId, pendingAddSurvey.surveyName)
        qc.invalidateQueries({ queryKey: QUERY_KEYS.etCourses.survey(courseId) })
        // 建完直接開視窗接續編輯題目——與編輯模式下按「建立」之後的樣子一致，
        // 使用者不該因為中間插了一次自動存草稿就得再點一次。
        setSurveyOpen(true)
      } catch (err) {
        handleError(err)
      }
    })()
  }, [pendingAddSurvey, isNew, courseId, handleError, location.pathname, navigate, qc])

  /**
   * 按下「新增項目」→ **先問名稱**（#414），確認後才真的建立。
   *
   * 2026-08-27 起此處原本直接以空名稱建 DB 空殼，理由是「不代填『新教材』——使用者
   * 開了視窗第一件事就是把預設值選起來刪掉」。⭐ 那個判斷仍然成立（`NewItemDialog`
   * 也沒有代填），被推翻的是它的前提「空名稱只是還沒填的過渡狀態」——空殼在建立當下
   * 就落地了，而清理只掛在「取消」上，換頁 / 重新整理 / 按「儲存草稿」都會留下它。
   */
  const handleAddItem = (chapter: ChapterItem, itemType: ItemType) => {
    // 🔴 **新增模式下課程本身的必填要先擋**，否則使用者會先打完項目名稱、按下「建立」
    // 才被告知「課程名稱未填」——那個錯誤與他剛做的事無關，而他剛輸入的名稱也白打了。
    // 擋在這裡即維持 #335 原本的行為：按下「新增項目」當場標出欄位錯誤。
    if (isNew && !validateForm()) return
    setNamingItem({ chapter, itemType })
  }

  /** 命名視窗按下「建立」。 */
  const confirmNewItem = async (title: string) => {
    if (!namingItem) return
    const { chapter, itemType } = namingItem
    setCreatingItem(true)
    try {
      // 新增模式：課程還不存在，項目掛不上去（`ET_ITEM` 需要真的 `CHAPTER_ID`）。
      // 先自動存草稿再繼續，而不是要使用者先去按一次「儲存草稿」——那個斷點沒有業務
      // 意義，章節那層（`CourseCreateReq.chapters`）當初就是為此讓課程與章節一次送出。
      // 形狀比照 Moodle 的「Save and display」：把存檔藏在「往下走」的按鈕語意裡。
      if (isNew) {
        await autoSaveThenAddItem(chapter, itemType, title)
        return
      }
      const created = await itemsApi.add(chapter.chapter_id, itemType, title)
      invalidate()
      // 建完直接開視窗——剛建的項目還沒有內容，不開等於要使用者再點一次
      setUnsavedNewItemId(created.item_id)
      setOpenItem(created)
    } catch (err) {
      handleError(err)
    } finally {
      setCreatingItem(false)
      setNamingItem(null)
    }
  }

  /**
   * 新增模式按「新增項目」：存草稿 → 導向編輯頁 → 由該頁接手建立項目並開視窗（#335）。
   *
   * ## 為何導向而非留在本頁用 state 切換
   *
   * 留在 `/et/courses/new` 的話，使用者一重新整理會看到空白的新增頁，而課程其實
   * 已經建好了——他會再建一門。導向後網址即為 `/et/courses/{id}`，重新整理安全。
   * 用 `replace` 是因為 `/new` 在草稿建立後已失效，返回鍵不該回到那裡。
   *
   * ## 為何用 chapterIndex 而非 chapter_id
   *
   * `POST /courses` 的回應只有 `course_id` / `version`，**不含新建章節的 id**。而
   * 暫存章節的 id 是前端的負數計數器，對後端無意義。後端按 `chapters` 陣列順序
   * 逐一 append（見 `EtCourseService.create_draft`），故索引可對應——由編輯頁載入
   * 課程後依索引取真正的 `chapter_id`。
   */
  const autoSaveThenAddItem = async (chapter: ChapterItem, itemType: ItemType, title: string) => {
    // 表單驗證已於 `handleAddItem` 做過（要在開啟命名視窗**之前**擋），此處不重複——
    // 兩處各驗一次會讓規則有兩個版本，而命名視窗開啟期間表單是碰不到的。
    const chapterIndex = stagedChapters.findIndex((c) => c.id === chapter.chapter_id)
    await autoSaveThenNavigate({ pendingAddItem: { chapterIndex: chapterIndex < 0 ? 0 : chapterIndex, itemType, title } })
  }

  /**
   * 存草稿 → 導向 `/et/courses/{id}`，把「接下來要做的事」放進 navigate state（#335 / #435）。
   *
   * 失敗時**不導向**：錯誤顯示在原處，使用者留在新增頁、剛輸入的內容還在。
   */
  const autoSaveThenNavigate = async (state: { pendingAddItem: PendingAddItem } | { pendingAddSurvey: PendingAddSurvey }) => {
    try {
      const created = await coursesApi.create({ ...toPayload(), chapters: stagedChapters.map((c) => c.name) })
      message.success("已自動儲存草稿")
      navigate(`/et/courses/${created.course_id}`, { replace: true, state })
    } catch (err) {
      handleError(err)
    }
  }

  const handleDeleteItem = (item: ItemRow) => {
    confirm({
      title: `刪除${item.item_type === "MATERIAL" ? "教材" : "測驗"}`,
      content:
        "確定刪除此項目？其內容與學員於此項目之學習紀錄、成績將一併移除，且不再計入完課率。",
      okText: "刪除",
      onOk: async () => {
        try {
          await itemsApi.remove(item.item_id)
          invalidate()
          if (openItem?.item_id === item.item_id) closeItemDialog()
        } catch (err) {
          handleError(err)
        }
      },
    })
  }

  const handleUploadVideo = async (file: File) => {
    if (openMaterialId === null) return
    setUploading(true)
    await runItemAction(
      () => materialsApi.uploadVideo(openMaterialId, file),
      () => {
        invalidateMaterial()
        invalidate()
      },
      setUploadError,
    )
    setUploading(false)
  }

  /**
   * 測驗內容有變更時，先問教師是否要求已通過的學員重測，再執行實際儲存（#361）。
   *
   * 沒有人通過過就不問——那是新建測驗的常態，多一個對話框只是噪音。
   */
  const askRetestThen = (run: (requireRetest: boolean) => void) => {
    if ((quiz?.passed_count ?? 0) > 0) {
      setPendingRetestAction(() => run)
      return
    }
    run(false)
  }

  const handleDeleteQuestion = (question: QuestionRow) => {
    confirm({
      title: "刪除題目",
      // ⚠️ 原文為「學員於此題之作答紀錄與得分將一併移除」——那是 #202 的行為，
      // 已於 #279 裁示 Q2=C 推翻。`soft_delete_questions` 只軟刪題目與選項，
      // 作答明細（自給自足的快照）完整保留，成績也不重算。
      content: "確定刪除此題目？此題不再出現於之後的作答；已作答學員的紀錄與成績完整保留、仍可回看。",
      okText: "刪除",
      onOk: () =>
        askRetestThen((requireRetest) =>
          void runItemAction(() => quizzesApi.removeQuestion(question.question_id, requireRetest), invalidateQuiz),
        ),
    })
  }

  // 已發布課程僅可新增配對、不可移除（FR-ET-US3-02）——鎖住的是**伺服器上已存在**的那幾組，
  // 不是整區；以值比對（`audienceKey`），新增的列照常可改可刪
  const lockedAudiences = new Set(status !== "DRAFT" && course ? course.audiences.map(audienceKey) : [])

  // ⚠️ 查詢失敗時**必須早退**。原本忽略 error，403 之後 `course` 為 undefined，
  // 而 `readOnly` 是由 `course` 推導的（undefined → false），結果學員直接看到一個
  // 可編輯的課程編輯頁——雖然每個寫入都會被後端擋下，但畫面本身就不該出現。

  // 重進頁面時快取讓 `courseLoading` 為 false，但表單要等 refetch 落定才預帶（#578，見上），
  // 這段空窗期若直接渲染就會出現下面那行註解原本要避免的「空表單閃現」。
  // ⚠️ 條件寫 `course &&` 而非 `courseId !== undefined`——403 / 404 時 `course` 為
  // undefined、表單永遠不會預帶，寫成後者會轉圈轉到天荒地老、蓋掉下方的錯誤畫面。
  const formPending = course !== undefined && loadedCourseId !== course.course_id
  if (courseLoading || formPending) {
    // 載入中先顯示轉圈——否則會先閃出一張空表單，看起來像資料掉了
    return (
      <Stack alignItems="center" sx={{ py: 8 }}>
        <CircularProgress />
      </Stack>
    )
  }

  if (courseError) {
    const { status, errorMessage } = toApiError(courseError)
    const forbidden = status === 403
    return (
      <Box>
        <ScreenHeader
          code="ET05"
          title="課程編輯"
          leading={
            <IconButton size="small" aria-label="返回課程列表" onClick={() => navigate("/et/courses")}>
              <ArrowBackIcon />
            </IconButton>
          }
        />
        <Alert severity={forbidden ? "warning" : "error"}>
          {forbidden ? "您沒有檢視此課程的權限。課程編輯僅開放教師與管理者。" : errorMessage}
        </Alert>
      </Box>
    )
  }

  return (
    <LocalizationProvider dateAdapter={AdapterDayjs} adapterLocale="zh-tw" localeText={PICKER_LOCALE_TEXT}>
    <Box>
      <ScreenHeader
        code="ET05"
        title={courseId === undefined ? "新增課程" : "課程編輯"}
        leading={
          <IconButton size="small" aria-label="返回課程列表" onClick={() => navigate("/et/courses")}>
            <ArrowBackIcon />
          </IconButton>
        }
        adornment={<Chip size="small" label={COURSE_STATUS_LABEL[status] ?? status} />}
        actions={
          <Stack direction="row" spacing={1}>
            {/*
              「預覽課程」（#481）。**草稿與已關閉課程只有這個入口**——課程列表的
              「全部課程」只含已發布且期間未過者，而 `structure` 有一段專為草稿而寫的
              程式碼（#255：「教師需要在發布**之前**確認學員視角，草稿階段正是最需要
              預覽的時候」），少了這顆按鈕那段永遠到不了。

              ⚠️ 新增模式不顯示：課程還不存在，沒有東西可以預覽。
              ⚠️ 唯讀者（他人課程）不顯示：他是從「全部課程」點進預覽頁、再退回來才會
              看到編輯頁，再給一顆按鈕只是繞回去。
            */}
            {courseId !== undefined && !readOnly && (
              <Button
                size="small"
                variant="outlined"
                startIcon={<VisibilityIcon />}
                onClick={() => navigate(`/et/courses/${courseId}/learn`)}
              >
                預覽課程
              </Button>
            )}
            {/*
              「邀請學員」僅**已發布**課程顯示（AC 1）——草稿尚無邀請碼、學員端也看不到課程；
              已關閉課程的學習頁為唯讀，把人邀請進去只會讓他點開後什麼都不能做。再開課後
              `status` 回 PUBLISHED，按鈕自然恢復，不需要額外的「恢復」邏輯。
              非擁有者（檢視模式）一律不顯示。
            */}
            {status === "PUBLISHED" && !readOnly && course !== undefined && (
              <Button variant="contained" size="small" startIcon={<PersonAddIcon />} onClick={() => setInviteOpen(true)}>
                邀請學員
              </Button>
            )}
            {/*
              關閉 / 再開課（US11 AC 1 / AC 8、#288）。兩者互斥且各只在對應狀態出現——
              草稿沒有學員也沒有邀請碼，關閉它沒有語意（要移除草稿走既有的刪除）。
            */}
            {status === "PUBLISHED" && !readOnly && course !== undefined && (
              <Button variant="outlined" size="small" color="warning" startIcon={<LockIcon />} onClick={requestClose}>
                關閉課程
              </Button>
            )}
            {status === "CLOSED" && !readOnly && course !== undefined && (
              <Button
                variant="contained"
                size="small"
                startIcon={<LockOpenIcon />}
                disabled={reopening}
                onClick={enterReopen}
              >
                再開課
              </Button>
            )}
          </Stack>
        }
      />

      {course !== undefined && (
        <InviteStudentsDialog
          open={inviteOpen}
          courseId={course.course_id}
          courseName={course.course_name}
          invitationCode={course.invitation_code}
          onClose={() => setInviteOpen(false)}
        />
      )}

      {readOnly && (
        <Alert severity="warning" icon={<VisibilityIcon />} sx={{ mb: 2 }}>
          <strong>檢視模式</strong> — 此課程由 <strong>{course ? ownerLabel(course) : "他人"}</strong> 建立，您僅可閱覽，無法編輯。
        </Alert>
      )}

      {/*
        已關閉提示（US11 AC 6 / #288）。

        ⚠️ 刻意寫明「課程內容仍可編輯」：關閉停的是**學員端**（不可加入、不可累積進度、
        不可作答、不可填問卷），教師端的編輯照舊。少了這句，教師會以為關閉後這頁是唯讀
        的而不敢改——AC 6 的整個用意就是讓他能在關閉期間整理教材再開課。
      */}
      {status === "CLOSED" && !reopening && (
        <Alert severity="info" icon={<LockIcon />} sx={{ mb: 2 }}>
          <strong>此課程已關閉</strong> — 學員無法加入、累積學習進度或填寫問卷，邀請碼暫時失效；
          已加入的學員仍可唯讀回看內容與成績。<strong>課程內容仍可編輯</strong>，整理完畢後按「再開課」即可恢復。
        </Alert>
      )}

      {/*
        再開課模式（#428）。
        ⚠️ **必須說明「為什麼被清空」**——只給紅框的話，教師會以為資料掉了。
      */}
      {reopening && (
        <Alert severity="warning" icon={<LockOpenIcon />} sx={{ mb: 2 }}>
          <strong>再開課：請重新設定開放起訖時間</strong> — 原本的起訖時間已清空，這是刻意的：
          沿用舊值會把課程再開成一段已經過去的期間，學員一樣進不來。
          <strong>尚未變更任何資料</strong>，按「取消再開課」即可還原。
          <Box component="span" sx={{ display: "block", mt: 0.5 }}>
            {/* ⚠️ 這句原本在 `ReopenCourseDialog` 裡，移除對話框時一併不見了（#428 code
                review 的 MEDIUM）。教師第一次再開課最擔心的就是學員得從頭來過。 */}
            學員的學習進度與成績會<strong>接續保留</strong>，原邀請碼沿用並恢復有效。
          </Box>
        </Alert>
      )}

      {/*
        再開課的發布檢核缺漏改以**對話框**呈現（#509；取代 #449 / PR #452 在頁面上的白底區塊）。

        ⚠️ 這不違反 #428：#428 移除的是「編輯起訖時間」的對話框（日曆比對話框還高），
        缺漏清單沒有日曆。橙色的「請重新設定開放起訖時間」與時間欄位是一組，⛔ 不要
        一起搬進來。

        ⚠️ 傳的是 `reopenBlockers`，**不是**發布用的 `blockers`——共用一份會讓上一次發布
        嘗試殘留的缺漏在此顯示（見 `reopenBlockers` 的宣告）。共用的只有呈現元件。

        關閉只清掉缺漏、**不退出再開課模式**：教師接著要去補內容，補完再按一次確認。
      */}
      {reopening && reopenBlockers.length > 0 && (
        <BlockerDialog
          title="再開課"
          message="課程目前不符發布條件，無法再開課。關閉期間的編輯可能移除了必要內容，請先補齊以下項目。"
          blockers={reopenBlockers}
          names={{ quiz: quizNames, chapter: chapterNames, itemChapter: itemChapterNames }}
          onClose={() => {
            // 關閉即進入標示模式：缺漏處標紅框，教師就地補（#558）。仍不退出再開課模式
            setReopenBlockers([])
            setHighlight("reopen")
          }}
        />
      )}

      {/*
        邀請碼（#247 補 #204 之缺口）。在此之前它只在發布當下的 `PublishDialog` 出現
        一次，而發布後**不提供重新產生**——教師關掉視窗就永久拿不回來，那門課再也發不
        出邀請碼。後端只對 owner 回傳本欄位（非擁有者恆為 null），故此處不必再判 readOnly。
      */}
      {course?.invitation_code && (
        <Alert severity="info" sx={{ mb: 2 }}>
          <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap>
            <span>課程邀請碼：</span>
            <Typography component="span" fontFamily="monospace" fontWeight={700} letterSpacing={3}>
              {course.invitation_code}
            </Typography>
            <IconButton
              size="small"
              aria-label="複製邀請碼"
              onClick={() => void navigator.clipboard?.writeText(course.invitation_code ?? "")}
            >
              <ContentCopyIcon fontSize="small" />
            </IconButton>
          </Stack>
        </Alert>
      )}

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 2 }}>
          基本資料
        </Typography>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", md: "repeat(12, 1fr)" },
            gap: 2,
          }}
        >
          <Box sx={{ gridColumn: { md: "span 9" } }}>
            <TextField
              label="課程名稱"
              required
              size="small"
              fullWidth
              value={form.course_name}
              disabled={readOnly}
              error={Boolean(fieldErrors.course_name)}
              helperText={fieldErrors.course_name}
              onChange={(e) => setForm({ ...form, course_name: e.target.value })}
            />
          </Box>
          <Box sx={{ gridColumn: { md: "span 3" } }}>
            <TextField
              label="狀態"
              size="small"
              fullWidth
              disabled
              value={COURSE_STATUS_LABEL[status] ?? status}
            />
          </Box>
          <Box sx={{ gridColumn: { md: "span 12" } }}>
            <CourseAudiencePairs
              options={tagOptions}
              value={form.audiences}
              lockedKeys={lockedAudiences}
              readOnly={readOnly}
              readOnlyPairs={course?.audiences ?? []}
              rowErrors={audienceRowErrors}
              error={fieldErrors.audiences}
              onChange={(next) => {
                setForm((prev) => ({ ...prev, audiences: next }))
                // 列錯誤以索引為鍵——增刪列後索引位移，舊訊息會掛在錯的列上，故整份清掉
                setAudienceErrors({})
              }}
            />
          </Box>
          <Box sx={{ gridColumn: { md: "span 4" } }}>
            {/* ⚠️ 再開課模式**不套 `startFloor`**：本頁平時擋「起始早於當下」，而再開課
                刻意允許（補開一段已經開始的期間是合理操作，見 `reopenSchedule.ts`）。
                沿用 `startFloor` 會讓那些日期變成灰底不可選，擋掉後端允許的操作。 */}
            <DateTimePicker
              label="課程起始時間"
              format={PICKER_FORMAT}
              ampm={false}
              value={startAt}
              disabled={readOnly}
              minDateTime={reopening ? undefined : startFloor}
              onChange={(v) => setStartAt(v)}
              slotProps={{
                textField: {
                  size: "small",
                  fullWidth: true,
                  required: reopening,
                  error: reopening
                    ? Boolean(reopenFieldErrors.start) || reopenStartEmpty
                    : Boolean(fieldErrors.open_start_at),
                  helperText: reopening ? reopenFieldErrors.start : fieldErrors.open_start_at,
                },
                actionBar: { actions: ["cancel", "accept"] },
              }}
            />
          </Box>
          <Box sx={{ gridColumn: { md: "span 4" } }}>
            {/* 再開課模式的訖止下限為「起始與當下之較晚者」——沿用原對話框的規則
                （後端 `ensure_reopen_schedule` 只要求訖止晚於當下）。 */}
            <DateTimePicker
              label="課程訖止時間"
              format={PICKER_FORMAT}
              ampm={false}
              value={endAt}
              disabled={readOnly}
              minDateTime={
                reopening
                  ? (startAt && startAt.isAfter(dayjs()) ? startAt : dayjs())
                  : (startAt ?? undefined)
              }
              onChange={(v) => setEndAt(v)}
              slotProps={{
                textField: {
                  size: "small",
                  fullWidth: true,
                  required: reopening,
                  error: reopening
                    ? Boolean(reopenFieldErrors.end) || reopenEndEmpty
                    : Boolean(fieldErrors.open_end_at),
                  helperText: reopening ? reopenFieldErrors.end : fieldErrors.open_end_at,
                },
                actionBar: { actions: ["cancel", "accept"] },
              }}
            />
          </Box>
          <Box sx={{ gridColumn: { md: "span 4" } }}>
            <FormControlLabel
              control={
                <Switch
                  checked={form.require_approval}
                  disabled={readOnly}
                  onChange={(e) => setForm({ ...form, require_approval: e.target.checked })}
                />
              }
              label="本課程需線下核可"
            />
            <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
              開啟後學員線上完課仍須教師 / 管理者核可；不併入完課定義、不影響完課率。
            </Typography>
          </Box>
          <Box sx={{ gridColumn: { md: "span 12" } }}>
            <TextField
              label="課程描述"
              size="small"
              fullWidth
              multiline
              rows={2}
              value={form.description}
              disabled={readOnly}
              error={Boolean(fieldErrors.description)}
              helperText={fieldErrors.description ?? `${form.description.length} / ${DESCRIPTION_MAX_LEN}`}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </Box>
        </Box>
      </Paper>

      <ChapterSection
        chapters={chapters}
        readOnly={readOnly}
        blockedChapters={highlights.chapters}
        blockedItems={highlights.items}
        disabled={false}
        onAdd={() => {
          setChapterDraft("")
          setChapterError("")
          setChapterDialogOpen(true)
        }}
        onRename={(chapter, name) => {
          if (isNew) {
            setStagedChapters((prev) => prev.map((c) => (c.id === chapter.chapter_id ? { ...c, name } : c)))
            return
          }
          chapterMut.mutate(() => coursesApi.renameChapter(chapter.chapter_id, name, chapter.version))
        }}
        onDelete={handleDeleteChapter}
        onReorder={(ids) => {
          if (isNew) {
            setStagedChapters((prev) => ids.map((id) => prev.find((c) => c.id === id)).filter((c) => c !== undefined))
            return
          }
          // 樂觀更新：先把快取裡的章節順序換掉，拖放後立即定位。
          // 少了這步，畫面要等 API + refetch 才變，中間會閃回舊順序、看起來像「拖了沒動」。
          // 失敗時 onError 會 invalidate 還原（見 chapterMut）。
          qc.setQueryData(QUERY_KEYS.etCourses.detail(courseId), (old?: CourseDetail) =>
            old
              ? {
                  ...old,
                  chapters: ids
                    .map((id) => old.chapters.find((c) => c.chapter_id === id))
                    .filter((c) => c !== undefined),
                }
              : old,
          )
          chapterMut.mutate(() => coursesApi.reorderChapters(courseId, ids, course?.version ?? 0))
        }}
        onAddItem={handleAddItem}
        onOpenItem={(item) => {
          setItemError(null)
          setUploadError(null)
          // 由清單點開的是既有項目——取消時不該把它刪掉
          setUnsavedNewItemId(null)
          setOpenItem(item)
        }}
        onDeleteItem={handleDeleteItem}
        onReorderItems={(chapter, ids) => {
          // 樂觀更新：同章節重排之理由——少了這步會閃回舊順序、看起來像「拖了沒動」
          qc.setQueryData(QUERY_KEYS.etCourses.detail(courseId as number), (old?: CourseDetail) =>
            old
              ? {
                  ...old,
                  chapters: old.chapters.map((c) =>
                    c.chapter_id === chapter.chapter_id
                      ? {
                          ...c,
                          items: ids.map((id) => c.items.find((i) => i.item_id === id)).filter((i) => i !== undefined),
                        }
                      : c,
                  ),
                }
              : old,
          )
          chapterMut.mutate(() => itemsApi.reorder(chapter.chapter_id, ids, chapter.version))
        }}
      />

      <MaterialDialog
        open={openMaterialId !== null}
        loading={materialLoading}
        readOnly={readOnly}
        material={material ?? null}
        dmOptions={dmOptions}
        videoLimits={videoLimits}
        error={itemError}
        uploadError={uploadError}
        uploading={uploading}
        onClose={requestCloseItem}
        onSave={(values: MaterialSavePayload) =>
          void runItemAction(
            () => materialsApi.update(openMaterialId as number, { ...values, version: material?.version ?? 0 }),
            () => {
              message.success("教材已儲存")
              invalidateMaterial()
              // 課程詳細也要刷——項目列顯示的名稱取自教材名稱
              invalidate()
              // 存過之後就不再是「未儲存的新項目」，關閉時不該被刪掉
              setUnsavedNewItemId(null)
              closeItemDialog()
            },
          )
        }
        onUploadVideo={(file) => void handleUploadVideo(file)}
      />

      <QuizDialog
        open={openQuizId !== null}
        loading={quizLoading}
        readOnly={readOnly}
        quiz={quiz ?? null}
        error={itemError}
        onClose={requestCloseItem}
        onSaveSettings={(values) =>
          askRetestThen((requireRetest) =>
            void runItemAction(
              () =>
                quizzesApi.update(openQuizId as number, {
                  ...values,
                  version: quiz?.version ?? 0,
                  require_retest: requireRetest,
                }),
              () => {
                message.success("測驗已儲存")
                invalidateQuiz()
                // 課程詳細也要刷——項目列顯示的名稱取自測驗名稱
                invalidate()
                setUnsavedNewItemId(null)
                closeItemDialog()
              },
            ),
          )
        }
        onSaveQuestion={(questionId: number | null, values: QuestionFormValues) =>
          askRetestThen((requireRetest) =>
            void runItemAction(() => {
              if (questionId === null) {
                return quizzesApi.addQuestion(openQuizId as number, { ...values, require_retest: requireRetest })
              }
              const version = quiz?.questions.find((q) => q.question_id === questionId)?.version ?? 0
              return quizzesApi.updateQuestion(questionId, { ...values, version, require_retest: requireRetest })
            }, invalidateQuiz),
          )
        }
        onDeleteQuestion={handleDeleteQuestion}
      />

      {/*
        ⚠️ **條件渲染，不要改成常駐掛載 `open={...}`。** MUI 的 Dialog 即使 `open=false`
        也會參與 `aria-hidden` 的簿記，常駐一個會讓本頁其他測試的背景按鈕查不到而
        逾時（實測：改成常駐後 `CourseEditorPage.test` 由 30/30 變成 28/30，兩條新增
        模式的測試卡在 5000ms；移除渲染即恢復）。
      */}
      {/* 新增項目前先取得名稱（#414）。⚠️ 同樣是**條件渲染**，理由見上方 RequireRetestDialog。 */}
      <NewItemDialog
        itemType={namingItem?.itemType ?? null}
        submitting={creatingItem}
        onCancel={() => setNamingItem(null)}
        onConfirm={confirmNewItem}
      />
      {pendingRetestAction !== null && (
        <RequireRetestDialog
          open
          passedCount={quiz?.passed_count ?? 0}
          onCancel={() => setPendingRetestAction(null)}
          onDecide={(requireRetest) => {
            const run = pendingRetestAction
            setPendingRetestAction(null)
            run(requireRetest)
          }}
        />
      )}

      <SurveySection
        survey={isNew ? null : survey}
        readOnly={readOnly}
        blocker={highlights.survey}
        isDraftCourse={status === "DRAFT"}
        saving={surveyMut.isPending}
        error={surveyError}
        // #359 第 1 項：直接開視窗，名稱於視窗內填。**不預建空殼**——取消時什麼都沒發生。
        onCreate={() => {
          // 🔴 理由與 `handleAddItem` 逐字相同（#435）：新增模式下課程本身的必填要先擋，
          // 否則使用者會先打完問卷名稱、按下「建立」才被告知「課程名稱未填」——那個錯誤
          // 與他剛做的事無關，而他剛輸入的名稱也白打了。
          if (isNew && !validateForm()) return
          setSurveyError(null)
          setSurveyOpen(true)
        }}
        onOpen={() => {
          setSurveyError(null)
          setSurveyOpen(true)
        }}
        onDeactivate={() =>
          confirm({
            title: "停用課後問卷",
            content: "停用後學員端不再顯示填寫入口，已填寫的內容仍保留。確定停用？",
            okText: "停用",
            onOk: () =>
              surveyMut.mutate(() =>
                surveyApi.update(survey!.survey_id, {
                  survey_name: survey!.survey_name,
                  is_active: false,
                  version: survey!.version,
                }),
              ),
          })
        }
        onDelete={() =>
          confirm({
            title: "刪除課後問卷",
            content: "確定刪除此問卷？其題目與選項將一併移除。刪除後可重新建立。",
            okText: "刪除",
            onOk: () => surveyMut.mutate(() => surveyApi.remove(survey!.survey_id)),
          })
        }
      />

      <SurveyDialog
        open={surveyOpen}
        readOnly={readOnly}
        survey={survey ?? null}
        templates={surveyTemplates}
        saving={surveyMut.isPending}
        error={surveyError}
        onCreate={(name) => {
          // 新增模式：課程還不存在，問卷掛不上去（`ET_SURVEY` 需要真的 `COURSE_ID`）。
          // ⚠️ 自動存草稿發生在**按下建立之後**，不是開視窗的時候——否則教師開了視窗
          // 又改變主意，課程草稿已經被建出來了，而 #359 的承諾是「取消時什麼都沒發生」。
          if (isNew) {
            void autoSaveThenNavigate({ pendingAddSurvey: { surveyName: name } })
            return
          }
          surveyMut.mutate(() => surveyApi.create(courseId as number, name))
        }}
        onClose={(dirty) => {
          // 題目編輯器展開中代表有還沒存的內容，直接關掉會讓它無聲消失
          // （#203 實測回饋：「有填入值按取消跳出提示」）
          if (!dirty) {
            setSurveyOpen(false)
            return
          }
          confirm({
            title: "放棄變更",
            // 建立步驟與編輯步驟的後果不同：前者是「問卷不會被建立」，後者是「問卷留著、
            // 這次的題目編輯不保留」。共用一句會讓教師以為取消會連問卷一起刪掉。
            content: survey
              ? "尚未儲存的題目內容將不會保留，確定關閉？"
              : "問卷尚未建立，關閉後不會保留已填的名稱。確定關閉？",
            okText: "確定",
            onOk: () => setSurveyOpen(false),
          })
        }}
        onRename={(name) =>
          surveyMut.mutate(() =>
            surveyApi.update(survey!.survey_id, {
              survey_name: name,
              is_active: survey!.is_active,
              version: survey!.version,
            }),
          )
        }
        onApplyTemplate={(code) =>
          surveyMut.mutate(() => surveyApi.applyTemplate(survey!.survey_id, code, survey!.version))
        }
        onSaveQuestion={(sqId: number | null, values: SurveyQuestionFormValues) =>
          surveyMut.mutate(() => {
            if (sqId === null) return surveyApi.addQuestion(survey!.survey_id, values)
            const version = survey!.questions.find((q) => q.sq_id === sqId)?.version ?? 0
            return surveyApi.updateQuestion(sqId, { ...values, version })
          })
        }
        onDeleteQuestion={(question: SurveyQuestionRow) =>
          confirm({
            title: "刪除問卷題目",
            content: "確定刪除此題目？此題與其選項將一併移除。",
            okText: "刪除",
            onOk: () => surveyMut.mutate(() => surveyApi.deleteQuestion(question.sq_id)),
          })
        }
        onReorder={(ids) => {
          // 樂觀更新：少了這步畫面要等 API + refetch 才變，中間會閃回舊順序、
          // 看起來像「拖了沒動」（比照章節 / 項目重排）。失敗時 onError 會 invalidate 還原。
          qc.setQueryData(QUERY_KEYS.etCourses.survey(courseId as number), (old?: typeof survey) =>
            old
              ? {
                  ...old,
                  questions: ids.map((id) => old.questions.find((q) => q.sq_id === id)).filter((q) => q !== undefined),
                }
              : old,
          )
          surveyMut.mutate(() => surveyApi.reorderQuestions(survey!.survey_id, ids, survey!.version))
        }}
      />

      {!readOnly && (
        <Paper
          variant="outlined"
          sx={{ position: "sticky", bottom: 0, mt: 2, p: 1.5, zIndex: 1 }}
        >
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography variant="caption" color="text.secondary">
              {reopening
                ? "再開課會重跑發布檢核；關閉期間若移除了必要內容，會在上方列出缺漏。尚未變更任何資料。"
                : status === "DRAFT"
                  ? "儲存草稿可隨時繼續編輯。發布檢核：至少 1 章節 + 1 教材、至少 1 組受訓對象、起訖時間已填、各測驗配分總和 = 100 且每測驗至少 1 題、無引用之廢止文件。"
                  : "已發布課程的編輯即時生效，不需重新發布。"}
            </Typography>
            <Stack direction="row" spacing={1}>
              {/* 再開課模式換成專屬的兩顆（#428）。
                  ⚠️ 一般的「儲存」在此刻意**不顯示**——`reopen` 是另一支端點，它會跑
                  `ensure_reopenable` 與發布檢核。若教師按了「儲存」，時間會以一般更新
                  寫入而**課程仍是關閉的**，那是一個看起來成功、實際沒再開課的結果。 */}
              {reopening ? (
                <>
                  <Button size="small" disabled={reopenMut.isPending} onClick={cancelReopen}>
                    取消再開課
                  </Button>
                  <Button
                    size="small"
                    variant="contained"
                    // 時間有錯時走的是 `reopenCheckMut`——它進行中也要擋，否則連點會連送預檢
                    // （與發布 / 再開課共用限流配額，security review LOW）
                    disabled={reopenMut.isPending || reopenCheckMut.isPending}
                    onClick={submitReopen}
                  >
                    確認再開課
                  </Button>
                </>
              ) : (
                <>
                  {/*
                    刪除草稿（#457）。後端與 `coursesApi.remove` 早就有了，缺的一直是這顆。

                    ⚠️ **刻意排在最左、與「儲存並發布」隔著兩顆按鈕。** 本專案的 `confirm`
                    確認鈕一律主色、不提供危險色（見 `NotificationContext`），所以誤點的
                    防線只剩版面距離——而這兩個動作的誤點代價完全不對稱。

                    `!isNew`：新增模式下課程還沒寫進 DB，沒有 `course_id` 可刪；此時該做的
                    是直接離開（「取消」），不是刪除一個不存在的東西。
                  */}
                  {status === "DRAFT" && !isNew && (
                    <Button size="small" color="error" onClick={requestDeleteDraft}>
                      刪除草稿
                    </Button>
                  )}
                  <Button size="small" onClick={() => navigate("/et/courses")}>
                    取消
                  </Button>
                  <Button size="small" variant="outlined" disabled={saveMut.isPending} onClick={handleSave}>
                    {status === "DRAFT" ? "儲存草稿" : "儲存"}
                  </Button>
                  {/*
                    僅草稿可發布。已發布課程的後續編輯**即時生效、不需重新發布**（AC 28），
                    故發布不是常駐動作——已發布時直接不顯示，而非顯示一顆按了會回
                    `ET_PUBLISH_002` 的按鈕。
                  */}
                  {status === "DRAFT" && (
                    <Tooltip title={isNew ? "請先儲存草稿後再發布" : ""}>
                      <span>
                        <Button
                          size="small"
                          variant="contained"
                          disabled={isNew || saveThenCheckMut.isPending}
                          onClick={openPublish}
                        >
                          儲存並發布
                        </Button>
                      </span>
                    </Tooltip>
                  )}
                </>
              )}
            </Stack>
          </Stack>
        </Paper>
      )}

      <PublishDialog
        open={publishOpen}
        checking={checkMut.isPending}
        publishing={publishMut.isPending}
        blockers={blockers}
        result={publishResult}
        quizNames={quizNames}
        chapterNames={chapterNames}
        itemChapterNames={itemChapterNames}
        onPublish={() => publishMut.mutate()}
        onClose={() => {
          // 🔴 **關閉結果視窗後才導回列表**（#358 第 4 項），不在 `onSuccess` 當下導。
          //
          // 「儲存草稿」成功即導回（第 274 行），發布原本卻停在編輯頁——教師按完
          // 「儲存並發布」後看不出有沒有成功。但不能照抄草稿的做法：`publishResult`
          // 帶著「已依受訓單位標籤帶入 N 位學員」與**邀請碼**，立刻導回等於把那兩樣
          // 從畫面上抽掉，而邀請碼只有這一次會顯示。
          //
          // 故導回時機綁在使用者**主動關閉**結果視窗。發布失敗時不會有 `publishResult`
          // （改設 `blockers` 留在原地讓他補缺漏），所以這裡不會誤導向。
          const published = publishResult !== null
          // 有缺漏時關閉 → 進入標示模式（#558）。檢核中途就關掉的不算——那時還不知道缺什麼
          const hadBlockers = !published && !checkMut.isPending && blockers.length > 0
          setPublishOpen(false)
          setPublishResult(null)
          if (published) navigate("/et/courses")
          else if (hadBlockers) setHighlight("publish")
        }}
      />


      <Dialog open={chapterDialogOpen} onClose={() => setChapterDialogOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>新增章節</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            size="small"
            fullWidth
            label="章節名稱"
            value={chapterDraft}
            error={Boolean(chapterError)}
            helperText={chapterError}
            onChange={(e) => setChapterDraft(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setChapterDialogOpen(false)}>取消</Button>
          <Button onClick={() => void submitChapter(true)}>儲存並繼續新增</Button>
          <Button variant="contained" onClick={() => void submitChapter(false)}>
            儲存
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={conflictOpen} onClose={() => setConflictOpen(false)}>
        <DialogTitle>儲存失敗</DialogTitle>
        <DialogContent>
          <DialogContentText>內容已被其他裝置變更，請重新整理後再儲存。</DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setConflictOpen(false)
              invalidate()
            }}
          >
            重新載入
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
    </LocalizationProvider>
  )
}
