"""稽核對象（target）顯示名稱解析（US10 / dp-audit，唯讀）。

`target_id` 為原始識別碼，使用者看原始 ID 無意義，故依 `func_name` 分派、**批次**查對應主檔解析為可讀名稱：

- 使用者類（DP-USERS / DP-PROFILE / DP-FORGOT / DP-REGISTER）→ DP_USER 姓名 →（無姓名）email；
  邀請（`invite_id` 非 DP_USER）→ DP_PENDING_REGISTRATION 姓名 → email
- DP-PARAMS（`param_id.param_key`）→ DP_PARAM_D.PARAM_NAME（中文，對齊 dp-params）
- DP-TEMPLATES（`module.template_code`）→ DP_NOTIFY_TEMPLATE.TEMPLATE_NAME（中文）
- 其餘 / 查無 → 原 `target_id`（呼叫端 fallback）

皆為唯讀 SELECT（跨 DP 子模組主檔），符合 sti-backend-boundaries 報表 / 查詢例外。
"""

from collections.abc import Iterable

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.notify.models import DpNotifyTemplate
from app.dp.params.models import DpParamDetail
from app.dp.user.models import DpPendingRegistration
from app.dp.users.models import DpUser

# target_id 指向使用者（USER_ID 或邀請 invite_id）之 func_name。
# DM-ROLES / ET-ROLES（角色與可見對象 / 受訓對象指派）target_id 即被指派之 USER_ID，
# 故一併解析為姓名（對象顯示人名而非原始 ID）。
#
# ⚠️ ET-ROLES 於 #716 補上——漏列的症狀是**畫面顯示原始 USER_ID**：seed 示範帳號的 ID
# 是可讀代碼，使用者會誤以為「姓名被翻成英文」，而正式帳號的隨機碼則完全無法辨識。
# 兩者 target_id 語意與 DM-ROLES 完全相同，當時只是漏收。
#
# ⛔ DM-CATALOG / ET-CATALOG 的 target_id 為受控項代碼（分類 / func / TAG_ID），非使用者，
# **不要**列入——它們的名稱改走稽核列自帶（見 query_service 的 _TARGET_NAME_KEYS），
# 那樣才留得住「操作當時的名稱」；查活表會讓標籤改名後連舊紀錄一起變。
_USER_FUNCS = frozenset({"DP-USERS", "DP-PROFILE", "DP-FORGOT", "DP-REGISTER", "DM-ROLES", "ET-ROLES"})

# ET 課程類：`target_id` 為課程 ID，或 `{course_id}:{user_id}`（再接 `:{quiz_id}`）之複合鍵。
# 本集合的解析**只負責人名那一段**（取現值）；課程名稱由稽核列自帶（取當時值），
# 兩段於 `query_service` 組合——見該檔 `_compose_et_target`。
#
# ⛔ 不要把課程名稱也改成在這裡查活表：課程改名後，舊稽核紀錄會跟著變成新名字，
# 那是竄改歷史（#717 裁示）。
ET_COURSE_FUNCS = frozenset(
    {"ET-COURSE", "ET-ENROLLMENT", "ET-EXPORT", "ET-REPORT", "ET-QUIZ-RESET", "ET-APPROVAL"}
)


def et_user_segment(target_id: str) -> str | None:
    """取 ET 複合鍵的使用者段；非複合鍵（純課程 ID 或 `ALL`）回 `None`。

    `12:u01` → `u01`、`12:u01:7` → `u01`、`12` → `None`。
    """
    parts = target_id.split(":")
    return parts[1] if len(parts) >= 2 and parts[1] else None

# (func_name, target_id) → 顯示名稱
_DisplayMap = dict[tuple[str, str], str]


async def resolve_target_displays(db: AsyncSession, pairs: Iterable[tuple[str, str | None]]) -> _DisplayMap:
    """批次解析對象顯示名稱。

    Args:
        pairs: (func_name, target_id) 序列；target_id 為 None 者略過。

    Returns:
        {(func_name, target_id): 顯示名稱}；查無者不放入（呼叫端 fallback 原 target_id）。
    """
    user_pairs: list[tuple[str, str]] = []
    param_pairs: list[tuple[str, str]] = []
    template_pairs: list[tuple[str, str]] = []
    # ET 複合鍵：(func_name, 原 target_id, 使用者段)——map 仍以原 target_id 為鍵，
    # 呼叫端才對得回去；值是**人名那一段**，不是完整顯示字串。
    et_triples: list[tuple[str, str, str]] = []
    for func_name, target_id in pairs:
        if not target_id:
            continue
        if func_name in _USER_FUNCS:
            user_pairs.append((func_name, target_id))
        elif func_name == "DP-PARAMS":
            param_pairs.append((func_name, target_id))
        elif func_name == "DP-TEMPLATES":
            template_pairs.append((func_name, target_id))
        elif func_name in ET_COURSE_FUNCS:
            seg = et_user_segment(target_id)
            if seg:
                et_triples.append((func_name, target_id, seg))

    result: _DisplayMap = {}
    result.update(await _resolve_users(db, user_pairs))
    result.update(await _resolve_params(db, param_pairs))
    result.update(await _resolve_templates(db, template_pairs))
    result.update(await _resolve_et_users(db, et_triples))
    return result


async def _resolve_et_users(db: AsyncSession, triples: list[tuple[str, str, str]]) -> _DisplayMap:
    """ET 複合鍵之使用者段 → 姓名（無姓名退 email）；查無者不放入。

    與 `_resolve_users` 的差別只在「查的 ID 不是整個 target_id，而是其中一段」。
    """
    if not triples:
        return {}
    ids = {seg for _, _, seg in triples}
    rows = (
        await db.execute(select(DpUser.user_id, DpUser.user_name, DpUser.email).where(DpUser.user_id.in_(ids)))
    ).all()
    name_by_id = {uid: (user_name or email) for uid, user_name, email in rows}
    return {(func_name, tid): name_by_id[seg] for func_name, tid, seg in triples if seg in name_by_id}


async def _resolve_users(db: AsyncSession, pairs: list[tuple[str, str]]) -> _DisplayMap:
    """使用者類：DP_USER 姓名→email；未命中者再查邀請 pending（invite_id）。"""
    if not pairs:
        return {}
    ids = {tid for _, tid in pairs}
    name_by_id: dict[str, str] = {}
    rows = (
        await db.execute(select(DpUser.user_id, DpUser.user_name, DpUser.email).where(DpUser.user_id.in_(ids)))
    ).all()
    for uid, user_name, email in rows:
        name_by_id[uid] = user_name or email

    unresolved = ids - set(name_by_id)
    if unresolved:
        prows = (
            await db.execute(
                select(
                    DpPendingRegistration.invite_id, DpPendingRegistration.user_name, DpPendingRegistration.email
                ).where(DpPendingRegistration.invite_id.in_(unresolved))
            )
        ).all()
        for invite_id, user_name, email in prows:
            if invite_id is not None:
                name_by_id[invite_id] = user_name or email

    return {(func_name, tid): name_by_id[tid] for func_name, tid in pairs if tid in name_by_id}


async def _resolve_params(db: AsyncSession, pairs: list[tuple[str, str]]) -> _DisplayMap:
    """DP-PARAMS：拆 param_id.param_key → PARAM_NAME（中文）。"""
    if not pairs:
        return {}
    split = {}  # (param_id, param_key) → 原 target_id
    for _, tid in pairs:
        param_id, sep, param_key = tid.partition(".")
        if sep:
            split[(param_id, param_key)] = tid
    if not split:
        return {}
    rows = (
        await db.execute(
            select(DpParamDetail.param_id, DpParamDetail.param_key, DpParamDetail.param_name).where(
                tuple_(DpParamDetail.param_id, DpParamDetail.param_key).in_(list(split.keys()))
            )
        )
    ).all()
    name_by_tid = {split[(pid, pkey)]: pname for pid, pkey, pname in rows if (pid, pkey) in split}
    return {(func_name, tid): name_by_tid[tid] for func_name, tid in pairs if tid in name_by_tid}


async def _resolve_templates(db: AsyncSession, pairs: list[tuple[str, str]]) -> _DisplayMap:
    """DP-TEMPLATES：拆 module.template_code → TEMPLATE_NAME（中文）。"""
    if not pairs:
        return {}
    split = {}  # (module, code) → 原 target_id
    for _, tid in pairs:
        module, sep, code = tid.partition(".")
        if sep:
            split[(module, code)] = tid
    if not split:
        return {}
    rows = (
        await db.execute(
            select(DpNotifyTemplate.module, DpNotifyTemplate.template_code, DpNotifyTemplate.template_name).where(
                tuple_(DpNotifyTemplate.module, DpNotifyTemplate.template_code).in_(list(split.keys()))
            )
        )
    ).all()
    name_by_tid = {split[(mod, code)]: tname for mod, code, tname in rows if (mod, code) in split}
    return {(func_name, tid): name_by_tid[tid] for func_name, tid in pairs if tid in name_by_tid}
