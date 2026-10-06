"""Testes para modules/whatsapp_sender.normalize_phone."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.whatsapp_sender import normalize_phone


def test_ddd_e_numero_de_11_digitos_recebe_ddi():
    assert normalize_phone("41999998888") == "+5541999998888"


def test_ddd_e_numero_de_10_digitos_recebe_ddi():
    assert normalize_phone("4133334444") == "+554133334444"


def test_numero_formatado_com_simbolos_e_normalizado():
    assert normalize_phone("(41) 99999-8888") == "+5541999998888"


def test_numero_ja_com_ddi_brasileiro_mantem_ddi():
    assert normalize_phone("5541999998888") == "+5541999998888"


def test_numero_internacional_generico_mantem_digitos():
    # 12+ digitos e que nao comeca com o DDI padrao -> mantido como esta.
    # (numeros de 10-11 digitos sao tratados como DDD+numero local, por
    # design - ver limitacao documentada no README sobre numeros nao-BR.)
    assert normalize_phone("447911123456") == "+447911123456"


def test_numero_vazio_retorna_none():
    assert normalize_phone("") is None
    assert normalize_phone(None) is None


def test_numero_curto_demais_retorna_none():
    assert normalize_phone("12345") is None


def test_default_country_code_customizado():
    # Numero local de 10 digitos (padrao americano sem DDI) com DDI customizado.
    assert normalize_phone("4155552671", default_country_code="1") == "+14155552671"


def test_numero_0800_nao_vira_telefone_valido():
    assert normalize_phone("0800 123 4567") is None
