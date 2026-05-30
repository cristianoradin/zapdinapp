"""
app/tests/test_database_adapter.py — Testes do AsyncPGAdapter e _to_pg.

Não requer banco de dados — testa apenas a lógica de conversão SQL.
"""
import pytest
from app.core.database import _to_pg


class TestToPg:
    """Conversão de placeholders ? → $n."""

    def test_simples(self):
        assert _to_pg("SELECT * FROM t WHERE id=?") == "SELECT * FROM t WHERE id=$1"

    def test_multiplos(self):
        assert _to_pg("INSERT INTO t (a,b) VALUES (?,?)") == \
               "INSERT INTO t (a,b) VALUES ($1,$2)"

    def test_sem_placeholder(self):
        assert _to_pg("SELECT 1") == "SELECT 1"

    def test_tres_placeholders(self):
        sql = "UPDATE t SET a=?, b=? WHERE id=?"
        assert _to_pg(sql) == "UPDATE t SET a=$1, b=$2 WHERE id=$3"

    def test_ignora_interrogacao_em_string_simples(self):
        # '?' dentro de string literal não deve ser substituído
        sql = "SELECT * FROM t WHERE x = '?'"
        assert _to_pg(sql) == "SELECT * FROM t WHERE x = '?'"

    def test_ignora_interrogacao_em_string_dupla(self):
        sql = 'SELECT * FROM t WHERE x = "?" AND y = ?'
        result = _to_pg(sql)
        # '?' dentro de aspas duplas não muda; '?' fora vira $1
        assert '"?"' in result
        assert '$1' in result

    def test_mix_string_e_placeholder(self):
        sql = "SELECT * FROM t WHERE a='?' AND b=?"
        result = _to_pg(sql)
        assert "'?'" in result  # string literal preservada
        assert "$1" in result   # placeholder convertido

    def test_string_com_aspas_escapadas(self):
        # '' dentro de string simples (escape SQL padrão)
        sql = "INSERT INTO t (x) VALUES ('it''s here') WHERE y=?"
        result = _to_pg(sql)
        assert "$1" in result
        assert "it''s here" in result

    def test_cache_funciona(self):
        # Chamar duas vezes retorna o mesmo resultado (sem side-effect)
        sql = "SELECT ? FROM t WHERE id=?"
        r1 = _to_pg(sql)
        r2 = _to_pg(sql)
        assert r1 == r2 == "SELECT $1 FROM t WHERE id=$2"

    def test_ja_tem_dollar_placeholder(self):
        # SQL já em formato PostgreSQL — não altera
        sql = "SELECT * FROM t WHERE id=$1"
        assert _to_pg(sql) == "SELECT * FROM t WHERE id=$1"

    def test_string_vazia(self):
        assert _to_pg("") == ""


class TestToPgEdgeCases:
    """Edge cases mais complexos."""

    def test_ilike_pattern(self):
        # ILIKE '%?%' — interrogação dentro de string não deve ser convertida
        sql = "SELECT * FROM t WHERE x ILIKE '%?%' AND id=?"
        result = _to_pg(sql)
        assert "'%?%'" in result
        assert "$1" in result
        assert "$2" not in result  # só 1 placeholder real

    def test_json_com_interrogacao(self):
        # PostgreSQL JSON: WHERE data->>'key' = '?' AND id=?
        sql = "SELECT * FROM t WHERE data->>'key' = '?' AND id=?"
        result = _to_pg(sql)
        assert "'?'" in result
        assert "$1" in result

    def test_comentario_nao_afeta(self):
        # Comentários SQL não têm '?' normalmente, mas garantir que não quebra
        sql = "SELECT * FROM t WHERE id=? -- busca por id"
        assert _to_pg(sql) == "SELECT * FROM t WHERE id=$1 -- busca por id"
