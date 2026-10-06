"""
modules/phone.py

Normalizacao e classificacao de telefones. Modulo puro (sem pywhatkit, sem
rede, sem tela), usado pelo envio, pelo CRM (opt-out) e pelo filtro de leads.

Regras para o Brasil (DDI 55), pelo numero nacional = DDD + numero local:
  - celular : DDD valido + 9 digitos comecando com 9  (11 digitos no total)
  - fixo    : DDD valido + 8 digitos comecando com 2-5 (10 digitos no total)
  - 0800/0300/0500/0900 e outros que comecam com 0 -> invalido (nao e WhatsApp)
Numeros antigos de 10 digitos comecando com 6-9 (celular sem o nono digito)
sao tratados como "invalido": o WhatsApp exige o 9 e adivinhar o numero certo
geraria mensagens para a pessoa errada.
"""

from __future__ import annotations

import re

MOBILE = "celular"
LANDLINE = "fixo"
INVALID = "invalido"
UNKNOWN = "desconhecido"  # fora do Brasil: nao da para classificar

_VALID_DDDS = {
    *range(11, 20), 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38,
    *range(41, 50), 51, 53, 54, 55, *range(61, 70), 71, 73, 74, 75, 77, 79,
    *range(81, 90), *range(91, 100),
}

_SPECIAL_PREFIXES = ("0800", "0300", "0500", "0900")


def digits_only(raw: str | None) -> str:
    return re.sub(r"\D", "", raw or "")


def normalize_phone(raw_phone: str | None, default_country_code: str = "55") -> str | None:
    """
    Normaliza para E.164 (ex: +5541999998888). Retorna None se nao der para
    extrair um numero plausivel. NAO diz se e celular: use `classify_phone`.
    """
    digits = digits_only(raw_phone)
    if not digits:
        return None

    if digits.startswith(_SPECIAL_PREFIXES):
        return None

    # Prefixo de tronco "0" + DDD + numero (ex: 041 99999-8888).
    if digits.startswith("0") and len(digits) in (11, 12):
        digits = digits[1:]

    if digits.startswith(default_country_code) and len(digits) in (12, 13):
        return f"+{digits}"

    if len(digits) in (10, 11):
        return f"+{default_country_code}{digits}"

    if len(digits) >= 11:
        return f"+{digits}"

    return None


def classify_phone(raw_phone: str | None, default_country_code: str = "55") -> tuple[str | None, str]:
    """
    Retorna (telefone_e164, tipo) onde tipo e MOBILE, LANDLINE, INVALID ou UNKNOWN.
    """
    e164 = normalize_phone(raw_phone, default_country_code)
    if e164 is None:
        return None, INVALID

    if default_country_code != "55" or not e164.startswith("+55"):
        return e164, UNKNOWN

    national = e164[3:]
    if len(national) not in (10, 11):
        return e164, INVALID

    ddd, local = int(national[:2]), national[2:]
    if ddd not in _VALID_DDDS:
        return e164, INVALID
    if len(local) == 9 and local[0] == "9":
        return e164, MOBILE
    if len(local) == 8 and local[0] in "2345":
        return e164, LANDLINE
    return e164, INVALID


def is_whatsapp_candidate(raw_phone: str | None, default_country_code: str = "55") -> bool:
    """True para celulares brasileiros validos (ou numeros de fora, nao classificaveis)."""
    _, kind = classify_phone(raw_phone, default_country_code)
    return kind in (MOBILE, UNKNOWN)


def mask_phone(phone: str) -> str:
    return phone[:5] + "****" + phone[-2:] if len(phone) > 7 else "****"
