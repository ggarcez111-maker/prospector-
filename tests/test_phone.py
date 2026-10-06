"""Testes para modules/phone.py (normalizacao e classificacao celular/fixo)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.phone import INVALID, LANDLINE, MOBILE, UNKNOWN, classify_phone, is_whatsapp_candidate, normalize_phone


def test_celular_com_nono_digito_e_celular():
    assert classify_phone("(41) 99999-8888") == ("+5541999998888", MOBILE)
    assert classify_phone("+55 41 99999-8888") == ("+5541999998888", MOBILE)
    assert classify_phone("5541999998888") == ("+5541999998888", MOBILE)


def test_fixo_e_classificado_como_fixo():
    assert classify_phone("(41) 3333-4444") == ("+554133334444", LANDLINE)
    assert classify_phone("(11) 4004-1234")[1] == LANDLINE


def test_0800_e_similares_sao_invalidos():
    for numero in ("0800 123 4567", "0300 313 1234", "0500 123 4567", "0900 123 4567"):
        assert normalize_phone(numero) is None
        assert classify_phone(numero) == (None, INVALID)


def test_celular_antigo_sem_nono_digito_e_invalido():
    # 10 digitos comecando com 9/8/7/6 no numero local: nao adivinhamos o 9.
    assert classify_phone("(41) 8888-7777")[1] == INVALID


def test_ddd_inexistente_e_invalido():
    assert classify_phone("(10) 99999-8888")[1] == INVALID
    assert classify_phone("(20) 99999-8888")[1] == INVALID


def test_prefixo_de_tronco_zero_e_removido():
    assert normalize_phone("041 99999-8888") == "+5541999998888"


def test_curto_ou_vazio_e_invalido():
    assert classify_phone("5541") == (None, INVALID)
    assert classify_phone("") == (None, INVALID)
    assert classify_phone(None) == (None, INVALID)


def test_fora_do_brasil_nao_e_classificado():
    e164, kind = classify_phone("4155552671", default_country_code="1")
    assert e164 == "+14155552671"
    assert kind == UNKNOWN


def test_is_whatsapp_candidate():
    assert is_whatsapp_candidate("41999998888") is True
    assert is_whatsapp_candidate("4133334444") is False
    assert is_whatsapp_candidate("0800 123 4567") is False
