import FormatBoldIcon from "@mui/icons-material/FormatBold"
import FormatItalicIcon from "@mui/icons-material/FormatItalic"
import FormatListBulletedIcon from "@mui/icons-material/FormatListBulleted"
import FormatListNumberedIcon from "@mui/icons-material/FormatListNumbered"
import TitleIcon from "@mui/icons-material/Title"
import Box from "@mui/material/Box"
import Divider from "@mui/material/Divider"
import Stack from "@mui/material/Stack"
import ToggleButton from "@mui/material/ToggleButton"
import Typography from "@mui/material/Typography"
import { EditorContent, useEditor } from "@tiptap/react"
import StarterKit from "@tiptap/starter-kit"
import { useEffect } from "react"

/**
 * 教材說明文字之 WYSIWYG 編輯器（ET02）。
 *
 * ## 白名單須與後端一致
 *
 * 後端 `app/et/common/html_sanitize.py` 以 allow-list 消毒，放行 `p/br/strong/em/u/
 * s/ul/ol/li/h3-h6/a/blockquote/code/pre`。這裡刻意**只提供其中一部分**（粗體、
 * 斜體、標題、列表），因為編輯器產出的東西若不在後端白名單內，使用者會遇到
 * 「存檔後格式不見了」而不知道為什麼。
 *
 * 反過來則無妨：後端放行的比編輯器產得出的多，只是留了餘裕。
 *
 * ## 不提供「插入連結」工具（2026-08-26 依實測回饋移除）
 *
 * 原本有一顆連結按鈕，以 `window.prompt` 問網址。移除的理由是那個互動很笨拙，
 * 而教師要放連結時直接把 URL 打進說明文字即可。後端白名單**仍保留 `a` 標籤**，
 * 既有內容中的連結不會因此消失。
 *
 * ## 這不是安全邊界
 *
 * 前端限制只擋得住經由 UI 的輸入。真正的把關在後端——繞過 UI 直接打 API 時，
 * 這裡的白名單一點作用也沒有。
 */

/** 編輯器可產出的標籤，須為後端白名單之子集。 */
const ALLOWED_MARKS = ["bold", "italic", "heading", "bulletList", "orderedList"] as const

interface RichTextEditorProps {
  value: string
  onChange: (html: string) => void
  disabled?: boolean
  /** 無障礙標籤——編輯區為 contenteditable，不是原生表單元件。 */
  label?: string
}

export function RichTextEditor({ value, onChange, disabled = false, label = "說明文字" }: RichTextEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        // 只開放後端白名單內、且 wireframe 工具列有的節點
        heading: { levels: [3, 4] },
        codeBlock: false,
        horizontalRule: false,
        blockquote: false,
      }),
    ],
    content: value,
    editable: !disabled,
    onUpdate: ({ editor: instance }) => onChange(instance.getHTML()),
  })

  // 外部值變更（載入既有教材、切換教材）時同步進編輯器。
  // 比對現值避免打字時被自己的 onUpdate 回寫覆蓋——那會讓游標每按一鍵就跳到開頭。
  useEffect(() => {
    if (editor && value !== editor.getHTML()) {
      editor.commands.setContent(value, { emitUpdate: false })
    }
  }, [editor, value])

  useEffect(() => {
    editor?.setEditable(!disabled)
  }, [editor, disabled])

  if (!editor) return null

  const buttons = [
    { key: "bold", title: "粗體", icon: <FormatBoldIcon fontSize="small" />, run: () => editor.chain().focus().toggleBold().run() },
    { key: "italic", title: "斜體", icon: <FormatItalicIcon fontSize="small" />, run: () => editor.chain().focus().toggleItalic().run() },
    { key: "heading", title: "標題", icon: <TitleIcon fontSize="small" />, run: () => editor.chain().focus().toggleHeading({ level: 3 }).run() },
    { key: "bulletList", title: "項目符號", icon: <FormatListBulletedIcon fontSize="small" />, run: () => editor.chain().focus().toggleBulletList().run() },
    { key: "orderedList", title: "編號清單", icon: <FormatListNumberedIcon fontSize="small" />, run: () => editor.chain().focus().toggleOrderedList().run() },
  ] as const

  return (
    <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, overflow: "hidden" }}>
      <Stack direction="row" spacing={0.5} sx={{ p: 0.5, flexWrap: "wrap", bgcolor: "action.hover" }}>
        {buttons.map((button) => (
          <ToggleButton
            key={button.key}
            value={button.key}
            size="small"
            disabled={disabled}
            selected={button.key === "heading" ? editor.isActive("heading", { level: 3 }) : editor.isActive(button.key)}
            aria-label={button.title}
            title={button.title}
            onClick={button.run}
            sx={{ border: 0, borderRadius: 1 }}
          >
            {button.icon}
          </ToggleButton>
        ))}
      </Stack>
      <Divider />
      <Box
        sx={{
          p: 1.5,
          minHeight: 140,
          cursor: disabled ? "default" : "text",
          bgcolor: disabled ? "action.disabledBackground" : "background.paper",
          "& .ProseMirror": { outline: "none", minHeight: 110, fontSize: "0.875rem" },
          "& .ProseMirror p": { margin: "0 0 0.5em" },
          "& .ProseMirror ul, & .ProseMirror ol": { paddingInlineStart: "1.5em", margin: "0 0 0.5em" },
          "& .ProseMirror a": { color: "primary.main" },
          // 空編輯器沒有任何可點區域時，使用者會不知道能不能打字
          "& .ProseMirror p.is-editor-empty:first-of-type::before": {
            content: '"輸入教材說明⋯"',
            color: "text.disabled",
            float: "left",
            height: 0,
            pointerEvents: "none",
          },
        }}
        onClick={() => !disabled && editor.chain().focus().run()}
      >
        <EditorContent editor={editor} aria-label={label} />
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", px: 1.5, pb: 1 }}>
        支援粗體 / 斜體 / 標題 / 列表；存檔時後端會依白名單消毒，其餘標記將被移除。
      </Typography>
    </Box>
  )
}

export { ALLOWED_MARKS }
