"""
app/repositories/contabil_repository.py — Acesso a dados do módulo contábil.

Entidades: empresas_contabil, documentos_fiscais, contabil_feed,
contabil_wa_pendentes, ocr_jobs.

ISOLAMENTO MULTI-TENANT (importante):
Todos os métodos que tocam empresas_contabil / documentos_fiscais /
contabil_feed recebem `tenant_id` como primeiro parâmetro e filtram por ele.
Exceções deliberadas (cross-tenant, uso interno do worker / webhook):
  - get_tenant_da_empresa        (webhook resolve tenant pela empresa)
  - marcar_boas_vindas_enviadas  (worker, empresa já resolvida)
  - listar_pendentes / marcar_enviado / registrar_falha_tentativa (worker)
  - criar_ocr_job / resetar_ocr_job (job atrelado ao documento, sem tenant)
"""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

from .base import BaseRepository

# Campos editáveis de empresas_contabil (ordem fixa do INSERT/UPDATE)
EMPRESA_FIELDS = [
    "nome", "cnpj", "ie", "cpf", "rg", "endereco", "numero_endereco",
    "bairro", "cep", "cidade", "uf", "telefone", "email", "regime_tributario",
]


class ContabilRepository(BaseRepository):

    # ── Empresas contábeis ────────────────────────────────────────────────────

    async def listar_empresas(self, tenant_id: int, q: Optional[str] = None) -> list:
        sql = """
            SELECT ec.*,
                   COUNT(df.id) FILTER (WHERE df.status != 'aprovado') AS docs_pendentes,
                   COUNT(df.id) FILTER (WHERE df.status = 'aprovado')  AS docs_aprovados,
                   COUNT(df.id) FILTER (WHERE df.status = 'ocr_erro')  AS docs_erro,
                   COUNT(df.id)                                         AS docs_total
            FROM empresas_contabil ec
            LEFT JOIN documentos_fiscais df ON df.empresa_id = ec.id
            WHERE ec.tenant_id = ?
        """
        params: list = [tenant_id]
        if q:
            sql += " AND (ec.nome ILIKE ? OR ec.cnpj LIKE ? OR ec.telefone LIKE ?)"
            like = f"%{q}%"
            params += [like, like, like]
        sql += " GROUP BY ec.id ORDER BY ec.nome"
        rows = await self._fetchall(sql, params)
        return [dict(r) for r in rows]

    async def telefone_existe(self, tenant_id: int, telefone: str) -> bool:
        row = await self._fetchone(
            "SELECT id FROM empresas_contabil WHERE telefone=? AND tenant_id=?",
            (telefone, tenant_id),
        )
        return row is not None

    async def criar_empresa(self, tenant_id: int, dados: dict) -> int:
        cur = await self._execute(
            """INSERT INTO empresas_contabil
               (tenant_id, nome, cnpj, ie, cpf, rg, endereco, numero_endereco, bairro, cep,
                cidade, uf, telefone, email, regime_tributario)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            tuple([tenant_id] + [dados.get(f) for f in EMPRESA_FIELDS]),
        )
        return cur.lastrowid

    async def get_empresa(self, tenant_id: int, empresa_id: int):
        return await self._fetchone(
            "SELECT * FROM empresas_contabil WHERE id=? AND tenant_id=?",
            (empresa_id, tenant_id),
        )

    async def empresa_existe(self, tenant_id: int, empresa_id: int) -> bool:
        row = await self._fetchone(
            "SELECT id FROM empresas_contabil WHERE id=? AND tenant_id=?",
            (empresa_id, tenant_id),
        )
        return row is not None

    async def get_nome_telefone(self, tenant_id: int, empresa_id: int):
        return await self._fetchone(
            "SELECT nome, telefone FROM empresas_contabil WHERE id=? AND tenant_id=?",
            (empresa_id, tenant_id),
        )

    async def atualizar_empresa(self, tenant_id: int, empresa_id: int, campos: dict) -> None:
        """`campos` — dict {coluna: valor} já filtrado (apenas colunas permitidas)."""
        fields, params = [], []
        for f, val in campos.items():
            fields.append(f"{f}=?")
            params.append(val)
        params.extend([empresa_id, tenant_id])
        await self._execute(
            f"UPDATE empresas_contabil SET {', '.join(fields)}, updated_at=NOW() "
            "WHERE id=? AND tenant_id=?",
            params,
        )

    async def deletar_empresa(self, tenant_id: int, empresa_id: int) -> None:
        await self._execute(
            "DELETE FROM empresas_contabil WHERE id=? AND tenant_id=?",
            (empresa_id, tenant_id),
        )

    async def set_boas_vindas(self, tenant_id: int, empresa_id: int, enviadas: bool) -> None:
        await self._execute(
            "UPDATE empresas_contabil SET boas_vindas_enviadas=? WHERE id=? AND tenant_id=?",
            (enviadas, empresa_id, tenant_id),
        )

    # cross-tenant (interno — worker de boas-vindas, empresa já resolvida)
    async def marcar_boas_vindas_enviadas(self, empresa_id: int) -> None:
        await self._execute_no_commit(
            "UPDATE empresas_contabil SET boas_vindas_enviadas=TRUE WHERE id=?",
            (empresa_id,),
        )

    # cross-tenant (webhook / worker resolvem o tenant pela empresa)
    async def get_tenant_da_empresa(self, empresa_id: int) -> Optional[int]:
        row = await self._fetchone(
            "SELECT tenant_id FROM empresas_contabil WHERE id=?", (empresa_id,)
        )
        return row["tenant_id"] if row else None

    async def empresa_existe_global(self, empresa_id: int) -> bool:
        """Cross-tenant — usada pelo webhook interno (resolve tenant depois)."""
        row = await self._fetchone(
            "SELECT tenant_id FROM empresas_contabil WHERE id=?", (empresa_id,)
        )
        return row is not None

    # ── Documentos fiscais ────────────────────────────────────────────────────

    async def listar_documentos(
        self,
        tenant_id: int,
        empresa_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> list:
        sql = """
            SELECT df.*, ec.nome AS empresa_nome
            FROM documentos_fiscais df
            LEFT JOIN empresas_contabil ec ON ec.id = df.empresa_id
            WHERE df.tenant_id=?
        """
        params: list = [tenant_id]
        if empresa_id:
            sql += " AND df.empresa_id=?"
            params.append(empresa_id)
        if status:
            sql += " AND df.status=?"
            params.append(status)
        sql += " ORDER BY df.created_at DESC LIMIT 200"
        rows = await self._fetchall(sql, params)
        return [dict(r) for r in rows]

    async def get_documento(self, tenant_id: int, doc_id: int) -> Optional[dict]:
        row = await self._fetchone(
            """SELECT df.*, ec.nome AS empresa_nome
               FROM documentos_fiscais df
               LEFT JOIN empresas_contabil ec ON ec.id = df.empresa_id
               WHERE df.id=? AND df.tenant_id=?""",
            (doc_id, tenant_id),
        )
        if not row:
            return None
        d = dict(row)
        # Parse JSON fields
        for f in ("dados_ocr", "dados_manual"):
            if d.get(f) and isinstance(d[f], str):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    pass
        return d

    async def get_arquivo(self, tenant_id: int, doc_id: int):
        return await self._fetchone(
            "SELECT arquivo_path, arquivo_mime, arquivo_nome "
            "FROM documentos_fiscais WHERE id=? AND tenant_id=?",
            (doc_id, tenant_id),
        )

    async def documento_existe(self, tenant_id: int, doc_id: int) -> bool:
        row = await self._fetchone(
            "SELECT id FROM documentos_fiscais WHERE id=? AND tenant_id=?",
            (doc_id, tenant_id),
        )
        return row is not None

    async def get_documento_arquivo_path(self, tenant_id: int, doc_id: int):
        return await self._fetchone(
            "SELECT arquivo_path FROM documentos_fiscais WHERE id=? AND tenant_id=?",
            (doc_id, tenant_id),
        )

    async def aprovar_documento(self, tenant_id: int, doc_id: int) -> None:
        await self._execute_no_commit(
            "UPDATE documentos_fiscais SET status='aprovado', updated_at=NOW() "
            "WHERE id=? AND tenant_id=?",
            (doc_id, tenant_id),
        )
        await self._execute_no_commit(
            "INSERT INTO contabil_feed(tenant_id, documento_id, tipo, descricao) VALUES(?,?,?,?)",
            (tenant_id, doc_id, "aprovado", "Documento aprovado pelo contador"),
        )
        await self._db.commit()

    async def entrada_manual(self, tenant_id: int, doc_id: int, dados: dict) -> None:
        """`dados` — campos não-nulos do payload (DadosManuaisNF.model_dump(exclude_none=True))."""
        valor_total = dados.get("valor_total")
        emitente_nome = dados.get("emitente_nome")
        emitente_cnpj = dados.get("emitente_cnpj")
        dest_nome = dados.get("destinatario_nome")
        dest_cnpj = dados.get("destinatario_cnpj")
        chave = dados.get("chave_acesso")
        numero = dados.get("numero_nf")
        data_emis = dados.get("data_emissao")  # já é date (do Pydantic)

        # JSON não serializa date — converte para string antes de salvar como JSON
        dados_json = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in dados.items()}

        await self._execute_no_commit(
            """UPDATE documentos_fiscais SET
                status='revisao_manual', dados_manual=?, chave_acesso=COALESCE(?,chave_acesso),
                numero_nf=COALESCE(?,numero_nf), emitente_nome=COALESCE(?,emitente_nome),
                emitente_cnpj=COALESCE(?,emitente_cnpj), destinatario_nome=COALESCE(?,destinatario_nome),
                destinatario_cnpj=COALESCE(?,destinatario_cnpj),
                valor_total=COALESCE(?,valor_total), data_emissao=COALESCE(?,data_emissao),
                updated_at=NOW()
               WHERE id=? AND tenant_id=?""",
            (json.dumps(dados_json, ensure_ascii=False), chave, numero,
             emitente_nome, emitente_cnpj, dest_nome, dest_cnpj,
             valor_total, data_emis, doc_id, tenant_id),
        )
        await self._execute_no_commit(
            "INSERT INTO contabil_feed(tenant_id, documento_id, tipo, descricao) VALUES(?,?,?,?)",
            (tenant_id, doc_id, "manual",
             f"Dados inseridos manualmente pelo contador — NF {numero or '?'}"),
        )
        await self._db.commit()

    async def reprocessar_documento(self, tenant_id: int, doc_id: int) -> None:
        """Marca doc como ocr_pendente e reseta o job OCR."""
        await self._execute_no_commit(
            "UPDATE documentos_fiscais SET status='ocr_pendente', erro_msg=NULL, updated_at=NOW() "
            "WHERE id=? AND tenant_id=?",
            (doc_id, tenant_id),
        )
        await self.resetar_ocr_job(doc_id)
        await self._db.commit()

    async def criar_documento(
        self,
        tenant_id: int,
        empresa_id: int,
        arquivo_path: str,
        arquivo_mime: str,
        arquivo_nome: Optional[str],
        feed_tipo: str,
        feed_descricao: str,
    ) -> int:
        """Insere documento fiscal (status ocr_pendente) + job OCR + evento no feed."""
        cur = await self._execute(
            """INSERT INTO documentos_fiscais
               (tenant_id, empresa_id, status, arquivo_path, arquivo_mime, arquivo_nome)
               VALUES (?, ?, 'ocr_pendente', ?, ?, ?)""",
            (tenant_id, empresa_id, arquivo_path, arquivo_mime, arquivo_nome),
        )
        doc_id = cur.lastrowid
        await self.criar_ocr_job(doc_id)
        await self._execute_no_commit(
            "INSERT INTO contabil_feed(tenant_id, empresa_id, documento_id, tipo, descricao) "
            "VALUES(?,?,?,?,?)",
            (tenant_id, empresa_id, doc_id, feed_tipo, feed_descricao),
        )
        await self._db.commit()
        return doc_id

    # ── Dashboard ─────────────────────────────────────────────────────────────

    async def dashboard_docs_hoje(self, tenant_id: int, hoje: date) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) AS total FROM documentos_fiscais "
            "WHERE tenant_id=? AND created_at::date = ?",
            (tenant_id, hoje),
        )
        return row["total"]

    async def dashboard_pendencias(self, tenant_id: int) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) AS total FROM documentos_fiscais "
            "WHERE tenant_id=? AND status IN ('ocr_pendente','revisao_manual')",
            (tenant_id,),
        )
        return row["total"]

    async def dashboard_taxa_ocr(self, tenant_id: int) -> float:
        row = await self._fetchone(
            """SELECT
                COUNT(*) FILTER (WHERE status = 'aprovado')  AS aprovados,
                COUNT(*) FILTER (WHERE status != 'recebido') AS processados
               FROM documentos_fiscais WHERE tenant_id=?""",
            (tenant_id,),
        )
        aprovados = row["aprovados"] or 0
        processados = row["processados"] or 0
        return round((aprovados / processados * 100), 1) if processados > 0 else 0.0

    async def dashboard_docs_recentes(self, tenant_id: int, limit: int = 50) -> list:
        rows = await self._fetchall(
            """SELECT df.*, ec.nome AS empresa_nome
               FROM documentos_fiscais df
               LEFT JOIN empresas_contabil ec ON ec.id = df.empresa_id
               WHERE df.tenant_id=?
               ORDER BY df.created_at DESC
               LIMIT ?""",
            (tenant_id, limit),
        )
        return [dict(r) for r in rows]

    # ── Feed de atividade ─────────────────────────────────────────────────────

    async def add_evento(
        self,
        tenant_id: Optional[int],
        tipo: str,
        descricao: str,
        empresa_id: Optional[int] = None,
        documento_id: Optional[int] = None,
        commit: bool = True,
    ) -> None:
        cols = ["tenant_id", "tipo", "descricao"]
        vals: list = [tenant_id, tipo, descricao]
        if empresa_id is not None:
            cols.append("empresa_id")
            vals.append(empresa_id)
        if documento_id is not None:
            cols.append("documento_id")
            vals.append(documento_id)
        sql = (
            f"INSERT INTO contabil_feed({', '.join(cols)}) "
            f"VALUES({','.join('?' * len(cols))})"
        )
        if commit:
            await self._execute(sql, tuple(vals))
        else:
            await self._execute_no_commit(sql, tuple(vals))

    async def listar_feed(self, tenant_id: int, limit: int = 50) -> list:
        rows = await self._fetchall(
            """SELECT cf.*, ec.nome AS empresa_nome
               FROM contabil_feed cf
               LEFT JOIN empresas_contabil ec ON ec.id = cf.empresa_id
               WHERE cf.tenant_id=?
               ORDER BY cf.criado_em DESC
               LIMIT ?""",
            (tenant_id, limit),
        )
        return [dict(r) for r in rows]

    # ── Boas-vindas pendentes (worker — cross-tenant por design) ─────────────

    async def enfileirar_boas_vindas(
        self, tenant_id: Optional[int], empresa_id: int, telefone: str, nome: str
    ) -> None:
        await self._execute(
            "INSERT INTO contabil_wa_pendentes(tenant_id, empresa_id, telefone, nome) "
            "VALUES(?,?,?,?)",
            (tenant_id, empresa_id, telefone, nome),
        )

    async def listar_pendentes(self, limit: int = 5) -> list:
        return await self._fetchall(
            "SELECT id, empresa_id, telefone, nome, tentativas "
            "FROM contabil_wa_pendentes WHERE status='pendente' "
            f"ORDER BY criado_em LIMIT {int(limit)}"
        )

    async def marcar_enviado(self, pendente_id: int) -> None:
        await self._execute(
            "UPDATE contabil_wa_pendentes SET status='enviado', enviado_em=NOW() WHERE id=?",
            (pendente_id,),
        )

    async def registrar_falha_tentativa(
        self, pendente_id: int, tentativas: int, status: str
    ) -> None:
        await self._execute(
            "UPDATE contabil_wa_pendentes SET tentativas=?, status=? WHERE id=?",
            (tentativas, status, pendente_id),
        )

    # ── Jobs OCR ──────────────────────────────────────────────────────────────

    async def criar_ocr_job(self, doc_id: int) -> None:
        await self._execute_no_commit(
            "INSERT INTO ocr_jobs(documento_id) VALUES(?) ON CONFLICT DO NOTHING",
            (doc_id,),
        )

    async def resetar_ocr_job(self, doc_id: int) -> None:
        await self._execute_no_commit(
            """INSERT INTO ocr_jobs(documento_id, status, tentativas)
               VALUES(?, 'pending', 0)
               ON CONFLICT(documento_id) DO UPDATE SET status='pending', tentativas=0, erro=NULL""",
            (doc_id,),
        )
