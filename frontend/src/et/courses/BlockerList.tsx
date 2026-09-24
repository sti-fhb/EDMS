import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline"
import List from "@mui/material/List"
import ListItem from "@mui/material/ListItem"
import ListItemIcon from "@mui/material/ListItemIcon"
import ListItemText from "@mui/material/ListItemText"

import { BLOCKER_HINT, blockerGroupLabel, groupBlockers } from "./surveySchemas"
import type { BlockerNames, PublishBlocker } from "./surveySchemas"

interface BlockerListProps {
  blockers: PublishBlocker[]
  names: BlockerNames
}

/**
 * 發布缺漏清單（US3 / #204、#412）。
 *
 * ## 為何抽成共用元件
 *
 * `PublishDialog`（發布）與課程編輯頁的再開課模式呈現的是**同一組缺漏**——
 * 後端兩條路徑共用 `evaluate_publish`。這段渲染原本在兩處各有一份**逐字相同**的
 * 13 行 JSX，而 `blockerLabel` 的沿革已經記過同一個教訓：文案邏輯複製兩份時，
 * `CHAPTER_EMPTY` 一加就同時在兩個地方標錯。
 *
 * #412 的「同類型合併」若照舊只會變成兩份都要改的第三次。
 *
 * ## 同類型缺漏合併為一列
 *
 * 一門課有兩個測驗配分未達 100 時，後端回兩條 blocker（各帶自己的 `target_id`）。
 * 逐條列會讓教師得自己認出「這兩條其實是同一件事」，而「去哪裡修」的提示也會重複。
 * 合併後對象並列於同一列，提示只出現一次。
 *
 * ⚠️ **合併是純呈現**——後端維持「一條缺漏一個 `PublishBlocker`」，那是為了讓
 * `target_id` 能定位到出問題的物件。⛔ 不要反過來要求後端回一個拼好的字串（訊息一律
 * 靜態、對象以 `target_id` 表達，見 `publish_rules.py` 檔頭）。
 */
export function BlockerList({ blockers, names }: BlockerListProps) {
  return (
    <List dense disablePadding>
      {groupBlockers(blockers).map((group) => (
        // `code` 分組後即唯一，不需再補索引。
        <ListItem key={group[0].code} disableGutters>
          <ListItemIcon sx={{ minWidth: 32 }}>
            <ErrorOutlineIcon color="error" fontSize="small" />
          </ListItemIcon>
          <ListItemText primary={blockerGroupLabel(group, names)} secondary={BLOCKER_HINT[group[0].code]} />
        </ListItem>
      ))}
    </List>
  )
}
