import ChevronRightIcon from "@mui/icons-material/ChevronRight"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Divider from "@mui/material/Divider"
import Link from "@mui/material/Link"
import List from "@mui/material/List"
import ListItemButton from "@mui/material/ListItemButton"
import ListItemText from "@mui/material/ListItemText"
import Paper from "@mui/material/Paper"
import Typography from "@mui/material/Typography"
import { useNavigate } from "react-router-dom"

import { KIND_LABELS } from "./schemas"
import type { AnnouncementItem } from "./schemas"
import { useAnnouncements, useDashboardStats } from "./useDashboard"

/** 單一統計卡（分類名 + 已發布目前版本數）。純資訊、不可點（FR-002）。 */
function StatCard({ name, count }: { name: string; count: number }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, textAlign: "center" }}>
      <Typography variant="h4" sx={{ fontWeight: 700 }}>
        {count}
      </Typography>
      <Chip size="small" label={name} sx={{ mt: 1 }} />
    </Paper>
  )
}

/** 公告列（文件名 + 類型 badge + 摘要 + 發布日期 / 撰寫者 / 分類）。點入詳細頁（FR-004）。 */
function AnnouncementRow({ item, onOpen }: { item: AnnouncementItem; onOpen: (docId: string) => void }) {
  return (
    <ListItemButton onClick={() => onOpen(item.doc_id)} divider>
      <ListItemText
        primary={
          <Box component="span" sx={{ display: "inline-flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
            <Typography component="span" sx={{ fontWeight: 600 }}>
              {item.doc_name}
            </Typography>
            <Chip
              size="small"
              color={item.kind === "NEW_VERSION" ? "primary" : "success"}
              label={`${KIND_LABELS[item.kind] ?? item.kind} ${item.version_no}`}
            />
          </Box>
        }
        secondary={
          <>
            <Typography variant="body2" color="text.secondary" component="span" sx={{ display: "block" }}>
              {item.change_summary || "（無摘要）"}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {item.published_date.slice(0, 10)} ｜ {item.author_name ?? "—"} ｜ {item.category_code}
            </Typography>
          </>
        }
      />
      <ChevronRightIcon color="disabled" />
    </ListItemButton>
  )
}

/**
 * 系統儀表板（US7 / DM00）：DM 模組落地頁——上方各類型文件總數（4 內建分類 + 總計，純資訊不可點），
 * 下方最新更新公告（近 30 天已發布，含新增 / 新版本），點入詳細頁、「查看全部文件」進文件庫。
 */
export function DmDashboardPage() {
  const navigate = useNavigate()
  const { data: stats, isPending: statsLoading, isError: statsError } = useDashboardStats()
  const { data: announcements, isPending: annLoading, isError: annError } = useAnnouncements()

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        系統儀表板
      </Typography>

      {/* 各類型文件總數 */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", mb: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            各類型文件總數
          </Typography>
          <Typography variant="caption" color="text.secondary">
            統計範圍：已發布之目前版本（不含送審中、草稿、已廢止）
          </Typography>
        </Box>
        {statsLoading ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 3 }}>
            <CircularProgress size={28} />
          </Box>
        ) : statsError ? (
          <Alert severity="error">載入失敗，請稍後再試。</Alert>
        ) : (
          <>
            <Box
              sx={{
                display: "grid",
                gap: 2,
                gridTemplateColumns: { xs: "repeat(2, 1fr)", md: "repeat(4, 1fr)" },
              }}
            >
              {(stats?.items ?? []).map((s) => (
                <StatCard key={s.category_code} name={s.category_name} count={s.count} />
              ))}
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ textAlign: "right", mt: 2 }}>
              總計 <strong>{stats?.total ?? 0}</strong> 份
            </Typography>
          </>
        )}
      </Paper>

      {/* 最新更新公告 */}
      <Paper sx={{ p: 2 }}>
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", mb: 1 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            最新更新公告{" "}
            <Typography component="span" variant="caption" color="text.secondary">
              （近一個月發布）
            </Typography>
          </Typography>
          <Link component="button" variant="body2" onClick={() => navigate("/dm/library")}>
            查看全部文件 →
          </Link>
        </Box>
        <Divider sx={{ mb: 1 }} />
        {annLoading ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 3 }}>
            <CircularProgress size={28} />
          </Box>
        ) : annError ? (
          <Alert severity="error">載入失敗，請稍後再試。</Alert>
        ) : (announcements ?? []).length === 0 ? (
          <Alert severity="info">近期無新發布文件</Alert>
        ) : (
          <List disablePadding>
            {(announcements ?? []).map((a) => (
              <AnnouncementRow key={`${a.doc_id}-${a.version_no}`} item={a} onOpen={(id) => navigate(`/dm/documents/${id}`)} />
            ))}
          </List>
        )}
      </Paper>
    </Box>
  )
}
