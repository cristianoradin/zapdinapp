"""
app/core/phone.py — Normalização canônica de números de telefone.

Padrão do sistema: apenas dígitos, sem DDI 55, sem formatação.
Ex: '+55 (11) 99999-0000' → '11999990000'
Ex: '5511999990000'      → '11999990000'
Ex: '11999990000@s.whatsapp.net' → '11999990000'

Use `phone_for_wa(p)` para montar o número completo que a Evolution API espera.
"""
import re


def normalize_phone(phone: str) -> str:
    """
    Remove DDI 55, @suffix, formatação — retorna só dígitos locais.
    Padrão canônico: '11999990000' (DDD + número, sem 55).
    """
    if not phone:
        return ""
    # Remove @domínio (WhatsApp JID: 5511...@s.whatsapp.net)
    p = phone.split("@")[0]
    # Mantém só dígitos
    p = re.sub(r"\D", "", p)
    # Remove DDI Brasil 55 se presente (len >= 12 garante que não é DDD+8 dígitos)
    if p.startswith("55") and len(p) >= 12:
        p = p[2:]
    return p


def phone_for_wa(phone: str) -> str:
    """
    Retorna número no formato que a Evolution API espera: '5511999990000'.
    """
    local = normalize_phone(phone)
    if not local:
        return ""
    return "55" + local


def phones_match(a: str, b: str) -> bool:
    """
    Compara dois números independente de formatação/DDI.
    Também tenta variante com/sem 9 extra (migração Brasil DDD+8→DDD+9).
    """
    na = normalize_phone(a)
    nb = normalize_phone(b)
    if na == nb:
        return True
    # Variante 9 extra: insere/remove 9 após DDD (posição 2)
    def _variants(p: str) -> set:
        v = {p}
        if len(p) == 10:
            v.add(p[:2] + "9" + p[2:])
        elif len(p) == 11 and p[2] == "9":
            v.add(p[:2] + p[3:])
        return v
    return bool(_variants(na) & _variants(nb))
