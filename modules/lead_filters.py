"""
modules/lead_filters.py

Etapas do pipeline que decidem QUEM entra no envio. Ficam fora do main.py
(que importa Playwright, Groq etc.) para poderem ser testadas isoladamente.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from modules.crm import (
    CRM,
    STATUS_CONTATADO,
    STATUS_DESCARTADO,
    STATUS_SEM_NOVO_ENVIO,
)
from modules.phone import LANDLINE, MOBILE, UNKNOWN, classify_phone
from modules.whatsapp_sender import RESULT_ENVIADO, RESULT_FALHA, RESULT_RECUSADO


def filter_whatsapp_leads(
    leads: list[dict],
    default_country_code: str = "55",
    include_landlines: bool = False,
) -> tuple[list[dict], dict]:
    """
    Mantem so leads que o WhatsApp consegue alcancar (celular valido) e grava
    `telefone_e164` em cada um. Roda ANTES do score/demo/mensagem para nao
    gastar Groq nem GitHub com quem so tem fixo, 0800 ou numero invalido.

    Retorna (leads_mantidos, estatisticas).
    """
    kept: list[dict] = []
    stats = {"celular": 0, "fixo": 0, "invalido": 0, "sem_telefone": 0}

    for lead in leads:
        if not (lead.get("telefone") or "").strip():
            stats["sem_telefone"] += 1
            continue

        e164, kind = classify_phone(lead.get("telefone"), default_country_code)
        if kind in (MOBILE, UNKNOWN):
            stats["celular"] += 1
        elif kind == LANDLINE:
            stats["fixo"] += 1
            if not include_landlines:
                continue
        else:
            stats["invalido"] += 1
            continue

        kept.append({**lead, "telefone_e164": e164})

    return kept, stats


def build_send_queue(
    leads: list[dict],
    crm: CRM,
    failures: dict | None = None,
    retry_failures: bool = False,
) -> list[dict]:
    """
    Monta a fila final de envio:
      - tira leads que o CRM ja considera encerrados (contatado, descartado,
        opt-out, respondeu...), para nao pedir a mesma aprovacao toda execucao;
      - com `retry_failures`, traz do CRM os leads que falharam antes (mesmo
        que nao tenham sido redescobertos agora) e os coloca na frente.
    """
    fila: list[dict] = []
    vistos: set[str] = set()

    def _aceita(lead: dict) -> bool:
        crm_id = lead.get("crm_id")
        if crm_id is None:
            return True
        row = crm.get_lead(crm_id)
        return not (row and row["status"] in STATUS_SEM_NOVO_ENVIO)

    if retry_failures and failures:
        for lead in crm.get_leads_by_phones(list(failures.keys())):
            png = Path(lead["demo_path"]).with_suffix(".png") if lead.get("demo_path") else None
            if png and png.exists():
                lead["demo_screenshot"] = str(png)
            e164 = lead.get("telefone_e164")
            if e164 and e164 not in vistos and _aceita(lead):
                vistos.add(e164)
                fila.append(lead)

    for lead in leads:
        e164 = lead.get("telefone_e164")
        if e164 and e164 in vistos:
            continue
        if not _aceita(lead):
            continue
        if e164:
            vistos.add(e164)
        fila.append(lead)

    return fila


def make_crm_callback(crm: CRM) -> Callable[[dict, str, str], None]:
    """Cria o `on_result` do envio: atualiza o status do lead no CRM."""

    def _on_result(lead: dict, resultado: str, detalhe: str) -> None:
        lead_id = lead.get("crm_id")
        if not lead_id:
            return
        if resultado == RESULT_ENVIADO:
            crm.event(lead_id, "mensagem_enviada", lead.get("mensagem_enviada") or lead.get("mensagem") or "")
            crm.update_status(lead_id, STATUS_CONTATADO, "mensagem enviada pelo WhatsApp")
        elif resultado == RESULT_FALHA:
            crm.event(lead_id, "envio_falhou", (detalhe or "")[:300])
        elif resultado == RESULT_RECUSADO:
            crm.update_status(lead_id, STATUS_DESCARTADO, detalhe)

    return _on_result
