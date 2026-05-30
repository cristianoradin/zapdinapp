"""baseline_schema_inicial

Revision ID: 5593fb3fd3ec
Revises: 
Create Date: 2026-05-30

BASELINE — schema já existe via init_db().
Esta migração é vazia e serve apenas como ponto de partida.

Para novas instalações: init_db() cria tudo, depois 'alembic stamp head'.
Para mudanças futuras: crie nova revisão com 'alembic revision -m "descricao"'
e escreva o SQL em upgrade()/downgrade().
"""
from alembic import op

revision = '5593fb3fd3ec'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schema já existe via app/core/database.py::init_db()
    pass


def downgrade() -> None:
    pass
