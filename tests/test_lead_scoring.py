"""Testes para modules/lead_scoring.score_lead / qualify_leads."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.lead_scoring import qualify_leads, score_lead


def test_lead_vazio_pontua_so_pela_ausencia_de_site():
    # Um dict vazio nao tem a chave "website", entao conta como "sem site".
    score, reasons = score_lead({})
    assert score == 30
    assert reasons == ["sem site"]


def test_lead_com_site_e_nenhum_outro_dado_tem_score_zero():
    score, reasons = score_lead({"website": "https://exemplo.com"})
    assert score == 0
    assert reasons == []


def test_lead_sem_site_soma_pontos_base():
    score, reasons = score_lead({"website": None})
    assert score >= 30
    assert "sem site" in reasons


def test_lead_com_site_nao_ganha_pontos_de_sem_site():
    score, _ = score_lead({"website": "https://exemplo.com"})
    score_sem_site, _ = score_lead({"website": None})
    assert score < score_sem_site


def test_lead_completo_e_categoria_de_alto_potencial_atinge_score_alto():
    lead = {
        "website": None,
        "telefone": "41999998888",
        "numero_avaliacoes": 150,
        "nota": 4.8,
        "categoria": "Restaurante",
        "endereco": "Rua Exemplo, 123",
    }
    score, reasons = score_lead(lead)
    assert score == 90  # 30+20+15+10+10+5
    assert "muitas avaliações" in reasons
    assert "nota alta" in reasons
    assert "categoria com potencial para presença online" in reasons


def test_score_nunca_ultrapassa_100():
    lead = {
        "website": None,
        "telefone": "41999998888",
        "numero_avaliacoes": 500,
        "nota": 5.0,
        "categoria": "clínica odontológica",
        "endereco": "Rua Exemplo, 123",
    }
    score, _ = score_lead(lead)
    assert score <= 100


def test_nota_invalida_nao_quebra_o_calculo():
    score, _ = score_lead({"nota": "sem avaliacoes"})
    assert isinstance(score, int)


def test_qualify_leads_filtra_por_score_minimo_e_ordena_desc():
    leads = [
        {"nome": "A", "website": "https://a.com"},  # score baixo (tem site)
        {"nome": "B", "website": None, "telefone": "41999998888", "numero_avaliacoes": 200, "nota": 4.9},
        {"nome": "C", "website": None, "telefone": "41999998888"},
    ]
    qualified = qualify_leads(leads, minimum_score=40)
    nomes = [lead["nome"] for lead in qualified]
    assert "A" not in nomes
    assert nomes[0] == "B"  # maior score primeiro
    assert qualified[0]["lead_score"] >= qualified[-1]["lead_score"]
