"""
app/core/database.py — PostgreSQL multi-tenant via asyncpg.

Cada empresa (CNPJ ativado) tem um registro em `empresas`.
Todos os dados (usuarios, config, sessoes_wa, mensagens, arquivos)
são isolados por empresa_id.
"""
from __future__ import annotations

import logging
import asyncpg
from contextlib import asynccontextmanager
from functools import lru_cache
from .config import settings

logger = logging.getLogger(__name__)

# ── Pool global ───────────────────────────────────────────────────────────────
_pool: asyncpg.Pool | None = None


@lru_cache(maxsize=512)
def _to_pg(sql: str) -> str:
    """Converte placeholders SQLite '?' → '$1', '$2', ... do PostgreSQL.
    Resultado cacheado — a maioria das queries são strings literais repetidas.

    LIMITAÇÃO CONHECIDA: '?' dentro de string literal SQL (ex: WHERE x = '?')
    seria incorretamente substituído. Não há esse padrão nas queries atuais,
    mas queries futuras devem evitar '?' literal em strings — usar $$ quoting.
    """
    n, out = 0, []
    for ch in sql:
        if ch == '?':
            n += 1
            out.append(f'${n}')
        else:
            out.append(ch)
    return ''.join(out)


# ── Cursor proxy ──────────────────────────────────────────────────────────────

class _Cursor:
    __slots__ = ('lastrowid', '_rows')

    def __init__(self, rows=None, lastrowid: int | None = None):
        self.lastrowid = lastrowid
        self._rows: list = rows if rows is not None else []

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return self._rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


class _ExecProxy:
    __slots__ = ('_coro',)

    def __init__(self, coro):
        self._coro = coro

    def __await__(self):
        return self._coro.__await__()

    async def __aenter__(self):
        return await self._coro

    async def __aexit__(self, *_):
        pass


# ── Adapter principal ─────────────────────────────────────────────────────────

class AsyncPGAdapter:
    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    def execute(self, sql: str, params: tuple = ()) -> _ExecProxy:
        return _ExecProxy(self._run(sql, params))

    async def _run(self, sql: str, params: tuple) -> _Cursor:
        pg = _to_pg(sql)
        args = list(params)
        head = pg.lstrip().upper()

        if head.startswith('SELECT') or head.startswith('WITH'):
            rows = await self._conn.fetch(pg, *args)
            return _Cursor(rows=rows)

        if head.startswith('INSERT') and 'RETURNING' not in head:
            pg_ret = pg.rstrip().rstrip(';') + ' RETURNING id'
            try:
                row = await self._conn.fetchrow(pg_ret, *args)
                return _Cursor(lastrowid=row['id'] if row else None)
            except (asyncpg.UndefinedColumnError, asyncpg.PostgresSyntaxError,
                    asyncpg.UndefinedFunctionError):
                await self._conn.execute(pg, *args)
                return _Cursor()

        await self._conn.execute(pg, *args)
        return _Cursor()

    async def commit(self):
        """No-op: asyncpg faz autocommit fora de transações explícitas."""

    async def executemany(self, sql: str, params_list):
        pg = _to_pg(sql)
        await self._conn.executemany(pg, [list(p) for p in params_list])

    async def executescript(self, script: str):
        for stmt in script.split(';'):
            s = stmt.strip()
            if s:
                await self._conn.execute(s)


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_db():
    async with _pool.acquire() as conn:
        yield AsyncPGAdapter(conn)


@asynccontextmanager
async def get_db_direct():
    async with _pool.acquire() as conn:
        yield AsyncPGAdapter(conn)


# ── Inicialização multi-tenant ────────────────────────────────────────────────

async def init_db() -> None:
    global _pool
    # Oculta senha na URL para o log
    _db_url_log = settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url
    logger.info("[db] Conectando ao PostgreSQL: %s", _db_url_log)
    try:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    except Exception as exc:
        logger.error("[db] FALHA ao conectar ao PostgreSQL (%s): %s", _db_url_log, exc)
        raise
    logger.info("[db] Pool PostgreSQL criado (min=2 max=10)")

    async with _pool.acquire() as conn:

        # ── Empresas (tenants) ────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS empresas (
                id         BIGSERIAL PRIMARY KEY,
                cnpj       TEXT UNIQUE NOT NULL,
                nome       TEXT NOT NULL,
                token      TEXT UNIQUE NOT NULL,
                ativo      BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ── Usuários (scoped por empresa) ─────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id            BIGSERIAL PRIMARY KEY,
                empresa_id    BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                username      TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (empresa_id, username)
            )
        """)

        # ── Config por empresa ────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS config (
                empresa_id BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                key        TEXT NOT NULL,
                value      TEXT NOT NULL,
                PRIMARY KEY (empresa_id, key)
            )
        """)

        # ── Sessões WhatsApp por empresa ──────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessoes_wa (
                empresa_id BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                id         TEXT NOT NULL,
                nome       TEXT NOT NULL,
                status     TEXT DEFAULT 'disconnected',
                qr_data    TEXT,
                phone      TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_seen  TIMESTAMPTZ,
                PRIMARY KEY (empresa_id, id)
            )
        """)

        # ── Mensagens por empresa ─────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mensagens (
                id           BIGSERIAL PRIMARY KEY,
                empresa_id   BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                sessao_id    TEXT,
                destinatario TEXT NOT NULL,
                mensagem     TEXT,
                tipo         TEXT DEFAULT 'text',
                status       TEXT DEFAULT 'pending',
                erro         TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                sent_at      TIMESTAMPTZ
            )
        """)
        # ── Arquivos por empresa ──────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS arquivos (
                id            BIGSERIAL PRIMARY KEY,
                empresa_id    BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                nome_original TEXT NOT NULL,
                nome_arquivo  TEXT NOT NULL,
                tamanho       INTEGER,
                destinatario  TEXT,
                sessao_id     TEXT,
                caption       TEXT,
                status        TEXT DEFAULT 'pending',
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                sent_at       TIMESTAMPTZ,
                delivered_at  TIMESTAMPTZ,
                read_at       TIMESTAMPTZ,
                erro          TEXT
            )
        """)

        # ── Migration: single-tenant → multi-tenant ──────────────────────────
        # Passo 1: adiciona coluna empresa_id (nullable) nas tabelas existentes
        for _tbl in ('usuarios', 'config', 'sessoes_wa', 'mensagens', 'arquivos'):
            try:
                await conn.execute(
                    f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS empresa_id BIGINT"
                )
            except Exception:
                pass

        # Passo 2: remove dados antigos sem empresa_id (single-tenant, incompatíveis)
        for _tbl in ('config', 'sessoes_wa', 'mensagens', 'arquivos', 'usuarios'):
            try:
                await conn.execute(f"DELETE FROM {_tbl} WHERE empresa_id IS NULL")
            except Exception:
                pass

        # Corrige PRIMARY KEY de config: (key) → (empresa_id, key)
        await conn.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_name = 'config'
                     AND tc.constraint_type = 'PRIMARY KEY'
                     AND kcu.column_name = 'key'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.key_column_usage kcu2
                    JOIN information_schema.table_constraints tc2
                      ON kcu2.constraint_name = tc2.constraint_name
                     AND tc2.table_name = 'config'
                     AND tc2.constraint_type = 'PRIMARY KEY'
                     AND kcu2.column_name = 'empresa_id'
                ) THEN
                    ALTER TABLE config DROP CONSTRAINT config_pkey;
                    ALTER TABLE config ADD PRIMARY KEY (empresa_id, key);
                END IF;
            END $$;
        """)

        # Corrige PRIMARY KEY de sessoes_wa: (id) → (empresa_id, id)
        await conn.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_name = 'sessoes_wa'
                     AND tc.constraint_type = 'PRIMARY KEY'
                     AND kcu.column_name = 'id'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.key_column_usage kcu2
                    JOIN information_schema.table_constraints tc2
                      ON kcu2.constraint_name = tc2.constraint_name
                     AND tc2.table_name = 'sessoes_wa'
                     AND tc2.constraint_type = 'PRIMARY KEY'
                     AND kcu2.column_name = 'empresa_id'
                ) THEN
                    ALTER TABLE sessoes_wa DROP CONSTRAINT sessoes_wa_pkey;
                    ALTER TABLE sessoes_wa ADD PRIMARY KEY (empresa_id, id);
                END IF;
            END $$;
        """)

        # Corrige UNIQUE de usuarios: (username) → (empresa_id, username)
        await conn.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'usuarios'
                      AND constraint_type = 'UNIQUE'
                      AND constraint_name = 'usuarios_username_key'
                ) THEN
                    ALTER TABLE usuarios DROP CONSTRAINT usuarios_username_key;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'usuarios'
                      AND constraint_type = 'UNIQUE'
                      AND constraint_name = 'usuarios_empresa_id_username_key'
                ) THEN
                    ALTER TABLE usuarios
                        ADD CONSTRAINT usuarios_empresa_id_username_key
                        UNIQUE (empresa_id, username);
                END IF;
            END $$;
        """)

        # Adiciona coluna menus em usuarios (migração segura)
        await conn.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'usuarios' AND column_name = 'menus'
                ) THEN
                    ALTER TABLE usuarios ADD COLUMN menus TEXT;
                END IF;
            END $$;
        """)

        # Adiciona coluna avatar_url em usuarios (migração segura)
        await conn.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'usuarios' AND column_name = 'avatar_url'
                ) THEN
                    ALTER TABLE usuarios ADD COLUMN avatar_url TEXT;
                END IF;
            END $$;
        """)

        # Índices (seguros mesmo se coluna empresa_id foi adicionada agora)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mensagens_empresa ON mensagens(empresa_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mensagens_status ON mensagens(empresa_id, status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_arquivos_empresa ON arquivos(empresa_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_arquivos_status ON arquivos(empresa_id, status)")
        # Índice isolado para o worker (busca por status sem filtrar empresa_id)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mensagens_status_worker ON mensagens(status, id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_arquivos_status_worker ON arquivos(status, id)")
        # Índice de empresa em sessoes_wa (busca frequente do worker)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessoes_wa_empresa ON sessoes_wa(empresa_id)")

        # Migração: adiciona nome_destinatario em mensagens e arquivos
        for _tbl2 in ('mensagens', 'arquivos'):
            try:
                await conn.execute(
                    f"ALTER TABLE {_tbl2} ADD COLUMN IF NOT EXISTS nome_destinatario TEXT DEFAULT ''"
                )
            except Exception:
                pass

        # ── Disparo em Massa ───────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contatos (
                id         BIGSERIAL PRIMARY KEY,
                empresa_id BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                phone      TEXT NOT NULL,
                nome       TEXT DEFAULT '',
                ativo      BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (empresa_id, phone)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_contatos_empresa ON contatos(empresa_id)")
        await conn.execute("ALTER TABLE contatos ADD COLUMN IF NOT EXISTS origem TEXT DEFAULT 'manual'")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS campanhas (
                id         BIGSERIAL PRIMARY KEY,
                empresa_id BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                nome       TEXT NOT NULL,
                tipo       TEXT NOT NULL DEFAULT 'text',
                mensagem   TEXT DEFAULT '',
                status     TEXT DEFAULT 'draft',
                total      INTEGER DEFAULT 0,
                enviados   INTEGER DEFAULT 0,
                erros      INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                done_at    TIMESTAMPTZ
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_campanhas_empresa ON campanhas(empresa_id)")
        await conn.execute("ALTER TABLE campanhas ADD COLUMN IF NOT EXISTS agendado_em TIMESTAMPTZ")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS campanha_arquivos (
                id            BIGSERIAL PRIMARY KEY,
                campanha_id   BIGINT NOT NULL REFERENCES campanhas(id) ON DELETE CASCADE,
                nome_original TEXT NOT NULL,
                nome_arquivo  TEXT NOT NULL,
                created_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS campanha_envios (
                id             BIGSERIAL PRIMARY KEY,
                campanha_id    BIGINT NOT NULL REFERENCES campanhas(id) ON DELETE CASCADE,
                empresa_id     BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                phone          TEXT NOT NULL,
                nome           TEXT DEFAULT '',
                status         TEXT DEFAULT 'queued',
                erro           TEXT,
                created_at     TIMESTAMPTZ DEFAULT NOW(),
                sent_at        TIMESTAMPTZ
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_campanha_envios_status ON campanha_envios(campanha_id, status)")
        # M5: índices para campanhas e envios (tabelas já criadas acima)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_campanhas_status ON campanhas(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_campanha_envios_empresa_status ON campanha_envios(empresa_id, status)")
        # idx_avaliacoes_phone_created e idx_pdv_tokens_ativo são criados APÓS
        # as tabelas avaliacoes e pdv_tokens (seção Papel 5 — DBA, no final)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS grupos_contatos (
                id         BIGSERIAL PRIMARY KEY,
                empresa_id BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                nome       TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (empresa_id, nome)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS grupo_contatos (
                grupo_id   BIGINT NOT NULL REFERENCES grupos_contatos(id) ON DELETE CASCADE,
                contato_id BIGINT NOT NULL REFERENCES contatos(id) ON DELETE CASCADE,
                PRIMARY KEY (grupo_id, contato_id)
            )
        """)

        # Tokens de máquina para o PDV (sem usuário/senha)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pdv_tokens (
                id           BIGSERIAL PRIMARY KEY,
                empresa_id   BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                token        TEXT UNIQUE NOT NULL,
                nome         TEXT NOT NULL DEFAULT 'PDV',
                ativo        BOOLEAN DEFAULT TRUE,
                criado_em    TIMESTAMPTZ DEFAULT NOW(),
                ultimo_uso   TIMESTAMPTZ
            )
        """)

        # Sessões PDV locais reportadas pelos clientes
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pdv_sessoes (
                id           BIGSERIAL PRIMARY KEY,
                empresa_id   BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                sessao_id    TEXT NOT NULL,
                pdv_nome     TEXT NOT NULL DEFAULT '',
                phone        TEXT,
                status       TEXT NOT NULL DEFAULT 'unknown',
                updated_at   TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (empresa_id, sessao_id)
            )
        """)

        # ── Avaliações de atendimento ──────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS avaliacoes (
                id            BIGSERIAL PRIMARY KEY,
                empresa_id    BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                token         TEXT UNIQUE NOT NULL,
                phone         TEXT NOT NULL,
                nome_cliente  TEXT DEFAULT '',
                vendedor      TEXT DEFAULT '',
                valor         TEXT DEFAULT '',
                nota          INTEGER,
                comentario    TEXT,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                respondido_em TIMESTAMPTZ
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_avaliacoes_empresa ON avaliacoes(empresa_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_avaliacoes_token ON avaliacoes(token)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_avaliacoes_vendedor ON avaliacoes(empresa_id, vendedor)")

        # ── M3: Blacklist de sessões invalidadas (logout) ──────────────────────
        # Armazena SHA-256 do token para não expor o cookie cru.
        # Registros são apagados automaticamente após session_max_age pelo reporter.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS invalidated_sessions (
                token_hash   TEXT PRIMARY KEY,
                invalidated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ── Papel 5 — DBA: índices ausentes, constraints, audit trail ──────────

        # 1) Índices ausentes identificados por análise de query patterns
        # M5 (movidos aqui para garantir que as tabelas já existam):
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_avaliacoes_phone_created "
            "ON avaliacoes(phone, created_at DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pdv_tokens_ativo ON pdv_tokens(ativo)"
        )
        # mensagens: stats diárias filtram por created_at e sent_at
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mensagens_empresa_created "
            "ON mensagens(empresa_id, created_at DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mensagens_empresa_sent "
            "ON mensagens(empresa_id, sent_at DESC) "
            "WHERE sent_at IS NOT NULL"
        )
        # avaliacoes: dashboard filtra por created_at e respondido_em
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_avaliacoes_empresa_created "
            "ON avaliacoes(empresa_id, created_at DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_avaliacoes_respondido "
            "ON avaliacoes(empresa_id, respondido_em) "
            "WHERE respondido_em IS NOT NULL"
        )
        # campanha_envios: JOIN frequente só pelo campanha_id
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_campanha_envios_campanha "
            "ON campanha_envios(campanha_id)"
        )
        # grupos / grupo_contatos: lookups de listagem e reverse
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_grupos_contatos_empresa "
            "ON grupos_contatos(empresa_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_grupo_contatos_contato "
            "ON grupo_contatos(contato_id)"
        )
        # pdv: listagem por empresa
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pdv_tokens_empresa "
            "ON pdv_tokens(empresa_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pdv_sessoes_empresa "
            "ON pdv_sessoes(empresa_id)"
        )
        # invalidated_sessions: limpeza pelo reporter filtra por invalidated_at
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_invalidated_sessions_at "
            "ON invalidated_sessions(invalidated_at)"
        )
        # arquivos: worker filtra por empresa_id + status + created_at
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arquivos_empresa_created "
            "ON arquivos(empresa_id, created_at DESC)"
        )

        # 2) CHECK constraints de status (NOT VALID = não varre linhas existentes)
        #    Garante integridade no banco, independente do código Python.
        for _chk_sql in [
            """DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'mensagens' AND constraint_name = 'chk_mensagens_status'
                ) THEN
                    ALTER TABLE mensagens
                        ADD CONSTRAINT chk_mensagens_status
                        CHECK (status IN ('queued','pending','sent','error','failed','delivered','read'))
                        NOT VALID;
                END IF;
            END $$""",
            """DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'arquivos' AND constraint_name = 'chk_arquivos_status'
                ) THEN
                    ALTER TABLE arquivos
                        ADD CONSTRAINT chk_arquivos_status
                        CHECK (status IN ('queued','pending','sent','failed','delivered','read'))
                        NOT VALID;
                END IF;
            END $$""",
            """DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'campanhas' AND constraint_name = 'chk_campanhas_status'
                ) THEN
                    ALTER TABLE campanhas
                        ADD CONSTRAINT chk_campanhas_status
                        CHECK (status IN ('draft','scheduled','running','paused','done'))
                        NOT VALID;
                END IF;
            END $$""",
            """DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'campanha_envios' AND constraint_name = 'chk_envios_status'
                ) THEN
                    ALTER TABLE campanha_envios
                        ADD CONSTRAINT chk_envios_status
                        CHECK (status IN ('queued','paused','sent','failed','error'))
                        NOT VALID;
                END IF;
            END $$""",
            """DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'avaliacoes' AND constraint_name = 'chk_avaliacoes_nota'
                ) THEN
                    ALTER TABLE avaliacoes
                        ADD CONSTRAINT chk_avaliacoes_nota
                        CHECK (nota IS NULL OR (nota >= 1 AND nota <= 5))
                        NOT VALID;
                END IF;
            END $$""",
        ]:
            try:
                await conn.execute(_chk_sql)
            except Exception as _e:
                logger.warning("[db] CHECK constraint ignorada: %s", _e)

        # 3) Colunas updated_at para audit trail (contatos e campanhas mudam com frequência)
        await conn.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'contatos' AND column_name = 'updated_at'
                ) THEN
                    ALTER TABLE contatos ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();
                END IF;
            END $$
        """)
        await conn.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'campanhas' AND column_name = 'updated_at'
                ) THEN
                    ALTER TABLE campanhas ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();
                END IF;
            END $$
        """)

        # ── Módulo Contábil ───────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS empresas_contabil (
                id               BIGSERIAL PRIMARY KEY,
                nome             TEXT NOT NULL,
                cnpj             TEXT,
                ie               TEXT,
                cpf              TEXT,
                rg               TEXT,
                endereco         TEXT,
                numero_endereco  TEXT,
                bairro           TEXT,
                cep              TEXT,
                cidade           TEXT,
                uf               TEXT,
                telefone         TEXT NOT NULL,
                email            TEXT,
                regime_tributario TEXT DEFAULT 'simples_nacional',
                ativo            BOOLEAN DEFAULT TRUE,
                boas_vindas_enviadas BOOLEAN DEFAULT FALSE,
                created_at       TIMESTAMPTZ DEFAULT NOW(),
                updated_at       TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_empresas_contabil_telefone
            ON empresas_contabil(telefone)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS documentos_fiscais (
                id               BIGSERIAL PRIMARY KEY,
                empresa_id       BIGINT REFERENCES empresas_contabil(id) ON DELETE CASCADE,
                tipo             TEXT DEFAULT 'nfe',   -- nfe | nfce | cte | outro
                status           TEXT DEFAULT 'recebido',
                -- recebido | ocr_pendente | ocr_erro | revisao_manual | aprovado
                origem_wa        TEXT,     -- número WhatsApp que enviou
                arquivo_path     TEXT,     -- caminho em disco
                arquivo_mime     TEXT,     -- image/jpeg | application/pdf | etc
                arquivo_nome     TEXT,
                dados_ocr        JSONB,    -- JSON extraído pela IA
                dados_manual     JSONB,    -- JSON inserido manualmente (override)
                erro_msg         TEXT,
                chave_acesso     TEXT,
                numero_nf        TEXT,
                emitente_nome    TEXT,
                emitente_cnpj    TEXT,
                destinatario_nome TEXT,
                destinatario_cnpj TEXT,
                valor_total      NUMERIC(14,2),
                data_emissao     DATE,
                created_at       TIMESTAMPTZ DEFAULT NOW(),
                updated_at       TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_docs_fiscais_empresa
            ON documentos_fiscais(empresa_id, created_at DESC)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_docs_fiscais_status
            ON documentos_fiscais(status, created_at DESC)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ocr_jobs (
                id              BIGSERIAL PRIMARY KEY,
                documento_id    BIGINT NOT NULL REFERENCES documentos_fiscais(id) ON DELETE CASCADE,
                status          TEXT NOT NULL DEFAULT 'pending',
                -- pending | processing | done | failed
                tentativas      INTEGER DEFAULT 0,
                erro            TEXT,
                criado_em       TIMESTAMPTZ DEFAULT NOW(),
                processado_em   TIMESTAMPTZ,
                UNIQUE (documento_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contabil_feed (
                id          BIGSERIAL PRIMARY KEY,
                empresa_id  BIGINT REFERENCES empresas_contabil(id) ON DELETE SET NULL,
                documento_id BIGINT REFERENCES documentos_fiscais(id) ON DELETE SET NULL,
                tipo        TEXT NOT NULL,
                -- recebido | ocr_iniciado | ocr_ok | ocr_erro | aprovado | manual | boas_vindas
                descricao   TEXT NOT NULL,
                criado_em   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_contabil_feed_ts
            ON contabil_feed(criado_em DESC)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contabil_wa_pendentes (
                id          BIGSERIAL PRIMARY KEY,
                empresa_id  BIGINT REFERENCES empresas_contabil(id) ON DELETE CASCADE,
                telefone    TEXT NOT NULL,
                nome        TEXT NOT NULL,
                tentativas  INTEGER DEFAULT 0,
                status      TEXT DEFAULT 'pendente',
                -- pendente | enviado | falha
                criado_em   TIMESTAMPTZ DEFAULT NOW(),
                enviado_em  TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ctb_wa_pendentes_status
            ON contabil_wa_pendentes(status, criado_em)
        """)

        # 4) Tabela de tracking de migrações aplicadas
        await conn.execute("""
            -- ── Chatbot ───────────────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS chatbot_config (
                empresa_id    BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                ativo         BOOLEAN DEFAULT TRUE,
                system_prompt TEXT DEFAULT '',
                PRIMARY KEY (empresa_id)
            );

            CREATE TABLE IF NOT EXISTS chat_historico (
                id         BIGSERIAL PRIMARY KEY,
                empresa_id BIGINT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
                phone      TEXT NOT NULL,
                role       TEXT NOT NULL CHECK (role IN ('user','assistant')),
                conteudo   TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_chat_hist_empresa_phone
                ON chat_historico(empresa_id, phone, created_at DESC);

            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW(),
                descricao  TEXT
            )
        """)
        # Registra as migrações já aplicadas (idempotente via ON CONFLICT DO NOTHING)
        for _ver, _desc in [
            ("001_initial",           "Schema inicial multi-tenant"),
            ("002_m5_indexes",        "Índices M5: campanhas, envios, avaliacoes, pdv_tokens"),
            ("003_m3_blacklist",      "Tabela invalidated_sessions para logout seguro"),
            ("004_dba_improvements",  "DBA: índices extras, CHECK constraints, updated_at"),
            ("005_contabil",          "Módulo Contábil: empresas_contabil, documentos_fiscais, ocr_jobs, contabil_feed"),
            ("006_ctb_wa_pendentes",  "Fila de boas-vindas WA pendentes para empresas contábil"),
            ("007_ctb_address_fields", "Campos CEP, numero_endereco e bairro em empresas_contabil"),
            ("008_chatbot",           "Tabelas chatbot_config e chat_historico"),
        ]:
            await conn.execute(
                "INSERT INTO schema_migrations(version, descricao) VALUES($1,$2) "
                "ON CONFLICT(version) DO NOTHING",
                _ver, _desc,
            )

        # ── Migration 007: adicionar cep, numero_endereco, bairro em empresas_contabil ──
        for _col, _type in [
            ("cep",             "TEXT"),
            ("numero_endereco", "TEXT"),
            ("bairro",          "TEXT"),
        ]:
            try:
                await conn.execute(
                    f"ALTER TABLE empresas_contabil ADD COLUMN IF NOT EXISTS {_col} {_type}"
                )
            except Exception:
                pass  # coluna já existe — ignorar

        logger.info("[db] Schema DBA inicializado — índices, constraints e migrations ok")
