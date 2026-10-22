"""已發布課程的內容編輯不得直接寫活表（#631 PR 2）。

## 🥇 本檔是整個 PR 2 真正的守門

把編輯端導向暫存區是**逐支方法改**的——29 個寫入端點各有一個分支。抽象擋不住「漏改
一處」：漏掉的那一支會悄悄維持即時生效，而那正是 #631 要修的缺陷本身，且**沒有任何
畫面或錯誤訊息會透露它**。

唯一擋得住的是**逐端點列舉**：對一門已發布課程打每一個內容編輯端點，斷言活表的內容樹
一個位元都沒變。

⛔ **不要因為某支端點「看起來很單純」而把它從清單裡拿掉。** 清單的價值在於它是**全集**；
少一條就等於那條從此沒有人檢查。

## 🔴 「全集」這件事由機器驗，不靠人記得

本檔曾經在 docstring 裡宣稱清單是全集，而**實際上缺了全部建立類端點**
（2026-10-16 security review M-5）——`POST /courses/{id}/survey`、
`POST /quizzes/{id}/questions`…，而那正是最危險的那一群：新建的內容若直寫活表，
下一次「更新」會把它判定成「教師刪了它」而軟刪掉，**連帶學員的進度**。

宣稱完備而不完備，比不宣稱更糟——讀者會以為有人檢查過。所以改成
`test_清單涵蓋全部內容寫入端點` 以 OpenAPI 自動列舉 `/api/et` 下的寫入端點再比對本清單：
**日後新增端點而忘了加進來，它會當場紅**。

⚠️ 真的不適用的端點列在 `_NOT_CONTENT_WRITES` 並**各自附理由**——⛔ 不可以只是把名字
加進去讓測試變綠，那等於把自動守門變回人工清單。
"""

import hashlib
from datetime import timedelta
from typing import Any, Final

import pytest
from sqlalchemy import select, update

from app.core.auth import create_access_token
from app.core.operator import OperatorInfo
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dp.users.models import DpUser
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.constants import (
    COURSE_CLOSED,
    ITEM_MATERIAL,
    ITEM_QUIZ,
    QUESTION_SINGLE,
    ROLE_TEACHER,
    SURVEY_QUESTION_SINGLE,
)
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.course.stage_live_tree import load_live_tree
from app.et.course.stage_repository import EtCourseStageRepository
from app.et.course.stage_rules import ENTITY_SURVEY, ENTITY_SURVEY_QUESTION
from app.et.course.stage_writer import EtCourseStageWriter
from app.et.material.models import EtMaterial
from app.et.quiz.models import EtQuestion, EtQuiz
from app.et.roles.models import EtUserRole
from app.et.survey.models import EtSurvey, EtSurveyQuestion
from tests.integration.et._tag_pairs import all_units_id

pytestmark = pytest.mark.integration

_COURSES = "/api/et/courses"


#: 內建問卷模板的代碼（`app/et/survey/templates.py`）。
_TEMPLATE_CODE: Final = "DEFAULT"


def _operator(user_id: str) -> OperatorInfo:
    return OperatorInfo(user_id=user_id)


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


def _tag(label: str) -> str:
    """由端點 label 推出一段**跨執行穩定**的識別碼後綴。

    ⛔ 不可用內建 `hash()`：它受 `PYTHONHASHSEED` 隨機化，同一條參數化測試每次執行
    拿到不同的 `DpUser.user_id`。那不會讓測試變紅，但會在測試 DB 裡堆出一堆孤兒使用者；
    更糟的是取模之後**不同 label 可能撞號**，兩條參數化同時命中就變成主鍵衝突的偶發紅
    ——而偶發紅會被當成假紅略過（2026-10-18 security review L-5 點名）。
    """
    # sha256 而非 md5：這裡只要「穩定且不撞號」，但 ruff 的 S324 會對 md5 報警，
    # 而為了測試資料去抑制一條安全規則不值得——兩者在這個用途上沒有差別。
    return hashlib.sha256(label.encode()).hexdigest()[:6]


async def _user(db, user_id: str) -> str:
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name=f"測試{user_id}",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            must_change_pwd=False,
            created_user="admin01",
            created_date=now,
        )
    )
    db.add(
        EtUserRole(
            user_id=user_id, role=ROLE_TEACHER, is_active=True, created_user="SYSTEM", created_date=now, deleted=0
        )
    )
    await db.flush()
    return user_id


async def _attach_tag(db, course_id: int, suffix: str = "") -> tuple[int, int]:
    """掛一組受訓對象配對，回傳 `(unit_tag_id, tag_id)`。

    ⚠️ 回傳是 #720 之後才需要的：`PUT /courses/{id}` 是**全量覆寫**，守門要打它就得把
    既有配對原樣送回去——少送一組，`ensure_tag_change_allowed` 會先以「已發布不可移除
    受訓對象」擋下，測試就倒在前置而不是倒在它要驗的事情上。
    """
    now = utcnow()
    tag = EtTag(
        #: `suffix` 讓同一門課掛得了第二組——`UQ_ET_TAG_NAME` 是全域唯一。
        tag_name=f"標籤{course_id}{suffix}",
        is_active=True,
        is_builtin=False,
        created_user="SYSTEM",
        created_date=now,
        deleted=0,
    )
    db.add(tag)
    await db.flush()
    unit_tag_id = await all_units_id(db)
    db.add(
        EtCourseTag(
            unit_tag_id=unit_tag_id,
            course_id=course_id,
            tag_id=tag.tag_id,
            created_user="SYSTEM",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()
    return unit_tag_id, tag.tag_id


async def _course_with_content(client, db, uid: str) -> dict[str, Any]:
    """建一門**內容齊全**的課程，回傳各層 id。

    齊全是刻意的：清單裡每一支端點都要有可打的對象，少建一種就會讓對應的那條
    測試因為「沒有東西可打」而假性通過。
    """
    now = utcnow().replace(microsecond=0)
    open_start_at = (now - timedelta(days=1)).isoformat()
    open_end_at = (now + timedelta(days=30)).isoformat()
    created = await client.post(
        _COURSES,
        json={
            "course_name": "守門測試課程",
            "open_start_at": open_start_at,
            "open_end_at": open_end_at,
        },
        headers=_bearer(uid),
    )
    assert created.status_code == 201, created.text
    cid = created.json()["course_id"]
    unit_tag_id, tag_id = await _attach_tag(db, cid)

    ch = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第一章"}, headers=_bearer(uid))
    chapter_id = ch.json()["chapter_id"]
    ch2 = await client.post(f"{_COURSES}/{cid}/chapters", json={"chapter_name": "第二章"}, headers=_bearer(uid))
    chapter2_id = ch2.json()["chapter_id"]
    # 第二章也要有內容，否則課程會被 BLOCK_CHAPTER_EMPTY 擋住發布，
    # 整份守門測試會倒在前置而不是倒在它要驗的事情上。
    ch2_item = await client.post(
        f"/api/et/chapters/{chapter2_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "第二章教材"},
        headers=_bearer(uid),
    )
    assert ch2_item.status_code == 201, ch2_item.text

    mat = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "教材甲"},
        headers=_bearer(uid),
    )
    assert mat.status_code == 201, mat.text
    quiz = await client.post(
        f"/api/et/chapters/{chapter_id}/items",
        json={"item_type": ITEM_QUIZ, "title": "小考"},
        headers=_bearer(uid),
    )
    assert quiz.status_code == 201, quiz.text
    quiz_id = quiz.json()["quiz_id"]
    q = await client.post(
        f"/api/et/quizzes/{quiz_id}/questions",
        json={
            "question_type": QUESTION_SINGLE,
            "stem": "題幹",
            "points": 100,
            "options": [{"option_text": "A", "is_correct": True}, {"option_text": "B", "is_correct": False}],
        },
        headers=_bearer(uid),
    )
    assert q.status_code == 201, q.text

    survey = await client.post(f"{_COURSES}/{cid}/survey", json={"survey_name": "課後問卷"}, headers=_bearer(uid))
    assert survey.status_code in (200, 201), survey.text
    survey_id = survey.json()["survey_id"]
    sq = await client.post(
        f"/api/et/surveys/{survey_id}/questions",
        json={
            "question_type": SURVEY_QUESTION_SINGLE,
            "stem": "滿意度",
            # ET_SURVEY_004：單選題至少 2 個選項
            "options": [{"option_text": "好"}, {"option_text": "普通"}],
        },
        headers=_bearer(uid),
    )
    assert sq.status_code == 201, sq.text
    await db.flush()

    item_rows = list(await db.scalars(select(EtItem).where(EtItem.chapter_id == chapter_id, EtItem.deleted == 0)))
    material_item = next(i for i in item_rows if i.material_id)
    material_row = await db.scalar(select(EtMaterial).where(EtMaterial.material_id == material_item.material_id))
    quiz_item = next(i for i in item_rows if i.quiz_id)
    question = await db.scalar(select(EtQuestion).where(EtQuestion.quiz_id == quiz_id, EtQuestion.deleted == 0))
    sq_row = await db.scalar(
        select(EtSurveyQuestion).where(EtSurveyQuestion.survey_id == survey_id, EtSurveyQuestion.deleted == 0)
    )
    chapter = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == chapter_id))
    quiz_row = await db.scalar(select(EtQuiz).where(EtQuiz.quiz_id == quiz_id))
    survey_row = await db.scalar(select(EtSurvey).where(EtSurvey.survey_id == survey_id))
    return {
        "course_id": cid,
        "unit_tag_id": unit_tag_id,
        "tag_id": tag_id,
        # ⚠️ 原樣留著供 `PUT /courses/{id}` 回送：全量覆寫少送訖止就會踩到 #301 的
        # `ensure_schedule_not_cleared`，測試又會倒在前置。
        "open_start_at": open_start_at,
        "open_end_at": open_end_at,
        "chapter_id": chapter_id,
        "chapter2_id": chapter2_id,
        "chapter_version": chapter.version,
        "material_item_id": material_item.item_id,
        "material_id": material_item.material_id,
        # ⚠️ 取實際版本而非寫死 0：哪天建立流程多 bump 一次，寫死的那個會變成 409，
        # 而 409 一樣讓 xfail 通過 ⇒ `strict=True` 的提醒不會響（security review L-6）
        "material_version": material_row.version,
        "quiz_item_id": quiz_item.item_id,
        "quiz_id": quiz_id,
        "quiz_version": quiz_row.version,
        "question_id": question.question_id,
        "question_version": question.version,
        "survey_id": survey_id,
        "survey_version": survey_row.version,
        "sq_id": sq_row.sq_id,
        "sq_version": sq_row.version,
    }


async def _publish(client, db, uid: str, cid: int) -> None:
    r = await client.post(f"{_COURSES}/{cid}/publish", headers=_bearer(uid))
    assert r.status_code == 200, r.text
    await db.flush()


async def _refresh_versions(db, ids: dict) -> None:
    """呼叫前重讀各實體的 `VERSION`。

    ⚠️ **發布會遞增課程的 `VERSION`**，所以前置時抓的值到了「已發布」那半就過期，
    帶著它打重排端點會吃 409 `ET_LOCK_001`——那是測試自己的前置錯誤，不是守門發現
    了什麼。兩個方向的測試共用本函式，才不會只在其中一邊對。
    """
    course = await db.scalar(select(EtCourse).where(EtCourse.course_id == ids["course_id"]))
    chapter = await db.scalar(select(EtChapter).where(EtChapter.chapter_id == ids["chapter_id"]))
    ids["course_version"] = course.version
    ids["chapter_version"] = chapter.version


async def _fingerprint(db, course_id: int) -> tuple:
    """活表內容樹的指紋——**每一列的每一個內容欄位**都算進去。

    只比「有幾列」會讓「改了標題」這種就地更新完全看不出來。
    """
    return tuple(
        (
            n.entity_type,
            n.key[1],
            n.sort_order,
            tuple(
                sorted(
                    (c.key, getattr(n.row, c.key))
                    for c in n.row.__mapper__.column_attrs
                    if c.key not in {"created_date", "updated_date", "created_user", "updated_user"}
                )
            ),
        )
        for n in await load_live_tree(db, course_id)
    )


# ── 內容編輯端點全集 ──────────────────────────────────────────────────────────
#
# 每一項是 `(標籤, 是否已導向暫存區, 呼叫函式)`。
# ⛔ 新增內容編輯端點時**必須**補進這張表，否則它從此沒有人檢查。

_COURSE_MODULE = [
    (
        # #720：基本資料與受訓對象改走暫存。全量覆寫，故既有配對要原樣送回。
        "PUT /courses/{id}",
        True,
        lambda c, u, i: c.put(
            f"{_COURSES}/{i['course_id']}",
            json={
                "course_name": "改過的課名",
                "description": "改過的描述",
                "open_start_at": i["open_start_at"],
                "open_end_at": i["open_end_at"],
                "require_approval": True,
                "audiences": [{"unit_tag_id": i["unit_tag_id"], "tag_id": i["tag_id"]}],
                "version": i["course_version"],
            },
            headers=_bearer(u),
        ),
    ),
    (
        "POST /courses/{id}/chapters",
        True,
        lambda c, u, i: c.post(
            f"{_COURSES}/{i['course_id']}/chapters", json={"chapter_name": "新章"}, headers=_bearer(u)
        ),
    ),
    (
        "PUT /courses/{id}/chapters/order",
        True,
        lambda c, u, i: c.put(
            f"{_COURSES}/{i['course_id']}/chapters/order",
            json={"chapter_ids": [i["chapter2_id"], i["chapter_id"]], "version": i["course_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /chapters/{id}",
        True,
        lambda c, u, i: c.put(
            f"/api/et/chapters/{i['chapter_id']}",
            json={"chapter_name": "改名", "version": i["chapter_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "DELETE /chapters/{id}",
        True,
        lambda c, u, i: c.delete(f"/api/et/chapters/{i['chapter2_id']}", headers=_bearer(u)),
    ),
    (
        "POST /chapters/{id}/items",
        True,
        lambda c, u, i: c.post(
            f"/api/et/chapters/{i['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": "新教材"},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /chapters/{id}/items/order",
        True,
        lambda c, u, i: c.put(
            f"/api/et/chapters/{i['chapter_id']}/items/order",
            # ⚠️ 項目重排的併發令牌是**章節**的 version，不是課程的
            json={"item_ids": [i["quiz_item_id"], i["material_item_id"]], "version": i["chapter_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "DELETE /items/{id}",
        True,
        lambda c, u, i: c.delete(f"/api/et/items/{i['material_item_id']}", headers=_bearer(u)),
    ),
]

_OTHER_MODULES = [
    (
        "PUT /materials/{id}",
        True,
        lambda c, u, i: c.put(
            f"/api/et/materials/{i['material_id']}",
            # ⚠️ **必須給說明文字**：fixture 的教材是空殼（無影片無文件），送 `None` 會先被
            # `ET_MATERIAL_002`「至少提供一項媒材」擋成 422，本條就測不到它宣稱的事。
            # 🔴 2026-10-17 發現這條一直是為了這個理由 xfail，不是為了「寫了活表」——
            # 一個**為了錯的理由而通過**的 xfail，`strict=True` 想要的提醒永遠不會響
            # （security review L-6 指出的形狀，實際成因比它推測的還早一步）。
            json={"material_name": "改名教材", "description_html": "<p>說明</p>", "version": i["material_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /quizzes/{id}",
        True,
        lambda c, u, i: c.put(
            f"/api/et/quizzes/{i['quiz_id']}",
            json={"quiz_name": "改名測驗", "pass_score": 80, "max_retry": 3, "version": i["quiz_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /questions/{id}",
        True,
        lambda c, u, i: c.put(
            f"/api/et/questions/{i['question_id']}",
            json={
                "question_type": QUESTION_SINGLE,
                "stem": "改過的題幹",
                "points": 100,
                "options": [{"option_text": "A", "is_correct": True}, {"option_text": "B", "is_correct": False}],
                "version": i["question_version"],
            },
            headers=_bearer(u),
        ),
    ),
    (
        "DELETE /questions/{id}",
        True,
        lambda c, u, i: c.delete(f"/api/et/questions/{i['question_id']}", headers=_bearer(u)),
    ),
    (
        "PUT /surveys/{id}",
        True,
        lambda c, u, i: c.put(
            f"/api/et/surveys/{i['survey_id']}",
            json={"survey_name": "改名問卷", "is_active": True, "version": i["survey_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /survey-questions/{id}",
        True,
        lambda c, u, i: c.put(
            f"/api/et/survey-questions/{i['sq_id']}",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": "改過的問卷題",
                "options": [{"option_text": "好"}, {"option_text": "普通"}],
                "version": i["sq_version"],
            },
            headers=_bearer(u),
        ),
    ),
    (
        "DELETE /survey-questions/{id}",
        True,
        lambda c, u, i: c.delete(f"/api/et/survey-questions/{i['sq_id']}", headers=_bearer(u)),
    ),
]

#: 🔴 **建立類端點**——2026-10-16 security review M-5 指出清單原本整群漏掉它們。
#:
#: 這一群最危險：新建的內容若直寫活表，而暫存樹是更早 seed 的，下一次「更新」會把它
#: 判定成「活表有、暫存沒有 ⇒ 教師刪了它」而軟刪掉，**連帶學員的進度與作答**。
#: 回應是 200「已更新」，稽核寫「刪除 N 筆」，而教師沒刪過任何東西。
_CREATE_WRITES = [
    (
        "POST /quizzes/{id}/questions",
        True,
        lambda c, u, i: c.post(
            f"/api/et/quizzes/{i['quiz_id']}/questions",
            json={
                "question_type": QUESTION_SINGLE,
                "stem": "新題",
                "points": 50,
                "options": [{"option_text": "A", "is_correct": True}, {"option_text": "B", "is_correct": False}],
            },
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /quizzes/{id}/questions/order",
        True,
        lambda c, u, i: c.put(
            f"/api/et/quizzes/{i['quiz_id']}/questions/order",
            json={"question_ids": [i["question_id"]], "version": i["quiz_version"]},
            headers=_bearer(u),
        ),
    ),
    (
        "POST /surveys/{id}/questions",
        True,
        lambda c, u, i: c.post(
            f"/api/et/surveys/{i['survey_id']}/questions",
            json={
                "question_type": SURVEY_QUESTION_SINGLE,
                "stem": "新問卷題",
                "options": [{"option_text": "好"}, {"option_text": "普通"}],
            },
            headers=_bearer(u),
        ),
    ),
    (
        "PUT /surveys/{id}/questions/order",
        True,
        lambda c, u, i: c.put(
            f"/api/et/surveys/{i['survey_id']}/questions/order",
            json={"question_ids": [i["sq_id"]], "version": i["survey_version"]},
            headers=_bearer(u),
        ),
    ),
]

_ALL = _COURSE_MODULE + _OTHER_MODULES + _CREATE_WRITES


#: `/api/et` 底下**不是**課程內容寫入的端點。每一條都要附理由。
#:
#: ⛔ **不可以只為了讓 `test_清單涵蓋全部內容寫入端點` 變綠而把名字加進來。** 那等於把
#: 機器守門退回人工清單，而本檔曾經就是這樣整群漏掉建立類端點的（security review M-5）。
#: 加之前問：「已發布課程的教師打這支，學員看到的內容會不會變？」會變就該進清單。
_NOT_CONTENT_WRITES: Final[dict[str, str]] = {
    # 課程本體與狀態：狀態轉換有自己的流程
    #
    # ⚠️ `PUT /api/et/courses/{course_id}`（基本資料）**曾經列在這裡**，理由是「刻意不走
    # 暫存」。#720 推翻了那條分界：教師在同一個畫面改名稱、改期間、改受訓對象，按「儲存」
    # 卻當場就讓學員看到——那正是 2026-10-19 手測回報的第一個 bug。它現在在守門清單裡。
    "POST /api/et/courses": "建立草稿課程——草稿不走暫存",
    "DELETE /api/et/courses/{course_id}": "刪除草稿課程，僅草稿可用",
    "POST /api/et/courses/{course_id}/publish": "發布本身就是生效入口",
    "POST /api/et/courses/{course_id}/close": "狀態轉換，不動內容",
    # ⚠️ 曾經寫著「狀態轉換，不動內容」——**#720 之後那句話是假的**：再開課會連同暫存的
    # 內容編輯一起套用（檢核 → 套用 → 轉 PUBLISHED），所以它和 `content/apply` 同類，
    # 是**生效入口**而不是「不動內容」。分類沒變，理由換了。
    "POST /api/et/courses/{course_id}/reopen": "「更新並重開課」——**這支就是生效入口**（#720）",
    "POST /api/et/courses/{course_id}/content/apply": "**這支就是生效入口**",
    "DELETE /api/et/courses/{course_id}/content/stage": "放棄暫存——只刪暫存列，活表不動",
    # #720：兩支都只動暫存列的**去留**，連暫存的內容都不改。
    "POST /api/et/courses/{course_id}/content/keep": "「保留編輯」只標記暫存樹要留著，活表不動",
    "DELETE /api/et/courses/{course_id}/content/stage/unkept": "丟棄未保留的殘留——只刪暫存列，活表不動",
    # ⚠️ 它**會**動暫存列（把問卷子樹從活表重抄一份），但不動活表——學員看到的內容
    # 在前後完全相同，這正是「放棄」的定義。與上一條同類（#712）。
    "DELETE /api/et/courses/{course_id}/content/stage/survey": "只放棄問卷的編輯——重抄活表，活表不動",
    "DELETE /api/et/surveys/{survey_id}": "刪問卷**僅草稿課程**可用（#238），已發布只能停用",
    # 學員端與教師的非內容操作
    #
    # ⚠️ 這張表的路徑**一律從 OpenAPI 抄**，不要憑印象寫。2026-10-17 第一版我寫了
    # `/enroll`、`/invite`、`/students/{user_id}/quizzes/{quiz_id}/reset` 等 10 支不存在
    # 的路徑——幸好 `test_清單涵蓋全部內容寫入端點` 當場紅了，否則那 10 支真正的端點
    # 會一直待在「沒有人解釋過」的狀態而沒人發現。
    "POST /api/et/enrollments": "學員加入課程",
    "POST /api/et/enrollments/preview": "加入前的預覽，唯讀",
    "POST /api/et/courses/{course_id}/invitations": "寄邀請信，不動內容",
    "POST /api/et/courses/{course_id}/invitations/preview": "邀請信預覽，唯讀",
    "POST /api/et/courses/{course_id}/survey/response": "學員填答",
    "POST /api/et/items/{item_id}/viewed": "學員學習進度",
    "POST /api/et/videos/{video_id}/intervals": "學員觀看區段",
    "POST /api/et/videos/{video_id}/ticket": "發播放票，不動內容",
    "POST /api/et/videos/{video_id}/normalize": "影片正規化，不改教材內容樹",
    "POST /api/et/quizzes/{quiz_id}/attempts": "學員開始作答",
    "PUT /api/et/attempts/{attempt_id}/answers/{question_id}": "學員暫存答案",
    "POST /api/et/attempts/{attempt_id}/submit": "學員交卷",
    "POST /api/et/courses/{course_id}/students/{user_id}/quizzes/{quiz_id}/retry-reset": ("教師重置學員次數，不動內容"),
    "DELETE /api/et/courses/{course_id}/students/{user_id}": "移除學員，不動內容",
    "POST /api/et/courses/{course_id}/approvals": "線下核可",
    "POST /api/et/courses/{course_id}/approvals/{user_id}/revoke": "撤回線下核可",
    "POST /api/et/approvals/search": "核可查詢（POST 只因為條件放 body），唯讀",
    # 檔案上傳：multipart，無法以本檔的 JSON 參數化方式打。
    # ⚠️ 它**是**內容寫入，暫存路徑由 `test_et_material.py` 的上傳測試覆蓋。
    "POST /api/et/materials/{material_id}/videos": "multipart 上傳，另由 test_et_material.py 覆蓋",
}


@pytest.mark.parametrize(
    ("label", "call"),
    [pytest.param(label, call, id=label) for label, _staged, call in _ALL],
)
async def test_他人不得碰到我的課程內容(label: str, call, client, db) -> None:
    """🔴 **授權的列舉式守門（活表 id 這一半）**（2026-10-18 security review M-4）。

    以教師乙的 token 打教師甲的課程，用的是**活表 id**，走各模組既有的 `_require_owned`。

    ⚠️ 它**不會**踏進 `_staged_*` 的負數分支——那一半由下一條測試守，兩條缺一不可。
    （本條原本宣稱涵蓋負數分支，變異檢查當場推翻：把 `_staged_quiz` 的 `ensure_owner`
    拿掉，18 條全綠。）

    ## ⛔ 不要在這裡加「甲的暫存區一列都沒變」

    看起來該加，實際上**恆真**：`client` fixture 的 `get_db` override 對丟出例外的請求
    呼叫 `db.rollback()`，而測試 session 走 savepoint 隔離，所以請求期間的任何寫入
    都會隨著 403／404 一起被回滾。那條斷言無論實作怎麼寫都會過，屬於
    「對錯誤回應做否定斷言」這一類的假證據。

    ⭐ **正向錨點是 `test_已發布課程的內容編輯不得直接寫活表`**：同一份 `_ALL`、同一個
    `call`，換成擁有者的 token 必須 `< 400`。少了它，把端點改成「一律 404」也會讓本條
    全綠。兩條合起來才是「擁有者做得到、他人做不到」。
    """
    tag = _tag(label)
    owner = await _user(db, f"ZT_O{tag}")
    other = await _user(db, f"ZT_X{tag}")
    ids = await _course_with_content(client, db, owner)
    await _publish(client, db, owner, ids["course_id"])
    # 版本號要是對的，否則可能先吃 409 `ET_LOCK_001`——那就不是授權擋下的了。
    await _refresh_versions(db, ids)

    r = await call(client, other, ids)

    assert r.status_code in (403, 404), f"{label} 應以 403/404 擋下他人，實際 {r.status_code}：{r.text}"


async def _staged_negative_ids(client, db, uid: str, ids: dict[str, Any]) -> dict[str, Any]:
    """在一門**已發布**課程的暫存區裡，由擁有者建出一整棵新內容樹，回傳全負數的 id。

    🔴 負數 id 只有「本次編輯新增、活表還沒有」的節點才會有——seed 進來的節點對外
    回的是 `SOURCE_ID`（正數）。所以要測到 `resolve_new` 之後那三行授權，只能**真的
    建一棵新的**，不能靠 seed。

    ⚠️ `course_id` 不在其中：課程列永遠在活表，沒有暫存版本。
    """
    cid = ids["course_id"]
    h = _bearer(uid)

    async def _post(url: str, payload: dict) -> dict:
        r = await client.post(url, json=payload, headers=h)
        assert r.status_code in (200, 201), f"前置失敗 {url}：{r.text}"
        return r.json()

    ch = await _post(f"{_COURSES}/{cid}/chapters", {"chapter_name": "暫存章甲"})
    ch2 = await _post(f"{_COURSES}/{cid}/chapters", {"chapter_name": "暫存章乙"})
    mat = await _post(f"/api/et/chapters/{ch['chapter_id']}/items", {"item_type": ITEM_MATERIAL, "title": "暫存教材"})
    quiz = await _post(f"/api/et/chapters/{ch['chapter_id']}/items", {"item_type": ITEM_QUIZ, "title": "暫存測驗"})
    question = await _post(
        f"/api/et/quizzes/{quiz['quiz_id']}/questions",
        {
            "question_type": QUESTION_SINGLE,
            "stem": "暫存題",
            "points": 100,
            "options": [{"option_text": "A", "is_correct": True}, {"option_text": "B", "is_correct": False}],
        },
    )
    # 活表已有一份問卷 ⇒ 先把它從暫存樹移走，建立這支才能成功、才拿得到負數問卷 id。
    repo = EtCourseStageRepository()
    node = next(n for n in await repo.load_tree(db, cid) if n.entity_type == ENTITY_SURVEY)
    await EtCourseStageWriter(repo).delete_subtree(db, node.stage_id, _operator(uid))
    survey = await _post(f"{_COURSES}/{cid}/survey", {"survey_name": "暫存問卷"})
    sq = await _post(
        f"/api/et/surveys/{survey['survey_id']}/questions",
        {
            "question_type": SURVEY_QUESTION_SINGLE,
            "stem": "暫存問卷題",
            "options": [{"option_text": "好"}, {"option_text": "普通"}],
        },
    )

    negative = {
        "course_id": cid,  # 課程永遠是活表列
        "course_version": ids["course_version"],
        "chapter_id": ch["chapter_id"],
        "chapter2_id": ch2["chapter_id"],
        "chapter_version": ch.get("version", 0),
        "material_item_id": mat["item_id"],
        "material_id": mat["material_id"],
        "material_version": mat.get("material_version", 0),
        "quiz_item_id": quiz["item_id"],
        "quiz_id": quiz["quiz_id"],
        "quiz_version": quiz.get("quiz_version", 0),
        "question_id": question["question_id"],
        "question_version": question.get("version", 0),
        "survey_id": survey["survey_id"],
        "survey_version": survey.get("version", 0),
        "sq_id": sq["sq_id"],
        "sq_version": sq.get("version", 0),
    }
    wrong = {k: v for k, v in negative.items() if k.endswith("_id") and k != "course_id" and v >= 0}
    assert not wrong, f"前置失敗：這些 id 不是負數，本測試就不會走到負數分支 {wrong}"
    return negative


#: 沒有負數 id 可打的端點——它們的對象是**課程列本身**，而課程永遠在活表
#: （理由見 `_staged_negative_ids` 的 docstring）。
#:
#: ⚠️ 列在這裡**不等於沒有授權守門**：`PUT /courses/{id}` 的他人守門走 `_require_owned`，
#: 由 `test_他人不得碰到我的課程內容`（403/404 那一版）覆蓋。⛔ 不要為了讓某支變綠而
#: 加進來——先問「這支吃得到負數 id 嗎？」吃得到就該留在參數化裡。
_NO_NEGATIVE_ID: Final[frozenset[str]] = frozenset({"PUT /courses/{id}"})


@pytest.mark.parametrize(
    ("label", "call"),
    [pytest.param(label, call, id=label) for label, _staged, call in _ALL if label not in _NO_NEGATIVE_ID],
)
async def test_他人不得以負數_id_碰到我的暫存區(label: str, call, client, db) -> None:
    """🔴 **授權的列舉式守門（負數 id 這一半）**（2026-10-18 security review M-4）。

    七支 `_staged_*` 解析器的負數分支各自手寫了「`resolve_new` → 取課程 →
    `ensure_owner` → 取鎖」。今天七份都對，但那是**七份手寫的三行**，而既有的列舉只驗
    「這支有沒有改走暫存」。新增第 19 支端點時漏掉 `ensure_owner`，CI 會全綠。

    ⭐ 這條是變異檢查逼出來的：原本只有活表 id 那一版，把 `_staged_quiz` 的
    `ensure_owner` 拿掉之後 18 條**全綠**——因為活表 id 根本不走那條分支。

    ## 為何斷言「恰好 403」而不是 403/404

    負數 id 在甲的暫存區裡確實存在，`resolve_new` 一定撈得到，所以唯一正確的結局是
    `ensure_owner` 的 403 `ET_COURSE_002`。放寬成 403/404 會讓「版本不符先爆」「節點
    查不到」這些**與授權無關**的理由也算通過，而那正是假證據的形狀。
    """
    tag = _tag(f"neg:{label}")
    owner = await _user(db, f"ZT_N{tag}")
    other = await _user(db, f"ZT_M{tag}")
    ids = await _course_with_content(client, db, owner)
    await _publish(client, db, owner, ids["course_id"])
    await _refresh_versions(db, ids)
    staged = await _staged_negative_ids(client, db, owner, ids)

    r = await call(client, other, staged)

    assert r.status_code == 403, f"{label} 應以 403 擋下他人，實際 {r.status_code}：{r.text}"


async def test_刪暫存新建的問卷回的是不可刪而不是查無(client, db) -> None:
    """🔴 錯的不是行為、是教師據以下一步的資訊（2026-10-18 security review L-6）。

    已發布課程不可刪問卷（`ET_SURVEY_007`，只能停用）。教師在編輯中新建了一份問卷、
    再按刪除時，那份問卷只存在暫存區 ⇒ 查活表查不到 ⇒ 原本回 404「找不到問卷」。

    他看得到那份問卷就在畫面上，卻被告知找不到；真正的理由是「這門課只能停用」。
    """
    uid = await _user(db, "ZT_SD1")
    ids = await _course_with_content(client, db, uid)
    await _publish(client, db, uid, ids["course_id"])
    repo = EtCourseStageRepository()
    writer = EtCourseStageWriter(repo)
    await repo.seed_from_live(db, ids["course_id"], _operator(uid))
    node = next(n for n in await repo.load_tree(db, ids["course_id"]) if n.entity_type == ENTITY_SURVEY)
    await writer.delete_subtree(db, node.stage_id, _operator(uid))
    created = await client.post(
        f"{_COURSES}/{ids['course_id']}/survey", json={"survey_name": "新問卷"}, headers=_bearer(uid)
    )
    assert created.status_code == 201, created.text

    r = await client.delete(f"/api/et/surveys/{created.json()['survey_id']}", headers=_bearer(uid))

    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "ET_SURVEY_007"


class TestSurveyCreationPathsStaged:
    """`POST /courses/{id}/survey` 與 `POST /surveys/{id}/apply-template` 的守門。

    🔴 **這兩支刻意不放進上面的參數化清單。** 那個 fixture 的課程已經有問卷、問卷也
    已經有題目，所以兩支都會被業務規則擋成 409——而「什麼都沒做」當然不會動活表。
    那種 param 是**弱守門**：即使端點在真的能動手時直寫活表，它照樣綠。

    要驗得到，必須讓它**真的成功**，所以各自建自己的前置狀態。
    """

    async def test_建立問卷進暫存而非活表(self, client, db) -> None:
        uid = await _user(db, "ZT_SC1")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        # 活表已有一份問卷 ⇒ 先把它從**暫存樹**移走，讓建立這支真的能成功
        repo = EtCourseStageRepository()
        writer = EtCourseStageWriter(repo)
        await repo.seed_from_live(db, ids["course_id"], _operator(uid))
        node = next(n for n in await repo.load_tree(db, ids["course_id"]) if n.entity_type == ENTITY_SURVEY)
        await writer.delete_subtree(db, node.stage_id, _operator(uid))
        before = await _fingerprint(db, ids["course_id"])

        r = await client.post(
            f"{_COURSES}/{ids['course_id']}/survey", json={"survey_name": "新問卷"}, headers=_bearer(uid)
        )

        assert r.status_code == 201, r.text
        assert r.json()["survey_id"] < 0, "新建的問卷要回負數 id（暫存）"
        assert await _fingerprint(db, ids["course_id"]) == before, "活表不得被動到"

    async def test_套用模板進暫存而非活表(self, client, db) -> None:
        uid = await _user(db, "ZT_SC2")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        # 套模板要求問卷 0 題 ⇒ 先把既有題目從暫存樹移走
        repo = EtCourseStageRepository()
        writer = EtCourseStageWriter(repo)
        await repo.seed_from_live(db, ids["course_id"], _operator(uid))
        nodes = await repo.load_tree(db, ids["course_id"])
        survey = next(n for n in nodes if n.entity_type == ENTITY_SURVEY)
        for sq in [n for n in nodes if n.entity_type == ENTITY_SURVEY_QUESTION]:
            await writer.delete_subtree(db, sq.stage_id, _operator(uid))
        before = await _fingerprint(db, ids["course_id"])

        r = await client.post(
            f"/api/et/surveys/{ids['survey_id']}/apply-template",
            json={"template_code": _TEMPLATE_CODE, "version": survey.version},
            headers=_bearer(uid),
        )

        assert r.status_code == 200, r.text
        assert r.json()["questions"], "模板題目要出現在暫存版的回應裡"
        assert await _fingerprint(db, ids["course_id"]) == before, "活表不得被動到"


async def test_清單涵蓋全部內容寫入端點(client) -> None:
    """🔴 **讓「全集」這件事由機器驗**，不靠下一個人記得。

    本檔原本在 docstring 宣稱清單是全集，實際上**缺了全部建立類端點**
    （2026-10-16 security review M-5）。宣稱完備而不完備比不宣稱更糟——讀者會以為有人
    檢查過，而那一群正是最危險的：新建的內容直寫活表，下一次「更新」會把它當成「教師
    刪了它」而軟刪，連帶學員進度。

    本條以 OpenAPI 列舉 `/api/et` 下所有 POST / PUT / DELETE，扣掉 `_NOT_CONTENT_WRITES`
    之後，剩下的必須**全部**在守門清單裡。日後新增端點忘了導向暫存區，這裡會當場紅。

    ⚠️ 它驗的是「有沒有被列舉」，不是「行為對不對」——行為由
    `test_已發布課程的內容編輯不得直接寫活表` 逐條驗。兩者缺一不可。
    """
    spec = (await client.get("/openapi.json")).json()
    actual = {
        f"{method.upper()} {path}"
        for path, ops in spec["paths"].items()
        if path.startswith("/api/et")
        for method in ops
        if method.upper() in {"POST", "PUT", "DELETE"}
    }
    # 清單裡的 label 是縮寫（省略 /api/et 與參數名），轉成 OpenAPI 的寫法比對不可靠，
    # 故反過來：用「端點數」對帳，並列出沒被解釋的那幾支。
    unexplained = sorted(actual - set(_NOT_CONTENT_WRITES) - _listed_openapi_paths())
    assert not unexplained, (
        "下列 /api/et 寫入端點既不在守門清單、也不在 `_NOT_CONTENT_WRITES` 的例外表裡。\n"
        "⛔ 不要直接塞進例外表——先問「已發布課程的教師打這支，學員看到的內容會不會變？」\n"
        f"{unexplained}"
    )


def _listed_openapi_paths() -> set[str]:
    """守門清單的 label → OpenAPI 路徑寫法。

    ⚠️ 手寫對照是刻意的：label 用的是可讀的縮寫（`PUT /chapters/{id}`），而 OpenAPI 用
    的是實際參數名（`/api/et/chapters/{chapter_id}`）。自動推導要猜參數名，猜錯會讓
    守門靜默失效——而這張表若與清單不同步，`test_清單涵蓋全部內容寫入端點` 會紅。
    """
    return {
        "PUT /api/et/courses/{course_id}",
        "POST /api/et/courses/{course_id}/chapters",
        "PUT /api/et/courses/{course_id}/chapters/order",
        "PUT /api/et/chapters/{chapter_id}",
        "DELETE /api/et/chapters/{chapter_id}",
        "POST /api/et/chapters/{chapter_id}/items",
        "PUT /api/et/chapters/{chapter_id}/items/order",
        "DELETE /api/et/items/{item_id}",
        "PUT /api/et/materials/{material_id}",
        "PUT /api/et/quizzes/{quiz_id}",
        "POST /api/et/quizzes/{quiz_id}/questions",
        "PUT /api/et/quizzes/{quiz_id}/questions/order",
        "PUT /api/et/questions/{question_id}",
        "DELETE /api/et/questions/{question_id}",
        "POST /api/et/courses/{course_id}/survey",
        "PUT /api/et/surveys/{survey_id}",
        "POST /api/et/surveys/{survey_id}/apply-template",
        "POST /api/et/surveys/{survey_id}/questions",
        "PUT /api/et/surveys/{survey_id}/questions/order",
        "PUT /api/et/survey-questions/{sq_id}",
        "DELETE /api/et/survey-questions/{sq_id}",
    }


@pytest.mark.parametrize(
    ("label", "call"),
    [pytest.param(label, call, id=label) for label, _staged, call in _ALL],
)
async def test_已發布課程的內容編輯不得直接寫活表(label: str, call, client, db) -> None:
    """🥇 PR 2 的核心守門——逐端點列舉，缺一條就等於那條從此沒人檢查。"""
    uid = await _user(db, f"ZT_W{_tag(label)}")
    ids = await _course_with_content(client, db, uid)
    await _publish(client, db, uid, ids["course_id"])

    await _refresh_versions(db, ids)
    before = await _fingerprint(db, ids["course_id"])
    resp = await call(client, uid, ids)
    await db.flush()
    after = await _fingerprint(db, ids["course_id"])

    assert resp.status_code < 400, f"{label} 應成功（寫進暫存區），實際 {resp.status_code}：{resp.text}"
    assert after == before, f"{label} 直接改動了活表——已發布課程的編輯必須先進暫存區"


@pytest.mark.parametrize(
    ("label", "call"),
    [pytest.param(label, call, id=label) for label, _staged, call in _ALL if _staged],
)
async def test_草稿課程的內容編輯仍直接寫活表(label: str, call, client, db) -> None:
    """🥇 **正向錨點**——少了它，把那些端點改成「什麼都不做」也會讓上一條通過。

    草稿沒有學員、不需版本化，行為必須完全不變。

    ⚠️ **母體是 `_ALL` 而非 `_COURSE_MODULE`**（#804）：原本只涵蓋章節與項目 7 支，
    教材 / 測驗 / 問卷那 11 支只靠 `is_staged` 的實作成立、沒有正向測試釘住。而 ET05
    的「取消」確認視窗對教師明寫「章節、教材、測驗與課後問卷…會即時存入」——那句承諾
    的依據就是本條，母體少一類就等於那句話有一類沒人驗。
    """
    uid = await _user(db, f"ZT_D{_tag(label)}")
    ids = await _course_with_content(client, db, uid)

    await _refresh_versions(db, ids)
    before = await _fingerprint(db, ids["course_id"])
    resp = await call(client, uid, ids)
    await db.flush()
    after = await _fingerprint(db, ids["course_id"])

    assert resp.status_code < 400, f"{label} 於草稿應成功，實際 {resp.status_code}：{resp.text}"
    assert after != before, f"{label} 於草稿課程應**立即**改動活表"


async def test_暫存模式回傳的_id_可以接著用(client, db) -> None:
    """🔴 **回傳的 id 必須能被下一個請求當作對象。**

    這條補的是「活表沒變」那組守門看不到的另一面：`add_chapter` 的暫存分支曾經回傳
    **正數**的 `STAGE_ID`（寫那段時還沒定下正負號規則，之後沒回去改）。活表確實沒變、
    守門全綠，但前端拿那個 id 去打 `/chapters/{id}/items` 會 404——或更糟，撞上某個
    真實章節而改到別的東西。

    ⭐ 那個 bug 是**既有測試的前置**抓到的（53 條紅），不是我的守門抓到的。教訓：
    「不該發生什麼」與「該發生什麼」要各有一條，前者單獨存在時會漏掉整個正向路徑。
    """
    uid = await _user(db, "ZT_RT1")
    ids = await _course_with_content(client, db, uid)
    await _publish(client, db, uid, ids["course_id"])

    ch = await client.post(
        f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
    )
    assert ch.status_code == 201, ch.text
    new_chapter_id = ch.json()["chapter_id"]
    assert new_chapter_id < 0, "暫存新增的節點對外必須是負數 id"

    # 拿它當對象再打一次——這是前端實際會做的事
    item = await client.post(
        f"/api/et/chapters/{new_chapter_id}/items",
        json={"item_type": ITEM_MATERIAL, "title": "暫存新教材"},
        headers=_bearer(uid),
    )

    assert item.status_code == 201, f"回傳的 id 必須能接著用：{item.text}"
    assert item.json()["item_id"] < 0
    assert item.json()["material_id"] < 0


async def _stage_basic_edit(client, db, uid: str, ids: dict, **over) -> None:
    """打一次 `PUT /courses/{id}`（全量覆寫），預設原樣送回、只改呼叫端指定的欄位。

    ⚠️ 版本每次重讀詳細頁取得：暫存開始之後活表的 `VERSION` 就不再遞增，拿活表的值
    打第二次必然 409。
    """
    detail = (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))).json()
    body = {
        "course_name": "守門測試課程",
        "open_start_at": ids["open_start_at"],
        "open_end_at": ids["open_end_at"],
        "audiences": [{"unit_tag_id": ids["unit_tag_id"], "tag_id": ids["tag_id"]}],
        "version": detail["version"],
    } | over
    resp = await client.put(f"{_COURSES}/{ids['course_id']}", json=body, headers=_bearer(uid))
    assert resp.status_code == 204, resp.text
    await db.flush()


class TestKeptEditsFlagInDetail:
    """詳細頁要回報「這份暫存已被保留」（#763 ②）。

    🔴 前端靠它分流**離開提示的文案**。少了它那句話在已保留的分支是假的：
    `discard_unkept` 對已保留的樹是 no-op，而提示寫著「離開後…都會放棄」。
    """

    async def test_按過保留編輯之後為真(self, client, db) -> None:
        uid = await _user(db, "ZT_KE1")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await db.execute(update(EtCourse).where(EtCourse.course_id == ids["course_id"]).values(status=COURSE_CLOSED))
        await db.flush()
        await _stage_basic_edit(client, db, uid, ids, course_name="關閉後改的課名")
        assert (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))).json()[
            "has_kept_edits"
        ] is False, "還沒按過保留編輯"

        kept = await client.post(f"{_COURSES}/{ids['course_id']}/content/keep", headers=_bearer(uid))
        assert kept.status_code == 204, kept.text

        detail = (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))).json()
        assert detail["has_kept_edits"] is True

    async def test_沒有暫存區時為假(self, client, db) -> None:
        """正向錨點：少了它，把欄位寫死成 `True` 也會讓上一條通過。"""
        uid = await _user(db, "ZT_KE2")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])

        detail = (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))).json()

        assert detail["has_kept_edits"] is False

    async def test_他人看不到擁有者的保留狀態(self, client, db) -> None:
        """比照 `has_pending_changes`：暫存區的任何狀態都只對擁有者有意義。"""
        uid = await _user(db, "ZT_KE3")
        other = await _user(db, "ZT_KE4")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await db.execute(update(EtCourse).where(EtCourse.course_id == ids["course_id"]).values(status=COURSE_CLOSED))
        await db.flush()
        await _stage_basic_edit(client, db, uid, ids, course_name="關閉後改的課名")
        await client.post(f"{_COURSES}/{ids['course_id']}/content/keep", headers=_bearer(uid))

        detail = (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(other))).json()

        assert detail["has_kept_edits"] is False


class TestStagedRead:
    """編輯頁讀暫存、他人與學員讀已生效版本（#631 PR 2a）。

    🔴 沒有這一半，教師**看不到自己剛做的編輯**——寫進暫存區但畫面還是舊的，
    他會以為系統壞了而重複操作。
    """

    async def test_擁有者看到暫存版本(self, client, db) -> None:
        uid = await _user(db, "ZT_SR1")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        names = [c["chapter_name"] for c in detail.json()["chapters"]]
        assert "暫存新章" in names, "教師必須看得到自己剛做的編輯"

    async def test_他人看到的是已生效版本(self, client, db) -> None:
        """🔴 他人閱覽與學員端一律看已生效版本。

        給他們看還沒生效的內容，會讓「這門課有什麼」出現兩種答案。
        """
        uid = await _user(db, "ZT_SR2")
        other = await _user(db, "ZT_SR3")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(other))

        names = [c["chapter_name"] for c in detail.json()["chapters"]]
        assert "暫存新章" not in names, "他人不得看到尚未生效的內容"
        assert "第一章" in names

    async def test_擁有者看到暫存的基本資料(self, client, db) -> None:
        """🥇 **寫進暫存就必須讀得回來，否則教師會以為自己的編輯掉了。**

        2026-10-19 手測回報的是反向那一半（寫進活表、學員看得到）；把寫入端改掉而讀取端
        沒跟上的症狀是：教師改完名稱、重整頁面，看到的還是舊名稱——他會再改一次，
        而暫存區裡其實已經有了。
        """
        uid = await _user(db, "ZT_SB1")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await _stage_basic_edit(client, db, uid, ids, course_name="暫存的課名", require_approval=True)

        detail = (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))).json()

        assert detail["course_name"] == "暫存的課名"
        assert detail["require_approval"] is True

    async def test_他人看到的是活表的基本資料(self, client, db) -> None:
        """他人閱覽與學員端一律看已生效版本——與章節同一條規則。"""
        uid = await _user(db, "ZT_SB2")
        other = await _user(db, "ZT_SB3")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await _stage_basic_edit(client, db, uid, ids, course_name="暫存的課名")

        detail = (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(other))).json()

        assert detail["course_name"] == "守門測試課程", "他人不得看到尚未生效的課名"

    async def test_受訓對象也讀暫存(self, client, db) -> None:
        """受訓對象與基本資料在同一張卡、同一次送出，讀取端分岔了就只有一半會更新。"""
        uid = await _user(db, "ZT_SB4")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        extra_unit, extra_tag = await _attach_tag(db, ids["course_id"], "乙")
        # 上一行直接寫活表是為了借一組**合法可選**的配對，隨即從活表移除，
        # 讓它只存在於本次暫存——否則分不出讀到的是暫存還是活表。
        await db.execute(
            update(EtCourseTag)
            .where(EtCourseTag.course_id == ids["course_id"], EtCourseTag.tag_id == extra_tag)
            .values(deleted=1)
        )
        await db.flush()
        await _stage_basic_edit(
            client,
            db,
            uid,
            ids,
            audiences=[
                {"unit_tag_id": ids["unit_tag_id"], "tag_id": ids["tag_id"]},
                {"unit_tag_id": extra_unit, "tag_id": extra_tag},
            ],
        )

        detail = (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))).json()

        assert {a["tag_id"] for a in detail["audiences"]} == {ids["tag_id"], extra_tag}

    async def test_version_回的是暫存節點的(self, client, db) -> None:
        """🔴 **前端拿這個數字去打下一次編輯與章節重排。**

        回活表的版本（暫存開始之後它就不再遞增）會讓第二次存檔恆 409，而教師看到的是
        「版本衝突，請重新整理」——重整之後還是同一個數字，他永遠存不進去。
        """
        uid = await _user(db, "ZT_SB5")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        live_before = (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))).json()["version"]
        await _stage_basic_edit(client, db, uid, ids, course_name="改一次")

        after = (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))).json()

        assert after["version"] == live_before + 1, "暫存列的版本要接著活表的值往下走"
        # 正向錨點：少了它，把實作寫成「永遠回 live_before + 1」也會讓上一條通過
        second = await client.put(
            f"{_COURSES}/{ids['course_id']}",
            json={
                "course_name": "改第二次",
                "open_start_at": ids["open_start_at"],
                "open_end_at": ids["open_end_at"],
                "audiences": [{"unit_tag_id": ids["unit_tag_id"], "tag_id": ids["tag_id"]}],
                "version": after["version"],
            },
            headers=_bearer(uid),
        )
        assert second.status_code == 204, f"拿詳細頁回的版本必須存得進去：{second.text}"

    async def test_既有內容回活表_id_新增的回負數(self, client, db) -> None:
        """⚠️ 前端把哪個數字帶回 PUT，決定後端改到哪一邊——回錯了不報錯，只改到別的東西。"""
        uid = await _user(db, "ZT_SR4")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )

        chapters = (await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))).json()["chapters"]
        by_name = {c["chapter_name"]: c["chapter_id"] for c in chapters}

        assert by_name["第一章"] == ids["chapter_id"], "既有章節回活表 id，與今天相同"
        assert by_name["暫存新章"] < 0, "本次編輯新增的回負數"

    async def test_還沒編輯過時讀活表(self, client, db) -> None:
        """正向錨點：少了它，把 `has_stage` 判斷拿掉（一律讀暫存）也會讓上面幾條通過。

        還沒編輯過時暫存區是空的，讀暫存會得到**一門沒有任何章節的課**。
        """
        uid = await _user(db, "ZT_SR5")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        assert [c["chapter_name"] for c in detail.json()["chapters"]] == ["第一章", "第二章"]


class TestHasPendingChanges:
    """`CourseDetail.has_pending_changes`——前端據此啟用「更新」鈕與顯示提示（#631）。

    🔴 少了這個旗標，教師編完直接離開會以為學員已經看到了——而那正是本功能把生效
    延後所製造的**新**風險。
    """

    async def test_編輯後為真(self, client, db) -> None:
        uid = await _user(db, "ZT_P1")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        assert detail.json()["has_pending_changes"] is True

    async def test_尚未編輯時為假(self, client, db) -> None:
        """正向錨點：少了它，讓旗標恆為真也會讓上一條通過——而那會讓「更新」鈕
        永遠亮著，教師按下去得到一個什麼都沒做的 no-op。"""
        uid = await _user(db, "ZT_P2")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        assert detail.json()["has_pending_changes"] is False

    async def test_草稿恆為假(self, client, db) -> None:
        """草稿的編輯本來就直接生效，沒有「尚未更新」這種狀態。"""
        uid = await _user(db, "ZT_P3")
        ids = await _course_with_content(client, db, uid)
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "草稿新章"}, headers=_bearer(uid)
        )

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        assert detail.json()["has_pending_changes"] is False

    async def test_他人看到的恆為假(self, client, db) -> None:
        """⚠️ 他人不該知道「這門課有人正在改」——那是擁有者的編輯狀態。"""
        uid = await _user(db, "ZT_P4")
        other = await _user(db, "ZT_P5")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(other))

        assert detail.json()["has_pending_changes"] is False

    async def test_更新成功後回到假(self, client, db) -> None:
        """按下「更新」之後暫存區清空，提示應消失。"""
        uid = await _user(db, "ZT_P6")
        ids = await _course_with_content(client, db, uid)
        await _publish(client, db, uid, ids["course_id"])
        ch = await client.post(
            f"{_COURSES}/{ids['course_id']}/chapters", json={"chapter_name": "暫存新章"}, headers=_bearer(uid)
        )
        await client.post(
            f"/api/et/chapters/{ch.json()['chapter_id']}/items",
            json={"item_type": ITEM_MATERIAL, "title": "新教材"},
            headers=_bearer(uid),
        )
        applied = await client.post(f"{_COURSES}/{ids['course_id']}/content/apply", headers=_bearer(uid))
        assert applied.status_code == 200, applied.text

        detail = await client.get(f"{_COURSES}/{ids['course_id']}", headers=_bearer(uid))

        assert detail.json()["has_pending_changes"] is False
        assert "暫存新章" in [c["chapter_name"] for c in detail.json()["chapters"]], "更新後內容已在活表"
