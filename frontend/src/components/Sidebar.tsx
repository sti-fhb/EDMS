import ArticleIcon from "@mui/icons-material/Article"
import ExpandMoreIcon from "@mui/icons-material/ExpandMore"
import FolderIcon from "@mui/icons-material/Folder"
import Box from "@mui/material/Box"
import ButtonBase from "@mui/material/ButtonBase"
import Collapse from "@mui/material/Collapse"
import List from "@mui/material/List"
import ListItemButton from "@mui/material/ListItemButton"
import ListItemText from "@mui/material/ListItemText"
import Typography from "@mui/material/Typography"
import { useState } from "react"
import { NavLink } from "react-router-dom"

import type { NavGroup } from "../layouts/navItems"
import { NAV_GROUPS } from "../layouts/navItems"

// 側欄配色：對齊 TBMS 母專案 layoutTokens 平時態（PEACE）。EDMS 暫不做作業模式三態，寫死此組。
const SIDEBAR = {
  headerColor: "#1b5e20",
  headerHoverBg: "#f1f8e9",
  itemColor: "#333",
  activeColor: "#1b5e20",
  activeBg: "#e8f5e9",
  activeBorder: "#2e7d32",
  hoverBg: "#e8f5e9",
  hoverColor: "#2e7d32",
}

/** 單一模組群組：可收合下拉（MUI Collapse + chevron 旋轉），子項縮排。對齊 TBMS 側欄。 */
function NavGroupSection({ group }: { group: NavGroup }) {
  // P1 僅「系統管理者後台」一組，預設展開（登入落在歡迎頁時側欄仍露出功能）；點標題可收合。
  const [expanded, setExpanded] = useState(true)
  return (
    <Box>
      <ButtonBase
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        sx={{
          width: "100%",
          px: 1.5,
          py: 1,
          justifyContent: "flex-start",
          color: SIDEBAR.headerColor,
          fontWeight: 700,
          fontSize: "0.82rem",
          "&:hover": { bgcolor: SIDEBAR.headerHoverBg },
        }}
      >
        <FolderIcon sx={{ fontSize: "1.1rem", width: 24, flexShrink: 0 }} />
        <Typography
          component="span"
          sx={{ ml: 1, flex: 1, textAlign: "left", fontSize: "inherit", fontWeight: "inherit", whiteSpace: "nowrap" }}
        >
          {group.title}
        </Typography>
        <ExpandMoreIcon
          sx={{
            fontSize: "0.85rem",
            transition: "transform 0.2s",
            transform: expanded ? "rotate(0deg)" : "rotate(-90deg)",
          }}
        />
      </ButtonBase>
      <Collapse in={expanded} timeout="auto" unmountOnExit>
        <List component="div" disablePadding>
          {group.items.map((item) => (
            <ListItemButton
              key={item.path}
              component={NavLink}
              to={item.path}
              sx={{
                pl: 5,
                pr: 1.5,
                py: 0.75,
                color: SIDEBAR.itemColor,
                borderLeft: "3px solid transparent",
                transition: "all 0.15s",
                "&:hover": { bgcolor: SIDEBAR.hoverBg, color: SIDEBAR.hoverColor },
                "&.active": {
                  bgcolor: SIDEBAR.activeBg,
                  color: SIDEBAR.activeColor,
                  fontWeight: 600,
                  borderLeft: `3px solid ${SIDEBAR.activeBorder}`,
                },
              }}
            >
              <ArticleIcon sx={{ width: 20, mr: 1, fontSize: "0.95rem", flexShrink: 0 }} />
              <ListItemText primary={item.label} primaryTypographyProps={{ fontSize: "0.85rem" }} />
            </ListItemButton>
          ))}
        </List>
      </Collapse>
    </Box>
  )
}

/**
 * 統一 shell 左側導覽（#89）：模組群組可收合下拉、功能項縮排，對齊 TBMS 母專案側欄。
 * P1 僅「系統管理者後台」群組（過渡期對所有登入者顯示，案 A）；ET / DM 群組於 P3 / P4 加入、
 * 屆時依權限決定是否顯示（無權限者完全看不到，最小知悉）。
 */
export function Sidebar() {
  return (
    <Box component="nav" aria-label="主導覽" sx={{ py: 0.5 }}>
      {NAV_GROUPS.map((group) => (
        <NavGroupSection key={group.title} group={group} />
      ))}
    </Box>
  )
}
