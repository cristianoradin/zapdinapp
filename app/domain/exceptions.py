"""
app/domain/exceptions.py — Exceções de domínio.

Cada exceção representa uma violação de regra de negócio.
Os routers capturam e convertem para HTTPException com o status correto.
Isso mantém a lógica de negócio desacoplada do framework HTTP.
"""


class DomainError(Exception):
    """Base para todas as exceções de domínio."""


class EmpresaNaoEncontrada(DomainError):
    pass


class TokenErpInvalido(DomainError):
    pass


class CampanhaNaoEncontrada(DomainError):
    pass


class CampanhaEmExecucao(DomainError):
    pass


class SemContatosParaDisparar(DomainError):
    pass


class GrupoNaoEncontrado(DomainError):
    pass


class AvaliacaoNaoEncontrada(DomainError):
    pass


class AvaliacaoJaRespondida(DomainError):
    pass


class ContatoJaExiste(DomainError):
    pass


class ArquivoInvalido(DomainError):
    pass


class LimiteDeTamanhoExcedido(DomainError):
    pass
