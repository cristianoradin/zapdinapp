"""
app/tests/test_rate_limit.py — Testes do rate limiter (unitário, sem DB).
"""
import time
from app.core.rate_limiter import RateLimiter, global_limiter


class TestRateLimiter:
    def test_permite_ate_o_limite(self):
        rl = RateLimiter(max_calls=3, period_seconds=60)
        assert rl.is_allowed("k") is True   # 1
        assert rl.is_allowed("k") is True   # 2
        assert rl.is_allowed("k") is True   # 3
        assert rl.is_allowed("k") is False  # 4 — bloqueado

    def test_chaves_isoladas(self):
        rl = RateLimiter(max_calls=1, period_seconds=60)
        assert rl.is_allowed("a") is True
        assert rl.is_allowed("b") is True   # outra chave, independente
        assert rl.is_allowed("a") is False

    def test_janela_expira(self):
        rl = RateLimiter(max_calls=1, period_seconds=0.1)
        assert rl.is_allowed("k") is True
        assert rl.is_allowed("k") is False
        time.sleep(0.15)
        assert rl.is_allowed("k") is True   # janela passou

    def test_reset(self):
        rl = RateLimiter(max_calls=1, period_seconds=60)
        assert rl.is_allowed("k") is True
        assert rl.is_allowed("k") is False
        rl.reset("k")
        assert rl.is_allowed("k") is True

    def test_global_limiter_config(self):
        # 600 req/min — generoso para multi-terminal
        assert global_limiter._max == 600
        assert global_limiter._period == 60
