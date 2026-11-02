-- ============================================================
-- EDMS app 執行期 DB 角色：建立並補齊最小權限（#22）
--
-- 冪等：可重複執行，每次都把權限收斂到下表的狀態。
-- 必須以「資料表 owner」（執行 alembic migration 的角色）或 superuser 連線執行，
-- 且須在 `alembic upgrade head` 之後（腳本會檢查 DP_AUDIT_LOG 是否存在）：
--
--   psql -v ON_ERROR_STOP=1 -v app_role=edms_app -d edms -f scripts/db-app-role.sql
--
-- 未給 -v app_role 時預設 edms_app。
-- 本腳本**不設定密碼**（避免密碼出現在檔案、指令列或 shell history）；
-- 角色建立後以 psql 的 \password 設定，步驟見 docs/infra/deployment.md「DB 角色」。
--
-- 收斂後的權限：
--   | 對象                         | app 角色可做                               |
--   |------------------------------|--------------------------------------------|
--   | public schema 的一般資料表    | SELECT / INSERT / UPDATE / DELETE          |
--   | DP_AUDIT_LOG                 | SELECT / INSERT（append-only）             |
--   | alembic_version              | SELECT（schema 版本只由 migration 改）     |
--   | public schema 的 sequence     | USAGE / SELECT                             |
--   | owner 日後建立的資料表／sequence | 同上兩列（ALTER DEFAULT PRIVILEGES，不必重跑） |
--   不給：DDL（CREATE）、TRUNCATE、REFERENCES、TRIGGER、sequence 的 UPDATE（setval）
--
-- 角色屬性固定為 LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS。
-- 防呆：app_role 若是資料表 owner、superuser、擁有任何物件（含 schema）或本資料庫，或是任何角色的成員（成員關係會繞過
-- 本腳本的 REVOKE，例如 pg_write_all_data 或 owner 本身），直接中止。
-- ============================================================

\set ON_ERROR_STOP on
\if :{?app_role}
\else
  \set app_role edms_app
\endif

SELECT set_config('edms.app_role', :'app_role', false);

DO $body$
DECLARE
    app_role   text := current_setting('edms.app_role');
    owner_role text;
BEGIN
    IF app_role IS NULL OR btrim(app_role) = '' THEN
        RAISE EXCEPTION 'app_role 未指定';
    END IF;

    -- 另驗 EDMS 獨有的表：TBMS 也沿用 DP_ 前綴表名，只看 DP_AUDIT_LOG 分不出連錯庫
    IF to_regclass('public."DP_AUDIT_LOG"') IS NULL OR to_regclass('public."ET_COURSE"') IS NULL THEN
        RAISE EXCEPTION '找不到 DP_AUDIT_LOG / ET_COURSE：請先執行 alembic upgrade head，或確認連到 EDMS 的資料庫';
    END IF;
    SELECT pg_get_userbyid(relowner) INTO owner_role FROM pg_class WHERE oid = 'public."DP_AUDIT_LOG"'::regclass;

    IF app_role = owner_role THEN
        RAISE EXCEPTION 'app_role (%) 不可與資料表 owner 相同', app_role;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_role AND rolsuper) THEN
        RAISE EXCEPTION 'app_role (%) 是 superuser，拒絕執行', app_role;
    END IF;
    -- 擁有任何物件（含 schema、函式，跨資料庫）或是本資料庫的 owner：可 DROP / 重建資料表，GRANT 管不到
    IF EXISTS (
        SELECT 1 FROM pg_shdepend d JOIN pg_roles r ON r.oid = d.refobjid
        WHERE r.rolname = app_role AND d.deptype = 'o'
    ) OR EXISTS (
        SELECT 1 FROM pg_database db JOIN pg_roles r ON r.oid = db.datdba
        WHERE db.datname = current_database() AND r.rolname = app_role
    ) THEN
        RAISE EXCEPTION 'app_role (%) 擁有資料庫物件，不是單純的執行期角色', app_role;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_role) THEN
        EXECUTE format('CREATE ROLE %I LOGIN', app_role);
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = app_role
    ) THEN
        RAISE EXCEPTION 'app_role (%) 是其他角色的成員，會繞過本腳本的權限收斂；請先解除成員關係', app_role;
    END IF;
    EXECUTE format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', app_role);

    -- 連線與 schema
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), app_role);
    EXECUTE format('REVOKE CREATE ON DATABASE %I FROM %I', current_database(), app_role);
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', app_role);
    EXECUTE format('REVOKE CREATE ON SCHEMA public FROM %I', app_role);

    -- 既有物件：先給一般 DML，再收回不該有的
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', app_role);
    EXECUTE format('REVOKE TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM %I', app_role);
    EXECUTE format('REVOKE UPDATE, DELETE ON public."DP_AUDIT_LOG" FROM %I', app_role);
    IF to_regclass('public.alembic_version') IS NOT NULL THEN
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE ON public.alembic_version FROM %I', app_role);
    END IF;
    EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', app_role);
    EXECUTE format('REVOKE UPDATE ON ALL SEQUENCES IN SCHEMA public FROM %I', app_role);

    -- owner 日後（新 migration）建立的物件自動帶入同樣權限；先全收回再給，曾被多給的預設權限也一併收斂
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE ALL ON TABLES FROM %I',
        owner_role, app_role);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I',
        owner_role, app_role);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
        owner_role, app_role);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO %I',
        owner_role, app_role);

    -- 事後斷言：不論權限來自哪裡（PUBLIC、殘留授權），結果不符就整段回滾
    IF has_table_privilege(app_role, 'public."DP_AUDIT_LOG"', 'UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES') THEN
        RAISE EXCEPTION 'app_role (%) 對 DP_AUDIT_LOG 仍有 INSERT / SELECT 以外的權限，請檢查授予 PUBLIC 的權限', app_role;
    END IF;
    IF NOT (has_table_privilege(app_role, 'public."DP_AUDIT_LOG"', 'INSERT')
            AND has_table_privilege(app_role, 'public."DP_AUDIT_LOG"', 'SELECT')) THEN
        RAISE EXCEPTION 'app_role (%) 對 DP_AUDIT_LOG 缺 INSERT / SELECT，app 將無法寫入稽核', app_role;
    END IF;
    IF to_regclass('public.alembic_version') IS NOT NULL
       AND has_table_privilege(app_role, 'public.alembic_version', 'INSERT, UPDATE, DELETE, TRUNCATE') THEN
        RAISE EXCEPTION 'app_role (%) 仍可寫入 alembic_version，請檢查授予 PUBLIC 的權限', app_role;
    END IF;
    IF has_schema_privilege(app_role, 'public', 'CREATE') OR has_database_privilege(app_role, current_database(), 'CREATE') THEN
        RAISE EXCEPTION 'app_role (%) 仍可在 public schema / 資料庫建立物件（多半是授予 PUBLIC 的 CREATE），'
            '請由 owner 執行 REVOKE CREATE ON SCHEMA public FROM PUBLIC 後重跑', app_role;
    END IF;

    RAISE NOTICE 'app 角色 % 權限已收斂（owner: %）', app_role, owner_role;
END
$body$;
