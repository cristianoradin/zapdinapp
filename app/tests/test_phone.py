"""
app/tests/test_phone.py — Testes unitários para app.core.phone.

Não requer banco de dados ou fixtures — apenas lógica pura.
"""
import pytest
from app.core.phone import normalize_phone, phone_for_wa, phones_match


class TestNormalizePhone:
    def test_remove_ddi_55(self):
        assert normalize_phone("5511999990000") == "11999990000"

    def test_remove_ddi_55_com_12_digitos(self):
        assert normalize_phone("554491317080") == "4491317080"

    def test_mantem_sem_55(self):
        assert normalize_phone("11999990000") == "11999990000"

    def test_remove_formatacao(self):
        assert normalize_phone("+55 (11) 9999-0000") == "1199990000"

    def test_remove_jid_whatsapp(self):
        assert normalize_phone("5511999990000@s.whatsapp.net") == "11999990000"

    def test_string_vazia(self):
        assert normalize_phone("") == ""

    def test_nao_remove_55_curto(self):
        # '5511' tem 4 dígitos — não tem DDI, não remove
        assert normalize_phone("5511") == "5511"

    def test_apenas_digitos(self):
        # Remove todos não-dígitos
        assert normalize_phone("(44) 9 9131-7080") == "44991317080"

    def test_plus_prefixo(self):
        assert normalize_phone("+5511999990000") == "11999990000"


class TestPhoneForWa:
    def test_adiciona_55(self):
        assert phone_for_wa("11999990000") == "5511999990000"

    def test_nao_duplica_55(self):
        # normalize_phone remove 55 antes, depois phone_for_wa adiciona
        assert phone_for_wa("5511999990000") == "5511999990000"

    def test_vazio(self):
        assert phone_for_wa("") == ""

    def test_com_formatacao(self):
        assert phone_for_wa("+55 (11) 9999-0000") == "551199990000"


class TestPhonesMatch:
    def test_mesmo_numero(self):
        assert phones_match("11999990000", "11999990000")

    def test_com_sem_55(self):
        assert phones_match("5511999990000", "11999990000")

    def test_variante_9_digito_10_para_11(self):
        # 4491317080 (10 dig) deve bater com 44991317080 (11 dig)
        assert phones_match("4491317080", "44991317080")

    def test_variante_9_digito_11_para_10(self):
        assert phones_match("44991317080", "4491317080")

    def test_diferentes(self):
        assert not phones_match("11999990000", "11888880000")

    def test_com_jid(self):
        assert phones_match("5511999990000@s.whatsapp.net", "11999990000")

    def test_ambos_com_formatacao(self):
        assert phones_match("+55 (11) 9999-0000", "1199990000")

    def test_nao_bate_numeros_distintos(self):
        assert not phones_match("11999990000", "21999990000")
