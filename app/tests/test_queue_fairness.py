"""
test_queue_fairness.py — Round-robin por empresa na fila do worker.

Garante que:
  1. _rotate alterna empresas (fairness) em vez de servir sempre a menor.
  2. Empresa bloqueada não monopoliza a rotação.
"""
from app.services import queue_worker as qw


def setup_function():
    # Reseta ponteiros entre testes
    qw._rr_ptrs.update({"msg": -1, "arq": -1, "camp": -1})


def test_rotate_lista_vazia():
    assert qw._rotate([], "msg") == []


def test_rotate_comeca_do_inicio_sem_historico():
    assert qw._rotate([1, 2, 3], "msg") == [1, 2, 3]


def test_rotate_continua_apos_ultimo_servido():
    qw._rr_ptrs["msg"] = 1
    assert qw._rotate([1, 2, 3], "msg") == [2, 3, 1]


def test_rotate_da_a_volta():
    qw._rr_ptrs["msg"] = 3
    assert qw._rotate([1, 2, 3], "msg") == [1, 2, 3]


def test_rotate_empresa_servida_some_da_fila():
    # Última servida foi 2; agora só 1 e 3 têm itens → 3 vem primeiro
    qw._rr_ptrs["msg"] = 2
    assert qw._rotate([1, 3], "msg") == [3, 1]


def test_rotate_fairness_simulada():
    """Simula 6 rodadas com 3 empresas: cada uma é servida 2x (nunca monopólio)."""
    servidas = []
    for _ in range(6):
        ordem = qw._rotate([10, 20, 30], "msg")
        escolhida = ordem[0]  # worker processa a primeira elegível
        servidas.append(escolhida)
        qw._rr_ptrs["msg"] = escolhida
    assert servidas == [10, 20, 30, 10, 20, 30]


def test_rotate_pula_bloqueada_sem_travar():
    """Empresa 10 bloqueada (sem sessão): worker daria continue e serviria a 20.
    A rotação deve oferecer as demais na sequência."""
    ordem = qw._rotate([10, 20, 30], "msg")
    # Worker pula a 10 (continue) e processa a 20
    proxima_elegivel = [e for e in ordem if e != 10][0]
    assert proxima_elegivel == 20
    qw._rr_ptrs["msg"] = proxima_elegivel
    # Próxima rodada: 30 vem antes de 10 e 20
    assert qw._rotate([10, 20, 30], "msg") == [30, 10, 20]


def test_ponteiros_independentes_por_tipo():
    qw._rr_ptrs["msg"] = 2
    qw._rr_ptrs["arq"] = -1
    assert qw._rotate([1, 2, 3], "msg") == [3, 1, 2]
    assert qw._rotate([1, 2, 3], "arq") == [1, 2, 3]
