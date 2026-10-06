import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"

import { useAuth } from "../auth/useAuth"
import { DmOverviewWidget } from "../dm/dashboard/DmOverviewWidget"
import { EtOverviewWidget } from "../et/dashboard/EtOverviewWidget"
import { PROFILE_ME_QUERY_KEY, profileApi } from "../dp/user/profileService"
import { useModuleSummary } from "../layouts/useModuleSummary"

/**
 * 中性歡迎頁（#89 P1）：登入後主頁，不綁任何模組權限、永遠存在。
 *
 * 只顯示問候（帶姓名）＋各模組的概況 widget。姓名載入失敗時靜默保底（退回「歡迎」），
 * 不阻斷頁面。**具任一 DM 角色者於此依權限疊加「DM 文件概況」widget（US7 / #89）**，
 * 無 DM 角色者不顯示（最小知悉）。
 *
 * ## 2026-10-02 手測裁示：拿掉「系統定位」與版本號
 *
 * ⚠️ 系統定位文案（「教育訓練與文件管理系統」）原是 **#89 的決策 D3**，由 PO 於
 * 2026-07-28 定案。本次裁示移除，**屬刻意推翻**而非漏掉——日後若有人依 #89 的留言
 * 想把它加回來，請先確認那是新的決定。
 *
 * 📌 版本號**並未消失**，登入畫面仍然顯示（`LoginOverlay`）。移除的是歡迎頁這一處，
 * 故「請問你是哪個版本」這個支援問法不受影響；`/api/version` 的查詢也隨之移除，
 * 不留一支沒有讀取端的請求。
 */
export function WelcomePage() {
  const { isAuthenticated, mustChangePwd } = useAuth()
  // 本頁為 index 路由、未登入時亦已掛載（被 LoginOverlay 覆蓋）；enabled 僅在已登入且非強制變更
  // 密碼時才發查詢，避免無謂 401（比照 #41 的取捨）。
  const enabled = isAuthenticated && !mustChangePwd
  const { data: me } = useQuery({ queryKey: PROFILE_ME_QUERY_KEY, queryFn: profileApi.getMe, enabled })
  const { data: modules } = useModuleSummary()

  const greeting = me?.user_name ? `歡迎，${me.user_name}` : "歡迎"

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>
        {greeting}
      </Typography>
      {/* #453 / #89 的 P3：教育訓練概況。
          ⚠️ 這裡只把「有沒有 ET 角色」當成**要不要發查詢**的條件（無角色者端點回 403，
          先打再被擋等於每位純 DM 使用者的首頁固定吃一個 403）。**渲染與否由 widget
          內部依「有無資料」決定**——#89 明訂人人具 ET 學員預設角色，照角色顯示會讓
          主管看到一張空的「我的課程」。⛔ 不要在這裡加 `&& <EtOverviewWidget/>` 的
          角色判斷，那正是 #89 警告的寫法。*/}
      <EtOverviewWidget enabled={Boolean(enabled && modules?.et.has_role)} />
      {/* US7 / #89：具任一 DM 角色者才疊加「DM 文件概況」；無 DM 角色者不顯示（最小知悉）*/}
      {enabled && modules?.dm.has_role && <DmOverviewWidget />}
    </Box>
  )
}
