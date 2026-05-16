# app/repositories — Camada de acesso a dados.
# Cada repositório encapsula todas as queries de uma entidade.
# Os routers e services só chamam métodos dos repositórios — nunca SQL direto.

from .mensagem_repository import MensagemRepository
from .contato_repository import ContatoRepository
from .campanha_repository import CampanhaRepository
from .avaliacao_repository import AvaliacaoRepository
from .config_repository import ConfigRepository

__all__ = [
    "MensagemRepository",
    "ContatoRepository",
    "CampanhaRepository",
    "AvaliacaoRepository",
    "ConfigRepository",
]
