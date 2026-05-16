"""
app/domain/entities.py — Entidades de domínio (tipadas, sem ORM).

Representam os objetos de negócio do ZapDin.
São dataclasses simples — sem dependência de banco ou HTTP.
Os repositories convertem registros do banco para estas entidades.
Os routers recebem DTOs Pydantic e os convertem para entidades.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── Empresa (tenant) ──────────────────────────────────────────────────────────

@dataclass
class Empresa:
    id: int
    cnpj: str
    nome: str
    token: str
    ativo: bool = True
    created_at: Optional[datetime] = None


# ── Mensagem ──────────────────────────────────────────────────────────────────

@dataclass
class Mensagem:
    empresa_id: int
    destinatario: str
    mensagem: str
    tipo: str = "text"
    status: str = "queued"
    id: Optional[int] = None
    nome_destinatario: str = ""
    sessao_id: Optional[str] = None
    erro: Optional[str] = None
    created_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None


# ── Contato ───────────────────────────────────────────────────────────────────

@dataclass
class Contato:
    empresa_id: int
    phone: str
    nome: str = ""
    ativo: bool = True
    origem: str = "manual"
    id: Optional[int] = None
    created_at: Optional[datetime] = None


# ── Campanha ──────────────────────────────────────────────────────────────────

@dataclass
class Campanha:
    empresa_id: int
    nome: str
    tipo: str = "text"
    mensagem: str = ""
    status: str = "draft"
    total: int = 0
    enviados: int = 0
    erros: int = 0
    id: Optional[int] = None
    agendado_em: Optional[datetime] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    done_at: Optional[datetime] = None


@dataclass
class CampanhaEnvio:
    campanha_id: int
    empresa_id: int
    phone: str
    nome: str = ""
    status: str = "queued"
    id: Optional[int] = None
    erro: Optional[str] = None
    created_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None


@dataclass
class GrupoContatos:
    empresa_id: int
    nome: str
    id: Optional[int] = None
    total: int = 0
    created_at: Optional[datetime] = None


# ── Avaliação ─────────────────────────────────────────────────────────────────

@dataclass
class Avaliacao:
    empresa_id: int
    token: str
    phone: str
    nome_cliente: str = ""
    vendedor: str = ""
    valor: str = ""
    nota: Optional[int] = None
    comentario: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    respondido_em: Optional[datetime] = None


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class ConfigEntry:
    empresa_id: int
    key: str
    value: str


# ── PDV ───────────────────────────────────────────────────────────────────────

@dataclass
class PdvToken:
    empresa_id: int
    token: str
    nome: str = "PDV"
    ativo: bool = True
    id: Optional[int] = None
    criado_em: Optional[datetime] = None
    ultimo_uso: Optional[datetime] = None


# ── Arquivo ───────────────────────────────────────────────────────────────────

@dataclass
class Arquivo:
    empresa_id: int
    nome_original: str
    nome_arquivo: str
    status: str = "queued"
    tamanho: int = 0
    destinatario: str = ""
    nome_destinatario: str = ""
    caption: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    erro: Optional[str] = None
