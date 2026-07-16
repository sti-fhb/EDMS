import List from "@mui/material/List"
import ListItemButton from "@mui/material/ListItemButton"
import ListItemText from "@mui/material/ListItemText"
import { NavLink } from "react-router-dom"

import { DP_NAV_ITEMS } from "../layouts/navItems"

/** DP 後台左側導覽；項目對齊 wireframe 六畫面。 */
export function Sidebar() {
  return (
    <List component="nav" aria-label="DP 後台導覽">
      {DP_NAV_ITEMS.map((item) => (
        <ListItemButton
          key={item.path}
          component={NavLink}
          to={item.path}
          sx={{ "&.active": { bgcolor: "action.selected", fontWeight: 700 } }}
        >
          <ListItemText primary={item.label} />
        </ListItemButton>
      ))}
    </List>
  )
}
