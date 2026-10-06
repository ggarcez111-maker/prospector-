"""Testes para modules/whatsapp_sender.send_messages (sem abrir navegador)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import whatsapp_sender as ws
from modules.approval import ApprovalAbort


def _leads(n, prefix="4199999000"):
    return [{"nome": f"L{i}", "telefone": f"{prefix}{i}", "mensagem": f"oi {i}"} for i in range(1, n + 1)]


def _run(tmp_path, leads, monkeypatch, enviados=None, **kwargs):
    """Executa send_messages com arquivos isolados e _send_one falso."""
    sent = []

    def fake_send(lead, telefone, mensagem, wait):
        sent.append((lead["nome"], telefone, mensagem))

    monkeypatch.setattr(ws, "_send_one", fake_send)
    monkeypatch.setattr(ws.time, "sleep", lambda s: None)
    params = dict(
        min_delay_seconds=0, max_delay_seconds=0,
        tracking_path=str(tmp_path / "enviados.json"),
        failures_path=str(tmp_path / "falhas.json"),
        warmup_state_path=str(tmp_path / "warmup.json"),
        daily_count_path=str(tmp_path / "diario.json"),
    )
    params.update(kwargs)
    resumo = ws.send_messages(leads, **params)
    return resumo, sent


def test_limite_e_diario_e_somado_entre_execucoes(tmp_path, monkeypatch):
    r1, sent1 = _run(tmp_path, _leads(5), monkeypatch, daily_limit=3)
    assert r1["enviados"] == 3 and len(sent1) == 3

    # Segunda execucao no mesmo dia, leads NOVOS: o limite do dia ja foi usado.
    r2, sent2 = _run(tmp_path, _leads(5, prefix="4198888000"), monkeypatch, daily_limit=3)
    assert r2["enviados"] == 0 and sent2 == []


def test_limite_restante_conta_o_que_ja_foi_enviado_hoje(tmp_path, monkeypatch):
    _run(tmp_path, _leads(2), monkeypatch, daily_limit=3)
    r2, sent2 = _run(tmp_path, _leads(5, prefix="4198888000"), monkeypatch, daily_limit=3)
    assert r2["enviados"] == 1


def test_retry_prioriza_quem_falhou_mesmo_com_telefone_em_formato_cru(tmp_path, monkeypatch):
    leads = [
        {"nome": "A", "telefone": "(41) 99999-0001", "mensagem": "a"},
        {"nome": "B", "telefone": "(41) 99999-8888", "mensagem": "b"},
    ]
    (tmp_path / "falhas.json").write_text(json.dumps({"+5541999998888": {"nome": "B"}}))
    _, sent = _run(tmp_path, leads, monkeypatch, daily_limit=10, retry_failures_first=True)
    assert [s[0] for s in sent] == ["B", "A"]


def test_ordenacao_com_falhas_funciona_diretamente():
    leads = [{"telefone": "(41) 3333-4444"}, {"telefone": "(41) 99999-8888"}]
    out = ws._order_with_failures_first(leads, {"+5541999998888": {}}, True)
    assert out[0]["telefone"] == "(41) 99999-8888"


def test_aprovacao_recusada_nao_envia_e_notifica(tmp_path, monkeypatch):
    eventos = []
    resumo, sent = _run(
        tmp_path, _leads(2), monkeypatch, daily_limit=10,
        approve=lambda lead, msg: None if lead["nome"] == "L1" else msg,
        on_result=lambda lead, res, det: eventos.append((lead["nome"], res)),
    )
    assert [s[0] for s in sent] == ["L2"]
    assert resumo["recusados"] == 1 and resumo["enviados"] == 1
    assert ("L1", "recusado") in eventos and ("L2", "enviado") in eventos


def test_aprovacao_pode_editar_a_mensagem(tmp_path, monkeypatch):
    _, sent = _run(tmp_path, _leads(1), monkeypatch, daily_limit=10, approve=lambda lead, msg: "texto novo")
    assert sent[0][2] == "texto novo"


def test_aprovacao_abort_interrompe_o_resto(tmp_path, monkeypatch):
    def approve(lead, msg):
        if lead["nome"] == "L2":
            raise ApprovalAbort()
        return msg

    resumo, sent = _run(tmp_path, _leads(4), monkeypatch, daily_limit=10, approve=approve)
    assert [s[0] for s in sent] == ["L1"]


def test_lead_recusado_nao_conta_no_limite_diario(tmp_path, monkeypatch):
    resumo, sent = _run(
        tmp_path, _leads(3), monkeypatch, daily_limit=2,
        approve=lambda lead, msg: None if lead["nome"] == "L1" else msg,
    )
    assert [s[0] for s in sent] == ["L2", "L3"]


def test_optout_e_respeitado(tmp_path, monkeypatch):
    resumo, sent = _run(tmp_path, _leads(2), monkeypatch, daily_limit=10, is_optout=lambda tel: tel.endswith("1"))
    assert resumo["optout"] == 1
    assert [s[0] for s in sent] == ["L2"]


def test_falha_de_envio_e_registrada_com_chave_e164_e_notificada(tmp_path, monkeypatch):
    def boom(lead, telefone, mensagem, wait):
        raise RuntimeError("sem internet")

    monkeypatch.setattr(ws, "_send_one", boom)
    monkeypatch.setattr(ws.time, "sleep", lambda s: None)
    eventos = []
    resumo = ws.send_messages(
        [{"nome": "X", "telefone": "(41) 99999-8888", "mensagem": "oi"}],
        min_delay_seconds=0, max_delay_seconds=0,
        tracking_path=str(tmp_path / "e.json"), failures_path=str(tmp_path / "f.json"),
        warmup_state_path=str(tmp_path / "w.json"), daily_count_path=str(tmp_path / "d.json"),
        on_result=lambda lead, res, det: eventos.append((res, det)),
    )
    assert resumo["erros"] == 1
    assert "+5541999998888" in json.loads((tmp_path / "f.json").read_text())
    assert eventos == [("falha", "sem internet")]


def test_intervalo_desconta_o_tempo_gasto_na_aprovacao(tmp_path, monkeypatch):
    sleeps = []
    clock = {"t": 1000.0}
    monkeypatch.setattr(ws.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(ws.random, "uniform", lambda a, b: 30.0)

    def approve(lead, msg):
        clock["t"] += 100  # humano demorou 100s para aprovar
        return msg

    monkeypatch.setattr(ws, "_send_one", lambda *a, **k: None)
    monkeypatch.setattr(ws.time, "sleep", lambda s: sleeps.append(s))
    ws.send_messages(
        _leads(2), daily_limit=10, approve=approve,
        tracking_path=str(tmp_path / "e.json"), failures_path=str(tmp_path / "f.json"),
        warmup_state_path=str(tmp_path / "w.json"), daily_count_path=str(tmp_path / "d.json"),
    )
    assert sleeps == []  # os 100s da aprovacao ja cobriram o intervalo de 30s


def test_intervalo_normal_sem_aprovacao(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(ws.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(ws.random, "uniform", lambda a, b: 30.0)
    monkeypatch.setattr(ws, "_send_one", lambda *a, **k: None)
    monkeypatch.setattr(ws.time, "sleep", lambda s: sleeps.append(s))
    ws.send_messages(
        _leads(2), daily_limit=10,
        tracking_path=str(tmp_path / "e.json"), failures_path=str(tmp_path / "f.json"),
        warmup_state_path=str(tmp_path / "w.json"), daily_count_path=str(tmp_path / "d.json"),
    )
    assert sleeps == [30.0]  # so entre o 1o e o 2o envio; nunca antes do 1o
