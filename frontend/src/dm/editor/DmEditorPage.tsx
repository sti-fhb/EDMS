import AddIcon from "@mui/icons-material/Add"
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import Alert from "@mui/material/Alert"
import Autocomplete from "@mui/material/Autocomplete"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Divider from "@mui/material/Divider"
import FormHelperText from "@mui/material/FormHelperText"
import IconButton from "@mui/material/IconButton"
import MenuItem from "@mui/material/MenuItem"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useBlocker, useNavigate, useParams } from "react-router-dom"

import {
  CHANGE_SUMMARY_MAX_LEN,
  describeUploadLimits,
  DOC_NAME_MAX_LEN,
  EMPTY_AUDIENCE_PAIR,
  EMPTY_EDITOR_FORM,
  isPreviewableMime,
  makeEditorSchema,
  MANUAL_CATEGORY,
  TRAINING_CATEGORY,
  VERSION_NO_MAX_LEN,
} from "./schemas"
import type { AudiencePair, EditorForm, OptionItem } from "./schemas"
import { editorApi } from "./editorService"
import { useDocTags, useDraftMeta, useEditorOptions, useReviewers, useUploadLimits } from "./useEditor"
import { ScreenHeader } from "../../components/ScreenHeader"
import { dmTagGroupLabel } from "../../constants/dmTagGroups"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"
import { formatDateTaipei } from "../../utils/date"
import { getFieldErrors } from "../../utils/zodUtils"
import { useDetail, useVersions } from "../detail/useDetail"

const VERSION_NO_HINT = "由撰寫者自行輸入（系統不建議版號）"

/** 續編時版號 / 摘要帶的是上次草稿值（#308），以此提示取代原本「留白」的提醒作用。 */
const DRAFT_PREFILL_HINT = "此為上次草稿內容，送審前請確認反映本次變更"

/** 後端 error_code → 對應表單欄位（用於 inline 標紅）；未列者以 Snackbar 呈現。 */
const ERROR_FIELD: Record<string, keyof EditorForm> = {
  DM_DOC_005: "audience_pairs", // 無可見對象（DM-MSG-DM08-008）
  DM_DOC_006: "version_no", // 版號空 / 重複（DM-MSG-DM08-009）
  DM_DOC_007: "func_code", // 手冊 func 重複（DM-MSG-DM08-003）
  DM_REVIEW_001: "reviewer_id", // 審核者為撰寫者本人
}

/**
 * 文件新增與編輯（US5 / DM08）雙模式表單。
 *
 * - **新增模式**（`/dm/documents/new`）：填 名稱 / 分類 /（MANUAL）func / 可見對象 / 檢索標籤 /
 *   首版版號 / 摘要 + 上傳單檔 → 存草稿 或 送簽（指定審核者）。
 * - **編輯模式**（`/dm/documents/:docId/edit`）：名稱 / 分類 / func 唯讀；改版號 / 摘要 / 檔案 /
 *   標籤 → 存草稿 或 送簽。
 *
 * 標籤採兩層（#377）：此處所改為該版本之提議值（後端寫 `DM_VERSION_TAG`），**核准發布時才生效**；
 * 表單預帶本人進行中版本之快照，無則帶文件層現值。TRAINING 分類隱藏可見對象欄且送出時清空
 * （spec_us5 FR-009：教材由 ET 引用，不設可見對象）。
 *
 * 送簽 = 先建草稿（新增 POST /documents 或加版 POST /versions）再 POST /submit；建草稿結果快取於
 * `persisted`，送簽失敗（如 func 重複）可原地重試而不重複建立、亦不觸發單一草稿擋（DM_DOC_009）。
 */
export function DmEditorPage() {
  const { docId } = useParams<{ docId?: string }>()
  const isNew = !docId
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { message, confirm } = useNotification()

  const { data: options } = useEditorOptions()
  // #455：上傳說明與選檔器的 accept 一律讀參數，不再寫死
  const { data: uploadLimits } = useUploadLimits()
  const { data: reviewers } = useReviewers()
  // 續編模式 meta（草稿匣「繼續編輯」）：有本人草稿 → 續編（draftMeta + PUT 更新既有版本）；
  // 無（後端 404 → null）→ 從 DM07 詳細載已發布文件 meta、走「加新版」（addVersion）。
  const {
    data: draftMeta,
    isPending: draftMetaPending,
    isFetching: draftMetaFetching,
  } = useDraftMeta(docId ?? "", !isNew)
  const isContinueDraft = !isNew && !!draftMeta
  // 續編首版草稿（父文件 DRAFT）不打 DM07 詳細 / 版本（DRAFT 不對外瀏覽會 404）；加新版 / 續編新版本才需。
  const wantPublishedMeta = !isNew && !draftMetaPending && draftMeta?.doc_status !== "DRAFT"
  const { data: detail, isPending: detailLoading } = useDetail(isNew ? "" : docId!, wantPublishedMeta)
  const { data: recentVersions } = useVersions(isNew ? "" : docId!, wantPublishedMeta)
  const {
    data: docTags,
    isFetching: docTagsFetching,
    isPending: docTagsPending,
    isError: docTagsError,
  } = useDocTags(isNew ? "" : docId!, !isNew)

  const [form, setForm] = useState<EditorForm>(EMPTY_EDITOR_FORM)
  const [file, setFile] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  // 已建立之草稿識別（送簽失敗重試時沿用，避免重複建立 / 單一草稿擋）
  const persisted = useRef<{ doc_id: string; version_id: number } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // 我方主動導向（存草稿 / 送簽成功、取消確認後）→ 略過離開攔截，避免自家導向被再次攔問。
  const bypassGuard = useRef(false)
  // 編輯模式標籤只預帶一次，之後尊重使用者編輯（避免 refetch 覆蓋）。
  const tagsPrefilled = useRef(false)
  // 續編模式草稿內容（名稱 / 版號 / 摘要 / 審核者）只預帶一次。
  const metaPrefilled = useRef(false)

  // 續編首版草稿（父 DRAFT）視同新增般開放全欄位編輯（分類除外，綁 DOC_ID）；加新版沿用唯讀身份欄。
  const editCategoryCode = isContinueDraft ? draftMeta?.category_code : detail?.category_code
  // isManual：新增模式看 form；續編首版看該文件分類（供 func 欄可編）。
  const isManual = isNew ? form.category_code === MANUAL_CATEGORY : editCategoryCode === MANUAL_CATEGORY
  // isTraining（同上判定規則）：訓練教材由 ET 引用、ET 取教材不套可見性，故可見對象欄隱藏且不檢核（#377）
  const isTraining = isNew ? form.category_code === TRAINING_CATEGORY : editCategoryCode === TRAINING_CATEGORY
  const fileNotPreviewable = file !== null && !isPreviewableMime(file.type)

  // 續編模式名稱可編（首版草稿 Q1=A）；其餘編輯情境名稱唯讀。
  const nameEditable = isContinueDraft && !!draftMeta?.name_editable
  // 已廢止文件之孤兒草稿：不可續編 / 送簽（後端亦擋 DM_DOC_018）；此處鎖動作、提示改用刪除。
  const draftObsolete = isContinueDraft && draftMeta?.doc_status === "OBSOLETE"
  // 續編時版號 / 摘要帶的是上次草稿值（#308），於欄位下方提示；新增文件無此情形。
  const draftPrefillHint = isContinueDraft && draftMeta ? DRAFT_PREFILL_HINT : ""
  // 編輯模式身份欄顯示值：續編取 draftMeta、加新版取 DM07 詳細。
  const editName = isContinueDraft ? (draftMeta?.doc_name ?? "") : (detail?.doc_name ?? "")
  const editCategoryName = isContinueDraft ? (draftMeta?.category_name ?? "") : (detail?.category_name ?? "")
  const editFuncCode = isContinueDraft ? draftMeta?.func_code : detail?.func_code
  const editFuncName = isContinueDraft ? draftMeta?.func_name : detail?.func_name

  const audienceOptions = options?.audiences ?? []
  const unitOptions = options?.units ?? []
  const retrievalOptions = options?.retrieval_tags ?? []
  /**
   * 陣列層錯誤（未設任何配對，例如把列全刪光）——顯示於區塊下方。
   *
   * 列內的「請選擇單位 / 職位」**不走這裡**：那些由各該欄位自身以紅框 + 紅字 label 呈現（#476），
   * 與頁面其他必填欄位一致；若同時在下方再列一次紅字會變成同一件事講兩遍。
   */
  const audienceError = errors["audience_pairs"]

  /**
   * 以 id 取顯示用選項；**不在 options 內者（已被管理者停用）合成一個標示「（已停用）」的選項**（#624）。
   *
   * 為何需要：`get_editor_options` 只回**啟用中**的標籤，而預帶**刻意不濾** `is_enabled`
   * （濾掉等於讓使用者不知情地把既有標籤送掉——#602 要消滅的形狀）。兩者相減的結果是
   * 「id 在表單裡、卻不在選項裡」，原本 `options.find(...)` 直接落空 ⇒ **該值在畫面上隱形**，
   * 而送出時後端回 `DM_DOC_010`（泛用碼，指不到欄位），使用者看不到要改哪一格。
   *
   * ⛔ 不可改用「預帶時濾掉停用標籤」來解——那只是把靜默清空換個地方留著。
   *
   * 名稱來自預帶回應的 `tag_names`（含已停用者）。查不到名稱時退回顯示 id：那表示資料層
   * 有殘留，顯示 id 仍比整格空白好——使用者至少看得出那裡有東西、能把它移除。
   *
   * 🔴 **「不在 options 裡」有兩個成因**，只有其中一個是停用：
   *
   *   1. 該標籤真的被管理者停用了              → 標示「（已停用）」
   *   2. `options` 還沒載入 / 載入失敗         → **無從判斷**，不得標示
   *
   * 載入閘（下方 `draftMetaPending || docTagsPending || ...`）**刻意不等 options**，所以第 2
   * 種一定會發生：docTags 先到的那段視窗內每個值都不在 options 裡，而 options 請求失敗時更是
   * 永久如此。若一律標成停用，使用者會看到整個表單的標籤都壞掉——那是比隱形更糟的假訊息。
   */
  const optionFor = useCallback(
    (id: string, from: OptionItem[]): OptionItem | null => {
      if (!id) return null
      const hit = from.find((o) => o.code === id)
      if (hit) return hit
      const name = docTags?.tag_names?.[id]
      // 名稱也查不到＝資料層殘留（`DM_TAG` 無刪除功能，正常不會發生），不是「已停用」。
      // 顯示 id 讓使用者至少看得出那裡有東西、能把它移除；但**不加後綴**，因為我們並不知道
      // 它是不是停用——這與下一行是同一個判準：不確定就不要下判斷。
      if (name === undefined) return { code: id, name: id }
      // `options` 為 undefined＝尚未載入或載入失敗；此時同樣無從判斷，只顯示名稱
      return { code: id, name: options ? `${name}（已停用）` : name }
    },
    [docTags?.tag_names, options],
  )

  const selectedRetrieval = useMemo(
    () => form.retrieval_ids.map((id) => optionFor(id, options?.retrieval_tags ?? [])).filter((o) => o !== null),
    [options?.retrieval_tags, form.retrieval_ids, optionFor],
  )

  // 草稿內容欄位（會寫入 DM_DOCUMENT / DM_DOC_VERSION / DM_DOC_TAG）：變更後清草稿快取，
  // 使下次送簽重新建立、避免沿用已過時之草稿。
  /**
   * 使用者一動手就鎖定對應的預帶 guard——背景 refetch 落定後不得覆蓋已輸入的值。
   *
   * 預帶改為「等 isFetching 落下」之後（#396），表單在 refetch 期間**已經可互動**（載入 gate 只擋
   * `draftMetaPending`，有快取時不擋），於是多出一段「使用者已輸入、guard 尚未鎖定」的視窗。若不在此
   * 鎖定，refetch 落定時 prefill effect 會把伺服器值蓋掉使用者剛選的標籤或剛打的版號，且無任何提示。
   */
  const lockPrefillFor = (key: keyof EditorForm) => {
    if (key === "audience_pairs" || key === "retrieval_ids") tagsPrefilled.current = true
    else metaPrefilled.current = true
  }

  const setField = <K extends keyof EditorForm>(key: K, value: EditorForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setDirty(true)
    persisted.current = null
    lockPrefillFor(key)
    setErrors((prev) => ({ ...prev, [key as string]: "" }))
  }

  /**
   * 可見對象配對之增 / 改 / 刪——一律建新陣列，不就地修改（immutability）。
   *
   * 改任一列都會清掉**所有** `audience_pairs.*` 錯誤：Zod 的錯誤 key 帶列索引
   * （`audience_pairs.0.unit_id`），刪列後索引會位移，只清單一 key 會讓舊訊息掛在錯的列上。
   */
  const clearAudienceErrors = () =>
    setErrors((prev) => Object.fromEntries(Object.entries(prev).filter(([k]) => !k.startsWith("audience_pairs"))))

  /**
   * 以 updater 更新配對清單——**必須是函式式的**，不可讀 render 閉包裡的 `form.audience_pairs`。
   *
   * 選完單位會立刻引發 re-render，使用者接著選職位時，若 updater 讀的是上一輪閉包的陣列，
   * 第二次更新會把剛選好的單位蓋回空字串；畫面上看起來就是「單位選了又不見」。
   */
  const setAudiencePairs = (updater: (prev: AudiencePair[]) => AudiencePair[]) => {
    setForm((prev) => ({ ...prev, audience_pairs: updater(prev.audience_pairs) }))
    setDirty(true)
    persisted.current = null
    lockPrefillFor("audience_pairs")
    clearAudienceErrors()
  }

  const addAudiencePair = () => setAudiencePairs((prev) => [...prev, EMPTY_AUDIENCE_PAIR])

  const updateAudiencePair = (idx: number, patch: Partial<AudiencePair>) =>
    setAudiencePairs((prev) => prev.map((pair, i) => (i === idx ? { ...pair, ...patch } : pair)))

  const removeAudiencePair = (idx: number) => setAudiencePairs((prev) => prev.filter((_, i) => i !== idx))

  // 審核者僅為 submit 參數、不屬草稿內容：變更**不可**清草稿快取，否則送簽失敗後改審核者重試
  // 會重複建立文件（新增模式）或誤觸單一草稿擋（編輯模式）。
  const setReviewer = (value: string) => {
    setForm((prev) => ({ ...prev, reviewer_id: value }))
    setDirty(true)
    lockPrefillFor("reviewer_id")
    setErrors((prev) => ({ ...prev, reviewer_id: "" }))
  }

  const onCategoryChange = (value: string) => {
    setForm((prev) => ({ ...prev, category_code: value, func_code: value === MANUAL_CATEGORY ? prev.func_code : "" }))
    setDirty(true)
    persisted.current = null
  }

  const onPickFile = (f: File | null) => {
    setFile(f)
    setDirty(true)
    persisted.current = null
    setErrors((prev) => ({ ...prev, file: "" }))
    if (f && !isPreviewableMime(f.type)) {
      // Office 等非可預覽格式：警示 + 二次確認（DM-MSG-DM08-002）
      confirm({
        title: "此檔案無法線上預覽",
        content: "所選檔案（如 Word / Excel）閱覽者將只能下載、無法線上預覽。是否仍使用此檔案？",
        okText: "仍使用此檔案",
        cancelText: "改傳其他檔案",
        onOk: () => {},
        onCancel: () => {
          setFile(null)
          if (fileInputRef.current) fileInputRef.current.value = ""
        },
      })
    }
  }

  function applyApiError(e: unknown) {
    const { errorCode, errorMessage } = toApiError(e)
    const field = ERROR_FIELD[errorCode]
    if (field) {
      setErrors((prev) => ({ ...prev, [field]: errorMessage }))
    } else {
      message.error(errorMessage) // DM_DOC_004 / 008 / 009 / REVIEW_002 等
    }
  }

  /** 建立 / 沿用草稿（新增→createDocument；編輯→addVersion）。檔案可為 null（存草稿允許不附）。 */
  async function persistDraft(): Promise<{ doc_id: string; version_id: number }> {
    if (persisted.current) return persisted.current
    let ids: { doc_id: string; version_id: number }
    if (isNew) {
      const r = await editorApi.createDocument({
        doc_name: form.doc_name.trim(),
        category_code: form.category_code,
        func_code: isManual ? form.func_code : "",
        audience_pairs: isTraining ? [] : form.audience_pairs, // TRAINING 不掛可見對象（切換分類後亦不殘留）
        retrieval_ids: form.retrieval_ids,
        version_no: form.version_no.trim(),
        change_summary: form.change_summary.trim(),
        assigned_reviewer: form.reviewer_id, // 存草稿記住指定審核者（供續編預帶）
        file,
      })
      ids = { doc_id: r.doc_id, version_id: r.version_id }
    } else if (isContinueDraft) {
      // 續編：更新既有 DRAFT 版本（in-place，不另開版本 → 不撞單一草稿唯一索引）
      const r = await editorApi.updateDraftVersion(docId!, draftMeta!.draft_version_id, {
        doc_name: nameEditable ? form.doc_name.trim() : null, // 首版草稿可改名（Q1=A）；已發布文件唯讀 → null
        func_code: nameEditable && isManual ? form.func_code : null, // 首版手冊類可改 func；其餘 null
        assigned_reviewer: form.reviewer_id, // 存草稿記住指定審核者（供續編預帶）
        version_no: form.version_no.trim(),
        change_summary: form.change_summary.trim(),
        audience_pairs: isTraining ? [] : form.audience_pairs, // TRAINING 不掛可見對象（切換分類後亦不殘留）
        retrieval_ids: form.retrieval_ids,
        file,
      })
      ids = { doc_id: docId!, version_id: r.version_id }
    } else {
      const r = await editorApi.addVersion(docId!, {
        version_no: form.version_no.trim(),
        change_summary: form.change_summary.trim(),
        assigned_reviewer: form.reviewer_id, // 存草稿記住指定審核者（供續編預帶）
        audience_pairs: isTraining ? [] : form.audience_pairs, // TRAINING 不掛可見對象（切換分類後亦不殘留）
        retrieval_ids: form.retrieval_ids,
        file,
      })
      ids = { doc_id: docId!, version_id: r.version_id }
    }
    persisted.current = ids
    return ids
  }

  // 成功 / 取消後導向：新增 → 文件庫；續編草稿 → 個人專區草稿匣（首版草稿之父文件為 DRAFT、詳細頁會 404，
  // 且續編入口本就來自草稿匣，故回草稿匣，Round-1 回饋）；加新版 → 原文件詳細頁（文件已發布可正常瀏覽）。
  const destAfter = () => (isNew ? "/dm/library" : isContinueDraft ? "/dm/me?tab=drafts" : `/dm/documents/${docId}`)

  // 我方主動導向：先舉旗略過離開攔截再 navigate。
  const go = (path: string) => {
    bypassGuard.current = true
    navigate(path)
  }

  function validate(forSubmit: boolean): boolean {
    const schema = makeEditorSchema({ isNew, isManual, forSubmit, isTraining, requireName: nameEditable })
    const result = schema.safeParse(form)
    const fieldErrors = getFieldErrors(result.success ? null : result.error)
    // 檔案僅送簽時必填；存草稿可先不附檔（US5「存草稿不卡」）。續編既有草稿若已有檔案（draftMeta.file_name），
    // 未重新上傳亦視為已附檔（沿用既有檔）→ 不誤要求上傳（Round-1 回饋）。
    const hasExistingFile = isContinueDraft && !!draftMeta?.file_name
    if (forSubmit && !file && !persisted.current && !hasExistingFile) fieldErrors.file = "請選擇要上傳的檔案"
    setErrors(fieldErrors)
    return Object.keys(fieldErrors).length === 0
  }

  // 續編寫入後失效相關查詢，避免下次再進編輯讀到舊快取（誤以為沒存到，Round-1 回饋）。
  const invalidateAfterWrite = () => {
    if (isNew || !docId) return
    qc.invalidateQueries({ queryKey: ["dm-editor", "doc-tags", docId] })
    qc.invalidateQueries({ queryKey: ["dm-editor", "draft-meta", docId] })
    qc.invalidateQueries({ queryKey: ["dm-detail", docId] })
    qc.invalidateQueries({ queryKey: ["dm-personal", "drafts"] })
  }

  async function handleSaveDraft() {
    if (!validate(false)) return
    setBusy(true)
    try {
      await persistDraft()
      invalidateAfterWrite()
      message.success("已儲存為草稿") // DM-MSG-DM08-007
      setDirty(false)
      go(destAfter())
    } catch (e) {
      applyApiError(e)
    } finally {
      setBusy(false)
    }
  }

  async function handleSubmit() {
    if (!validate(true)) return
    setBusy(true)
    try {
      const ids = await persistDraft()
      await editorApi.submit(ids.doc_id, { version_id: ids.version_id, assigned_reviewer: form.reviewer_id })
      invalidateAfterWrite()
      // ⛔ 不宣稱通知（#677）：`DOC_SUBMIT` 的 CHANNEL 已由 BOTH 改為 MSG（#554），不寄信；
      // 審核者改由 DM02 簽核中心的待處理清單看到。
      message.success("已送交簽核") // DM-MSG-DM08-006
      setDirty(false)
      go(destAfter())
    } catch (e) {
      applyApiError(e)
    } finally {
      setBusy(false)
    }
  }

  function handleCancel() {
    // 取消鈕：回來源頁（新增→文件庫、續編草稿→草稿匣、加新版→原詳細頁）。有未存變更先二次確認
    //（DM-MSG-DM08-005），確認後以 go() 略過離開攔截，避免與 useBlocker 重複彈窗。
    const leave = () => go(destAfter())
    if (!dirty) {
      leave()
      return
    }
    confirm({
      title: "尚未儲存",
      content: "編輯項目將不會保留，確定要離開嗎？",
      okText: "離開不儲存",
      cancelText: "繼續編輯",
      onOk: leave,
    })
  }

  // 離開攔截（DM-MSG-DM08-005）：表單有未存變更且非我方主動導向（go）時，攔下其他 in-app 導向
  //（左側功能列切換、瀏覽器返回等），彈同款二次確認。取消鈕自帶確認、走 go() 不重複攔問。
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && !bypassGuard.current && currentLocation.pathname !== nextLocation.pathname,
  )
  useEffect(() => {
    if (blocker.state !== "blocked") return
    confirm({
      title: "尚未儲存",
      content: "編輯項目將不會保留，確定要離開嗎？",
      okText: "離開不儲存",
      cancelText: "繼續編輯",
      onOk: () => blocker.proceed(),
      onCancel: () => blocker.reset(),
    })
  }, [blocker, confirm])

  // 編輯模式：載入文件現有標籤 → 一次性預帶進表單（不標記 dirty，尊重後續使用者編輯）。
  //
  // ⚠️ 必須等 `isFetching` 落下才預帶。TanStack Query 預設 `staleTime: 0`，重進本頁時會**同步吐出
  // 上次的快取值**再背景 refetch；若此時就預帶，`tagsPrefilled` 這個一次性 guard 會鎖住舊值，
  // 稍後 refetch 回來的新值再也寫不進表單——表現為「改了標籤存檔後，下次開啟還是舊值，要再改一次
  // 才會真的存」（#377 手測回報）。
  useEffect(() => {
    if (isNew || tagsPrefilled.current || !docTags || docTagsFetching) return
    tagsPrefilled.current = true
    setForm((prev) => ({
      ...prev,
      // 文件原本沒有配對（或全被略過）時仍保留一列空白，否則畫面只剩一顆「新增」按鈕（#476）
      audience_pairs: docTags.audience_pairs.length > 0 ? docTags.audience_pairs : [EMPTY_AUDIENCE_PAIR],
      retrieval_ids: docTags.retrieval_ids,
    }))
  }, [isNew, docTags, docTagsFetching])

  // 續編模式：一次性預帶既有草稿內容——名稱 / func / 版號 / 摘要 / 前次審核者，四種情況
  // （首版 / 新版本 × 自存 / 退回）一致。
  //
  // #308 推翻 Round-1 的「新版本草稿版號 / 摘要留白」：留白的目的是逼使用者填全新版號，但
  // 送審時 `version_no_taken`（editor/service.py）已擋掉與同文件既有版本重複的版號，留白對此
  // 沒有額外貢獻；代價卻是使用者看不到自己上次寫了什麼（值其實在 DB 裡），且與其他欄位都預帶
  // 的行為不一致，看起來像資料遺失。改以欄位下方的提示達成「請確認反映本次變更」的提醒。
  // 同 tagsPrefilled：等 `isFetching` 落下才預帶，否則一次性 guard 會鎖住重進本頁時同步吐出的舊快取。
  useEffect(() => {
    if (isNew || metaPrefilled.current || !draftMeta || draftMetaFetching) return
    metaPrefilled.current = true
    setForm((prev) => ({
      ...prev,
      doc_name: draftMeta.doc_name,
      func_code: draftMeta.func_code ?? "",
      version_no: draftMeta.version_no ?? "",
      change_summary: draftMeta.change_summary ?? "",
      reviewer_id: draftMeta.assigned_reviewer ?? "",
    }))
  }, [isNew, draftMeta, draftMetaFetching])

  // 續編須等 draftMeta 解析（決定續編 / 加新版）；加新版情境再等 DM07 詳細載入。
  //
  // 標籤也必須等（#602）：表單若在標籤未到位時就渲染，使用者會看到空的標籤欄、以為本來就是空的。
  // 核准發布時 `apply_version_tags_to_doc` 是**差異式覆寫**（目標集外的有效列軟刪除），於是：
  //
  // - **檢索標籤**：送簽無任何檢核（FR-001 列為選填）→ 一路通到核准，文件的適用模組 / 文件性質 /
  //   法規關聯被整組刪掉，該文件從此用這些條件篩不到，全程無錯誤訊息。
  // - **可見對象**：送簽要求至少 1 組（DM_DOC_005），所以不會變成空的——但使用者會被迫**從頭猜一組**
  //   填進去（最自然的反應是挑「全單位 + 全體」），核准後文件層可見對象就被那一組換掉。
  //   這是**存取範圍被意外放寬或縮小**，而簽核頁只顯示該版本提議的標籤、無新舊對照，審核者看不出差異。
  // ⚠️ 用 `isPending`（還沒有資料）而**不是** `isFetching`：後者在有快取的背景 refetch 期間也為真，
  // 會推翻 #396 的刻意設計（refetch 期間表單本來就該可互動，競態由 `lockPrefillFor` 鎖住）。
  if (!isNew && (draftMetaPending || docTagsPending || (!draftMeta && detailLoading))) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
        <CircularProgress />
      </Box>
    )
  }

  // 標籤**從來沒取到**就不開放編輯（#602）。⛔ 不可改成「顯示警告但仍放行」——使用者會照樣存檔，
  // 而送出的空標籤會在核准發布時清掉文件既有的檢索標籤，全程沒有任何錯誤訊息。
  //
  // ⚠️ `&& !docTags` 不可省：TanStack Query v5 在「先前成功過、背景 refetch 失敗」時 status 轉 error
  // 但**舊 data 仍保留**，於是 isError 與 data 同時為真。那個情境標籤早已預帶、沒有送出空值的風險，
  // 若一併擋掉，使用者填到一半切出去再切回來就會被換成錯誤頁、未存編輯全丟——比本 issue 要修的更糟。
  // 這與上面載入閘選 `isPending` 是同一個對稱性：兩道閘都只針對「手上根本沒有資料」。
  if (!isNew && docTagsError && !docTags) {
    return (
      <Box>
        <ScreenHeader code="DM08" />
        <Alert severity="error" sx={{ mb: 2 }}>
          無法載入此文件現有的標籤，請重新整理後再試。
          <Typography variant="body2" sx={{ mt: 0.5 }}>
            為避免送出時清空既有的可見對象與檢索標籤，本頁暫不開放編輯。
          </Typography>
        </Alert>
        <Button variant="outlined" onClick={() => go(destAfter())}>
          返回
        </Button>
      </Box>
    )
  }

  return (
    <Box>
      {/* 不加返回鍵：離開一律走底部「取消」，它帶有未儲存變更的二次確認 */}
      <ScreenHeader code="DM08" title={isNew ? "新增文件" : `編輯文件 — ${editName}`} />

      {draftObsolete && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          此文件已廢止，無法續編或送審。請至個人專區草稿匣刪除此草稿。
        </Alert>
      )}

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "2fr 1fr" }, gap: 2 }}>
        {/* 左：基本資料 + 版本 + 上傳 */}
        <Stack spacing={2}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              基本資料
            </Typography>
            <Stack spacing={2}>
              {isNew ? (
                <>
                  {/* 新增模式：身份欄可編 */}
                  <TextField
                    label="文件名稱"
                    required
                    fullWidth
                    size="small"
                    value={form.doc_name}
                    onChange={(e) => setField("doc_name", e.target.value)}
                    error={!!errors.doc_name}
                    helperText={errors.doc_name}
                    slotProps={{ htmlInput: { maxLength: DOC_NAME_MAX_LEN } }}
                  />
                  <TextField
                    select
                    label="分類"
                    required
                    fullWidth
                    size="small"
                    value={form.category_code}
                    onChange={(e) => onCategoryChange(e.target.value)}
                    error={!!errors.category_code}
                    helperText={errors.category_code}
                  >
                    {(options?.categories ?? []).map((c) => (
                      <MenuItem key={c.code} value={c.code}>
                        {c.name}
                      </MenuItem>
                    ))}
                  </TextField>
                  {isManual && (
                    <TextField
                      select
                      label="關聯作業項目"
                      required
                      fullWidth
                      size="small"
                      value={form.func_code}
                      onChange={(e) => setField("func_code", e.target.value)}
                      error={!!errors.func_code}
                      helperText={errors.func_code}
                    >
                      {(options?.funcs ?? []).map((f) => (
                        <MenuItem key={f.code} value={f.code}>
                          {f.code} — {f.name}
                        </MenuItem>
                      ))}
                    </TextField>
                  )}
                </>
              ) : (
                <>
                  {/* 編輯模式：分類 / func 唯讀；文件名稱於續編首版草稿（未發布）時可改（Q1=A），其餘唯讀 */}
                  {nameEditable ? (
                    <TextField
                      label="文件名稱"
                      required
                      fullWidth
                      size="small"
                      value={form.doc_name}
                      onChange={(e) => setField("doc_name", e.target.value)}
                      error={!!errors.doc_name}
                      helperText={errors.doc_name || "此文件尚未發布，續編期間可修改名稱"}
                      slotProps={{ htmlInput: { maxLength: DOC_NAME_MAX_LEN } }}
                    />
                  ) : (
                    <TextField label="文件名稱" fullWidth size="small" value={editName} disabled />
                  )}
                  <TextField label="分類" fullWidth size="small" value={editCategoryName} disabled />
                  {/* 首版草稿續編開放全欄位編輯：手冊類 func 可改（下拉）；其餘情境唯讀顯示 */}
                  {nameEditable && isManual ? (
                    <TextField
                      select
                      label="關聯作業項目"
                      required
                      fullWidth
                      size="small"
                      value={form.func_code}
                      onChange={(e) => setField("func_code", e.target.value)}
                      error={!!errors.func_code}
                      helperText={errors.func_code}
                    >
                      {(options?.funcs ?? []).map((f) => (
                        <MenuItem key={f.code} value={f.code}>
                          {f.code} — {f.name}
                        </MenuItem>
                      ))}
                    </TextField>
                  ) : (
                    editFuncCode && (
                      <TextField
                        label="關聯作業項目"
                        fullWidth
                        size="small"
                        value={`${editFuncCode} — ${editFuncName ?? ""}`}
                        disabled
                      />
                    )
                  )}
                </>
              )}
              {/* 可見對象 + 檢索標籤：新增與編輯模式皆可編；核准發布時才生效（#377）。
                  TRAINING 不設可見對象——教材一律由教育訓練模組引用，故整欄隱藏。 */}
              {isTraining ? (
                <Alert severity="info" variant="outlined">
                  訓練教材由教育訓練模組引用，不需設定可見對象
                </Alert>
              ) : (
                <Box>
                  {/* 一列＝一組 (單位, 職位) 配對。兩欄必須成對設定：掛 [(軍醫局, 護理師), (三總, 行政人員)]
                      意為「僅此兩種人」，若拆成兩個獨立多選會連「軍醫局的行政人員」也一併看得到（#437）。 */}
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    可見對象
                  </Typography>
                  <Stack spacing={1}>
                    {form.audience_pairs.map((pair, idx) => (
                      <Stack
                        // 完全受控（值皆來自 state），用索引不會有狀態殘留；把值寫進 key 會讓
                        // 「選完單位」當下整列卸載重建，徒增時序風險。
                        key={idx}
                        direction="row"
                        spacing={1}
                        alignItems="flex-start"
                      >
                        <Autocomplete
                          size="small"
                          sx={{ flex: 1 }}
                          options={unitOptions}
                          value={optionFor(pair.unit_id, unitOptions)}
                          onChange={(_, v: OptionItem | null) =>
                            updateAudiencePair(idx, { unit_id: v?.code ?? "" })
                          }
                          getOptionLabel={(o) => o.name}
                          isOptionEqualToValue={(a, b) => a.code === b.code}
                          renderInput={(params) => (
                            <TextField
                              {...params}
                              label="單位"
                              required
                              error={!!errors[`audience_pairs.${idx}.unit_id`]}
                            />
                          )}
                        />
                        <Autocomplete
                          size="small"
                          sx={{ flex: 1 }}
                          options={audienceOptions}
                          value={optionFor(pair.audience_id, audienceOptions)}
                          onChange={(_, v: OptionItem | null) =>
                            updateAudiencePair(idx, { audience_id: v?.code ?? "" })
                          }
                          getOptionLabel={(o) => o.name}
                          isOptionEqualToValue={(a, b) => a.code === b.code}
                          renderInput={(params) => (
                            <TextField
                              {...params}
                              label="職位"
                              required
                              error={!!errors[`audience_pairs.${idx}.audience_id`]}
                            />
                          )}
                        />
                        <IconButton
                          size="small"
                          aria-label={`移除第 ${idx + 1} 組可見對象`}
                          onClick={() => removeAudiencePair(idx)}
                        >
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </Stack>
                    ))}
                  </Stack>
                  <Button size="small" startIcon={<AddIcon />} onClick={addAudiencePair} sx={{ mt: 1 }}>
                    新增可見對象
                  </Button>
                  <FormHelperText error={!!audienceError}>
                    {audienceError ||
                      "每組為「單位 + 職位」；「全單位」＝不限單位、「全體」＝不限職位。核准發布後生效"}
                  </FormHelperText>
                </Box>
              )}
              <Autocomplete
                multiple
                size="small"
                options={retrievalOptions}
                value={selectedRetrieval}
                onChange={(_, v: OptionItem[]) => setField("retrieval_ids", v.map((o) => o.code))}
                getOptionLabel={(o) => o.name}
                isOptionEqualToValue={(a, b) => a.code === b.code}
                groupBy={(o) => dmTagGroupLabel(o.group_code)}
                renderInput={(params) => <TextField {...params} label="檢索標籤（選填）" />}
              />
            </Stack>
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              版本資訊
            </Typography>
            {!isNew && detail?.current_version_no && (
              <TextField
                label="目前版本"
                fullWidth
                size="small"
                value={detail.current_version_no}
                disabled
                sx={{ mb: 2 }}
              />
            )}
            <Stack spacing={2}>
              <TextField
                label={isNew ? "首版版本號" : "新版本號"}
                required
                fullWidth
                size="small"
                value={form.version_no}
                onChange={(e) => setField("version_no", e.target.value)}
                error={!!errors.version_no}
                helperText={errors.version_no || [VERSION_NO_HINT, draftPrefillHint].filter(Boolean).join("；")}
                slotProps={{ htmlInput: { maxLength: VERSION_NO_MAX_LEN } }}
              />
              <TextField
                label={isNew ? "首版摘要" : "變更摘要"}
                required
                fullWidth
                multiline
                minRows={2}
                size="small"
                value={form.change_summary}
                onChange={(e) => setField("change_summary", e.target.value)}
                error={!!errors.change_summary}
                helperText={errors.change_summary || draftPrefillHint}
                slotProps={{ htmlInput: { maxLength: CHANGE_SUMMARY_MAX_LEN } }}
              />
            </Stack>
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              文件內容（上傳檔案）
            </Typography>
            <Stack spacing={1}>
              <Box
                component="label"
                onDragOver={(e) => {
                  e.preventDefault()
                  setDragOver(true)
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDragOver(false)
                  onPickFile(e.dataTransfer.files?.[0] ?? null)
                }}
                sx={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 0.5,
                  py: 4,
                  px: 2,
                  border: "2px dashed",
                  borderColor: dragOver ? "primary.main" : errors.file ? "error.main" : "divider",
                  borderRadius: 1,
                  bgcolor: dragOver ? "action.selected" : "action.hover",
                  cursor: "pointer",
                  textAlign: "center",
                  transition: "border-color .15s, background-color .15s",
                }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  hidden
                  onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
                />
                <CloudUploadOutlinedIcon sx={{ fontSize: 44, color: "action.active", mb: 0.5 }} />
                {file ? (
                  <>
                    <Typography variant="body2" color="text.primary">
                      已選擇：{file.name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      點擊或拖拉可重新選擇
                    </Typography>
                  </>
                ) : isContinueDraft && draftMeta?.file_name ? (
                  // 續編既有草稿之已存檔案：比照新增之「已選擇」樣式（未重新上傳則沿用）
                  <>
                    <Typography variant="body2" color="text.primary">
                      已選擇：{draftMeta.file_name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      點擊或拖拉可重新選擇
                    </Typography>
                  </>
                ) : (
                  <>
                    <Typography variant="body2" color="text.secondary">
                      拖拉檔案至此或<Box component="span" sx={{ color: "primary.main" }}>點擊選擇</Box>
                    </Typography>
                    {/* #455：文案改讀 `DP_PARAM`。⚠️ 寫死時 IT 改完 DB 之後這行仍說舊話，
                        而 #469 把唯讀參數改為 HIDDEN 之後，**這行是系統內唯一顯示上限
                        的地方**——它若說謊就沒有第二處可以對照。 */}
                    <Typography variant="caption" color="text.secondary">
                      {uploadLimits ? describeUploadLimits(uploadLimits) : "上傳限制載入中…"}
                    </Typography>
                  </>
                )}
              </Box>
              {errors.file && (
                <Typography variant="caption" color="error">
                  {errors.file}
                </Typography>
              )}
              {fileNotPreviewable && (
                <Alert severity="warning">此檔案格式（如 Word / Excel）無法線上預覽，閱覽者僅能下載。</Alert>
              )}
            </Stack>
          </Paper>
        </Stack>

        {/* 右：指定審核者 + 動作 */}
        <Stack spacing={2}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              送交簽核
            </Typography>
            <TextField
              select
              label="指定審核者"
              fullWidth
              size="small"
              value={form.reviewer_id}
              onChange={(e) => setReviewer(e.target.value)}
              error={!!errors.reviewer_id}
              helperText={errors.reviewer_id || "送簽時必填；不含您本人"}
            >
              {(reviewers ?? []).map((r) => (
                <MenuItem key={r.user_id} value={r.user_id}>
                  {r.user_name}
                </MenuItem>
              ))}
            </TextField>
            <Divider sx={{ my: 2 }} />
            <Stack spacing={1}>
              <Button variant="contained" onClick={handleSubmit} disabled={busy || draftObsolete}>
                送交簽核
              </Button>
              <Button variant="outlined" onClick={handleSaveDraft} disabled={busy || draftObsolete}>
                儲存為草稿
              </Button>
              <Button color="inherit" onClick={handleCancel} disabled={busy}>
                取消
              </Button>
            </Stack>
          </Paper>

          {/* 最近版本（編輯模式）：呈現本文件近期版本 / 狀態 / 發布日期，供撰寫者對照定版號 */}
          {!isNew && (recentVersions?.length ?? 0) > 0 && (
            <Paper sx={{ p: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                最近版本
              </Typography>
              <Stack divider={<Divider flexItem />} spacing={1}>
                {(recentVersions ?? []).slice(0, 5).map((v) => (
                  <Box
                    key={v.version_id}
                    sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 1 }}
                  >
                    <Box>
                      <Typography variant="body2">{v.version_no}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {formatDateTaipei(v.published_date)}
                      </Typography>
                    </Box>
                    <Typography variant="caption" color={v.is_current ? "success.main" : "text.secondary"}>
                      {v.is_current ? "目前發布版" : "已被取代"}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            </Paper>
          )}
        </Stack>
      </Box>
    </Box>
  )
}