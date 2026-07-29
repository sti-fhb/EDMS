import List from "@mui/material/List"
import ListItemButton from "@mui/material/ListItemButton"
import ListItemText from "@mui/material/ListItemText"
import ListSubheader from "@mui/material/ListSubheader"
import { Fragment } from "react"
import { NavLink } from "react-router-dom"

import { NAV_GROUPS } from "../layouts/navItems"

/**
 * 統一 shell 左側導覽（#89）：依權限群組渲染，群組標題用 ListSubheader。
 * P1 僅「系統管理者後台」群組，過渡期對所有登入者顯示（案 A）；ET / DM 群組於 P3 / P4 加入、
 * 屆時依權限決定是否顯示（無權限者完全看不到，最小知悉）。
 */
export function Sidebar() {
  return (
    <List component="nav" aria-label="主導覽">
      {NAV_GROUPS.map((group) => (
        <Fragment key={group.title}>
          <ListSubheader disableSticky>{group.title}</ListSubheader>
          {group.items.map((item) => (
            <ListItemButton
              key={item.path}
              component={NavLink}
              to={item.path}
              sx={{ "&.active": { bgcolor: "action.selected", fontWeight: 700 } }}
            >
              <ListItemText primary={item.label} />
            </ListItemButton>
          ))}
        </Fragment>
      ))}
    </List>
  )
}
