"""Testes para modules/lead_filters.py (filtro de celular e fila de envio)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.crm import CRM, STATUS_CONTATADO, STATUS_DESCARTADO
from modules.lead_filters import build_send_queue, filter_whatsapp_leads, make_crm_callback


LEADS = [
    {"nome": "Cel", "telefone": "(41) 99999-8888"},
    {"nome": "Fixo", "telefone": "(41) 3333-4444"},
    {"nome": "0800", "telefone": "0800 123 4567"},
    {"nome": "Sem", "telefone": None},
    {"nome": "Vazio", "telefone": "   "},
]


def test_filtro_mantem_so_celular_e_grava_e164():
    kept, stats = filter_whatsapp_leads(LEADS)
    assert [l["nome"] for l in kept] == ["Cel"]
    assert kept[0]["telefone_e164"] == "+5541999998888"
    assert stats == {"celular": 1, "fixo": 1, "invalido": 1, "sem_telefone": 2}


def test_filtro_pode_manter_fixos():
    kept, _ = filter_whatsapp_leads(LEADS, include_landlines=True)
    assert [l["nome"] for l in kept] == ["Cel", "Fixo"]


def test_fila_ignora_leads_ja_encerrados_no_crm(tmp_path):
    crm = CRM(str(tmp_path / "t.db"))
    a = {"nome": "A", "link_perfil": "https://maps/a", "telefone": "41999990001", "telefone_e164": "+5541999990001"}
    b = {"nome": "B", "link_perfil": "https://maps/b", "telefone": "41999990002", "telefone_e164": "+5541999990002"}
    a["crm_id"] = crm.upsert_lead(a)
    b["crm_id"] = crm.upsert_lead(b)
    crm.update_status(a["crm_id"], STATUS_CONTATADO)

    fila = build_send_queue([a, b], crm)
    assert [l["nome"] for l in fila] == ["B"]
    crm.close()


def test_fila_com_retry_traz_do_crm_quem_falhou_e_poe_na_frente(tmp_path):
    crm = CRM(str(tmp_path / "t.db"))
    falhou = {
        "nome": "Falhou", "link_perfil": "https://maps/f", "telefone": "(41) 99999-0003",
        "telefone_e164": "+5541999990003", "mensagem": "oi", "demo_path": "demos/f/index.html",
    }
    falhou["crm_id"] = crm.upsert_lead(falhou)
    novo = {"nome": "Novo", "link_perfil": "https://maps/n", "telefone": "41999990004", "telefone_e164": "+5541999990004"}
    novo["crm_id"] = crm.upsert_lead(novo)

    # "Falhou" NAO foi redescoberto agora; so existe no CRM + falhas.json.
    fila = build_send_queue([novo], crm, failures={"+5541999990003": {}}, retry_failures=True)
    assert [l["nome"] for l in fila] == ["Falhou", "Novo"]
    assert fila[0]["demo_path"] == "demos/f/index.html"
    crm.close()


def test_fila_sem_duplicar_quando_falhou_e_foi_redescoberto(tmp_path):
    crm = CRM(str(tmp_path / "t.db"))
    lead = {"nome": "X", "link_perfil": "https://maps/x", "telefone": "41999990005",
            "telefone_e164": "+5541999990005", "mensagem": "oi"}
    lead["crm_id"] = crm.upsert_lead(lead)
    fila = build_send_queue([lead], crm, failures={"+5541999990005": {}}, retry_failures=True)
    assert len(fila) == 1
    crm.close()


def test_callback_atualiza_status_no_crm(tmp_path):
    crm = CRM(str(tmp_path / "t.db"))
    lead = {"nome": "A", "link_perfil": "https://maps/a", "mensagem": "oi"}
    lead["crm_id"] = crm.upsert_lead(lead)
    cb = make_crm_callback(crm)

    cb(lead, "falha", "timeout")
    assert crm.get_lead(lead["crm_id"])["status"] == "novo"  # falha nao encerra o lead

    cb({**lead, "mensagem_enviada": "texto editado"}, "enviado", "")
    assert crm.get_lead(lead["crm_id"])["status"] == STATUS_CONTATADO
    eventos = [e["details"] for e in crm.conn.execute("SELECT * FROM events WHERE event='mensagem_enviada'")]
    assert eventos == ["texto editado"]

    lead2 = {"nome": "B", "link_perfil": "https://maps/b"}
    lead2["crm_id"] = crm.upsert_lead(lead2)
    cb(lead2, "recusado", "pulado")
    assert crm.get_lead(lead2["crm_id"])["status"] == STATUS_DESCARTADO
    crm.close()
