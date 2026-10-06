"""Testes para modules/crm.CRM (usa banco SQLite temporario em memoria)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.crm import STATUS_NAO_CONTATAR, STATUS_NOVO, CRM


def make_crm(tmp_path: Path) -> CRM:
    return CRM(str(tmp_path / "test.db"))


def test_upsert_lead_cria_novo_registro(tmp_path):
    crm = make_crm(tmp_path)
    lead_id = crm.upsert_lead({"nome": "Padaria X", "telefone": "41999998888", "link_perfil": "https://maps/x"})
    row = crm.get_lead(lead_id)
    assert row["nome"] == "Padaria X"
    assert row["status"] == STATUS_NOVO
    crm.close()


def test_upsert_lead_com_mesmo_link_perfil_atualiza_em_vez_de_duplicar(tmp_path):
    crm = make_crm(tmp_path)
    lead = {"nome": "Padaria X", "telefone": None, "link_perfil": "https://maps/x", "lead_score": 10}
    id1 = crm.upsert_lead(lead)

    lead["lead_score"] = 80
    id2 = crm.upsert_lead(lead)

    assert id1 == id2
    row = crm.get_lead(id1)
    assert row["lead_score"] == 80

    total = crm.conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
    assert total == 1
    crm.close()


def test_upsert_lead_sem_link_perfil_usa_combo_como_fallback(tmp_path):
    crm = make_crm(tmp_path)
    lead = {"nome": "Sem Link", "telefone": "41988887777", "endereco": "Rua A"}
    id1 = crm.upsert_lead(lead)
    id2 = crm.upsert_lead(lead)  # mesma combinacao -> mesma linha

    assert id1 == id2
    total = crm.conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
    assert total == 1
    crm.close()


def test_demo_public_url_persiste_no_upsert(tmp_path):
    crm = make_crm(tmp_path)
    lead = {"nome": "Loja Y", "link_perfil": "https://maps/y", "demo_path": "demos/loja-y/index.html"}
    lead_id = crm.upsert_lead(lead)
    row = crm.get_lead(lead_id)
    assert row["demo_url"] == "demos/loja-y/index.html"
    assert row["demo_public_url"] is None

    crm.set_demo_public_url(lead_id, "https://usuario.github.io/repo/demos/loja-y/")
    row = crm.get_lead(lead_id)
    assert row["demo_public_url"] == "https://usuario.github.io/repo/demos/loja-y/"
    crm.close()


def test_mark_optout_e_is_optout(tmp_path):
    crm = make_crm(tmp_path)
    crm.mark_optout("+5541999998888")
    assert crm.is_optout("+5541999998888") is True
    assert crm.is_optout("+5541900000000") is False
    crm.close()


def test_update_status_registra_evento(tmp_path):
    crm = make_crm(tmp_path)
    lead_id = crm.upsert_lead({"nome": "Loja Z", "link_perfil": "https://maps/z"})
    crm.update_status(lead_id, "respondeu", "cliente pediu mais detalhes")
    row = crm.get_lead(lead_id)
    assert row["status"] == "respondeu"

    eventos = crm.conn.execute("SELECT event FROM events WHERE lead_id=?", (lead_id,)).fetchall()
    assert any(e["event"] == "status:respondeu" for e in eventos)
    crm.close()


def test_funnel_report_agrega_por_status(tmp_path):
    crm = make_crm(tmp_path)
    crm.upsert_lead({"nome": "L1", "link_perfil": "https://maps/1", "lead_score": 50})
    lead_id_2 = crm.upsert_lead({"nome": "L2", "link_perfil": "https://maps/2", "lead_score": 90})
    crm.update_status(lead_id_2, "fechou")

    report = crm.funnel_report()
    assert report["total_leads"] == 2
    assert report["maior_score"] == 90
    assert report["por_status"].get("fechou") == 1
    assert report["por_status"].get(STATUS_NOVO) == 1
    crm.close()


def test_optout_vale_para_qualquer_formato_do_telefone(tmp_path):
    crm = make_crm(tmp_path)
    crm.mark_optout("(41) 99999-8888")
    assert crm.is_optout("+5541999998888") is True
    assert crm.is_optout("41999998888") is True
    assert crm.is_optout("(41) 99999-8888") is True
    assert crm.is_optout("+5541999990000") is False
    crm.close()


def test_optout_marca_lead_existente_que_tem_telefone_cru(tmp_path):
    crm = make_crm(tmp_path)
    lead_id = crm.upsert_lead({"nome": "Loja", "telefone": "(41) 99999-8888", "link_perfil": "https://maps/l"})
    crm.mark_optout("+5541999998888")
    assert crm.get_lead(lead_id)["status"] == STATUS_NAO_CONTATAR
    crm.close()


def test_optout_sobrevive_a_lead_redescoberto_com_outro_link(tmp_path):
    crm = make_crm(tmp_path)
    crm.mark_optout("+5541999998888")
    novo_id = crm.upsert_lead({"nome": "Loja", "telefone": "(41) 99999-8888", "link_perfil": "https://maps/novo"})
    assert crm.get_lead(novo_id)["status"] == STATUS_NOVO
    assert crm.is_optout("(41) 99999-8888") is True  # o numero continua bloqueado
    crm.close()


def test_optout_nao_cria_lead_fantasma(tmp_path):
    crm = make_crm(tmp_path)
    crm.mark_optout("+5541999998888")
    total = crm.conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
    assert total == 0
    crm.close()


def test_optout_com_telefone_invalido_levanta_erro(tmp_path):
    import pytest

    crm = make_crm(tmp_path)
    with pytest.raises(ValueError):
        crm.mark_optout("123")
    crm.close()


def test_migracao_de_banco_antigo_preserva_optouts(tmp_path):
    import sqlite3

    path = tmp_path / "antigo.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE leads (id INTEGER PRIMARY KEY AUTOINCREMENT, dedup_key TEXT UNIQUE,
          nome TEXT NOT NULL, telefone TEXT, endereco TEXT, nota REAL, numero_avaliacoes INTEGER,
          link_perfil TEXT, website TEXT, categoria TEXT, lead_score INTEGER DEFAULT 0,
          score_reasons TEXT, demo_url TEXT, demo_public_url TEXT, mensagem TEXT,
          status TEXT DEFAULT 'novo', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER NOT NULL,
          event TEXT NOT NULL, details TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO leads (dedup_key, nome, telefone, status)
          VALUES ('link:x', 'Antigo', '(41) 99999-8888', 'nao_contatar');
        """
    )
    old.commit()
    old.close()

    crm = CRM(str(path))
    assert crm.is_optout("+5541999998888") is True
    assert crm.get_lead(1)["telefone_e164"] == "+5541999998888"
    crm.close()


def test_get_leads_by_phones_devolve_leads_com_mensagem(tmp_path):
    crm = make_crm(tmp_path)
    crm.upsert_lead({"nome": "A", "telefone": "41999990001", "link_perfil": "https://maps/a",
                     "mensagem": "oi", "demo_path": "demos/a/index.html"})
    crm.upsert_lead({"nome": "B", "telefone": "41999990002", "link_perfil": "https://maps/b"})  # sem mensagem
    leads = crm.get_leads_by_phones(["+5541999990001", "+5541999990002"])
    assert [l["nome"] for l in leads] == ["A"]
    assert leads[0]["demo_path"] == "demos/a/index.html" and leads[0]["crm_id"]
    crm.close()
