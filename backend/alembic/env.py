import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import settings
from app.core.db import Base
from app.dm.audience.models import DmUserTag  # noqa: F401
from app.dm.catalog.models import DmCategory, DmFunc, DmTag, DmTagGroup  # noqa: F401
from app.dm.document.models import DmDocRead, DmDocTag, DmDocument, DmDocVersion  # noqa: F401
from app.dm.review.models import DmChangeLog, DmReview  # noqa: F401

# DM 模組
from app.dm.roles.models import DmUserRole, DmUserRoleLog  # noqa: F401

# 匯入所有 model，讓 Alembic autogenerate 能掃描到。
# 每新增一個 module 的 model，在此處加上 import（並於行末以 noqa 抑制 F401），例如：
#   from app.et.courses.models import Course
from app.dp.audit.models import DpAuditLog  # noqa: F401
from app.dp.notify.models import DpEmailLog, DpNotifyTemplate  # noqa: F401
from app.dp.params.models import DpParamDetail, DpParamMaster  # noqa: F401
from app.dp.schedules.models import DpSchedule, DpScheduleLog  # noqa: F401
from app.dp.user.models import DpPwdHistory, DpPwdReset  # noqa: F401
from app.dp.users.models import DpUser  # noqa: F401

# ET 模組（#185 Foundation，28 表）
from app.et.catalog.models import EtCourseTag, EtTag, EtUserTag  # noqa: F401
from app.et.course.models import EtChapter, EtCourse, EtItem  # noqa: F401
from app.et.invitation.models import EtInvitation, EtOwnerTransfer  # noqa: F401
from app.et.material.models import (  # noqa: F401
    EtMaterial,
    EtMaterialDoc,
    EtMaterialVideo,
)
from app.et.progress.models import (  # noqa: F401
    EtEnrollment,
    EtProgress,
    EtProgressInterval,
    EtProgressVideo,
)
from app.et.quiz.models import (  # noqa: F401
    EtOption,
    EtQuestion,
    EtQuiz,
    EtQuizAttemptD,
    EtQuizAttemptM,
    EtQuizRetryReset,
)
from app.et.roles.models import EtUserRole  # noqa: F401
from app.et.stats.models import EtWeeklyStat  # noqa: F401
from app.et.survey.models import (  # noqa: F401
    EtSurvey,
    EtSurveyOption,
    EtSurveyQuestion,
    EtSurveyResponseD,
    EtSurveyResponseM,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
