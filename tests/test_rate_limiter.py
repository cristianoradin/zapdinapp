"""
test_rate_limiter.py — Testa o RateLimiter central (core/rate_limiter.py).

Cobre:
  1. Permite chamadas até o limite
  2. Bloqueia após o limite
  3. reset() libera novamente
  4. Instâncias pre-configuradas (login, erp, activation) têm os limites corretos
"""
from app.core.rate_limiter import RateLimiter, login_limiter, erp_limiter, activation_limiter


def test_permite_ate_o_limite():
    rl = RateLimiter(max_calls=3, period_seconds=60)
    assert rl.is_allowed("ip1") is True
    assert rl.is_allowed("ip1") is True
    assert rl.is_allowed("ip1") is True


def test_bloqueia_apos_limite():
    rl = RateLimiter(max_calls=3, period_seconds=60)
    for _ in range(3):
        rl.is_allowed("ip2")
    assert rl.is_allowed("ip2") is False


def test_reset_libera_novamente():
    rl = RateLimiter(max_calls=2, period_seconds=60)
    rl.is_allowed("ip3")
    rl.is_allowed("ip3")
    assert rl.is_allowed("ip3") is False

    rl.reset("ip3")
    assert rl.is_allowed("ip3") is True


def test_ips_diferentes_sao_independentes():
    rl = RateLimiter(max_calls=1, period_seconds=60)
    assert rl.is_allowed("ipA") is True
    assert rl.is_allowed("ipA") is False
    assert rl.is_allowed("ipB") is True   # ipB tem contador próprio


def test_login_limiter_tem_limite_correto():
    """login_limiter: 10 calls / 60s."""
    assert login_limiter._max == 10
    assert login_limiter._period == 60


def test_erp_limiter_tem_limite_correto():
    """erp_limiter: 60 calls / 60s."""
    assert erp_limiter._max == 60
    assert erp_limiter._period == 60


def test_activation_limiter_tem_limite_correto():
    """activation_limiter: 5 calls / 3600s."""
    assert activation_limiter._max == 5
    assert activation_limiter._period == 3600
