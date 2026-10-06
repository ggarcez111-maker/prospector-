"""
modules/whatsapp_sender.py

MODULO 3 - Envio das mensagens via WhatsApp Web usando pywhatkit (gratuito).

Requisitos do pywhatkit:
- WhatsApp Web precisa estar logado no navegador padrao da maquina.
- A maquina precisa ter interface grafica (pywhatkit controla o navegador
  via pyautogui) - nao funciona em servidores 100% headless/sem tela.

Implementa:
- "Drip mode": uma mensagem por vez, com intervalo aleatorio entre envios.
  O tempo gasto na aprovacao manual conta como parte do intervalo.
- Limite DIARIO real: os envios do dia sao somados entre execucoes
  (envios_diarios.json), entao rodar o script 3 vezes nao triplica o limite.
  Com warm-up opcional (limite comeca baixo e cresce a cada dia de uso).
- Aprovacao manual opcional (`approve`): voce ve cada mensagem antes de sair.
- Fila de reenvio: falhas ficam em falhas.json (chave = telefone E.164) e
  podem ser priorizadas (`retry_failures_first=True`).
- Opt-out (via CRM) checado antes de cada envio.
- Envio de imagem: se o lead tiver `demo_screenshot`, envia a imagem com a
  mensagem como legenda.
- Callback `on_result` para o CRM registrar contatado/falha/recusado.
- Log de cada tentativa (numero mascarado) em envios.log.
"""

from __future__ import annotations

import json
import random
import time
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from modules.approval import ApprovalAbort
from modules.phone import mask_phone as _mask
from modules.phone import normalize_phone  # noqa: F401  (reexportado para compatibilidade)
from utils.logger import get_logger

logger = get_logger(__name__)

_ENVIADOS_TRACKING_FILE = "enviados.json"
_FALHAS_TRACKING_FILE = "falhas.json"
_WARMUP_STATE_FILE = "warmup_state.json"
_DAILY_COUNT_FILE = "envios_diarios.json"

# Rampa de warm-up: limite maximo de mensagens por dia de uso do numero
# (dia 1 = primeira vez que o script envia algo). Depois do ultimo valor,
# mantem o daily_limit configurado normalmente.
_WARMUP_RAMP = [5, 8, 10, 12]

RESULT_ENVIADO = "enviado"
RESULT_FALHA = "falha"
RESULT_RECUSADO = "recusado"


# ---------- persistencia ----------

def _load_json_set(path: str, key: str) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text(encoding="utf-8")).get(key, []))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Nao foi possivel ler '%s' (%s). Iniciando lista vazia.", path, exc)
        return set()


def _persist_json_set(path: str, key: str, values: set[str]) -> None:
    Path(path).write_text(
        json.dumps({key: sorted(values)}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_failures(path: str = _FALHAS_TRACKING_FILE) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


_load_failures = load_failures  # nome antigo


def _persist_failures(path: str, failures: dict) -> None:
    Path(path).write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_daily_counts(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def sent_today(path: str = _DAILY_COUNT_FILE) -> int:
    return int(_load_daily_counts(path).get(date.today().isoformat(), 0))


def _register_sent_today(path: str) -> None:
    counts = _load_daily_counts(path)
    today = date.today().isoformat()
    counts[today] = int(counts.get(today, 0)) + 1
    # mantem so os ultimos 30 dias, para o arquivo nao crescer para sempre
    counts = dict(sorted(counts.items())[-30:])
    Path(path).write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- limite / ordenacao ----------

def _effective_daily_limit(configured_limit: int, warmup_enabled: bool, state_path: str) -> int:
    """
    Se warm-up estiver ativo, calcula o limite do dia com base em ha
    quantos dias o script vem sendo usado para enviar mensagens
    (contando dias de calendario distintos, nao execucoes).
    """
    if not warmup_enabled:
        return configured_limit

    today = date.today().isoformat()
    state_file = Path(state_path)
    dias_usados: list[str] = []
    if state_file.exists():
        try:
            dias_usados = json.loads(state_file.read_text(encoding="utf-8")).get("dias", [])
        except (json.JSONDecodeError, OSError):
            dias_usados = []

    if today not in dias_usados:
        dias_usados.append(today)
        state_file.write_text(json.dumps({"dias": dias_usados}, ensure_ascii=False, indent=2), encoding="utf-8")

    dia_numero = len(dias_usados)  # 1-indexado
    if dia_numero <= len(_WARMUP_RAMP):
        limite_do_dia = _WARMUP_RAMP[dia_numero - 1]
        logger.info(
            "Warm-up ativo: dia %d de uso, limite ajustado para %d (configurado: %d).",
            dia_numero,
            limite_do_dia,
            configured_limit,
        )
        return min(limite_do_dia, configured_limit)

    return configured_limit


def _lead_phone(lead: dict, default_country_code: str) -> str | None:
    return lead.get("telefone_e164") or normalize_phone(lead.get("telefone"), default_country_code)


def _order_with_failures_first(
    leads: list[dict],
    failures: dict,
    retry_first: bool,
    default_country_code: str = "55",
) -> list[dict]:
    """
    Coloca primeiro quem falhou antes. As falhas sao gravadas com o telefone
    normalizado (E.164), entao a comparacao tem que usar o mesmo formato.
    """
    if not retry_first or not failures:
        return leads

    def _key(lead: dict) -> int:
        return 0 if _lead_phone(lead, default_country_code) in failures else 1

    return sorted(leads, key=_key)  # sorted e estavel: preserva a ordem por score


# ---------- envio ----------

def _send_one(
    lead: dict,
    telefone: str,
    mensagem: str,
    wait_time_seconds: int,
) -> None:
    # Import tardio: pywhatkit/pyautogui exigem tela ja no import, o que
    # quebraria testes e comandos (--relatorio, --optout) em maquinas sem GUI.
    import pywhatkit

    screenshot = lead.get("demo_screenshot")
    if screenshot and Path(screenshot).exists():
        pywhatkit.sendwhats_image(
            receiver=telefone,
            img_path=screenshot,
            caption=mensagem,
            wait_time=wait_time_seconds,
            tab_close=True,
            close_time=3,
        )
    else:
        pywhatkit.sendwhatmsg_instantly(
            phone_no=telefone,
            message=mensagem,
            wait_time=wait_time_seconds,
            tab_close=True,
            close_time=3,
        )


def send_messages(
    leads_with_messages: list[dict],
    daily_limit: int = 15,
    min_delay_seconds: int = 20,
    max_delay_seconds: int = 40,
    wait_time_seconds: int = 25,
    default_country_code: str = "55",
    tracking_path: str = _ENVIADOS_TRACKING_FILE,
    failures_path: str = _FALHAS_TRACKING_FILE,
    warmup_state_path: str = _WARMUP_STATE_FILE,
    daily_count_path: str = _DAILY_COUNT_FILE,
    skip_already_sent: bool = True,
    retry_failures_first: bool = False,
    warmup_enabled: bool = False,
    is_optout: Optional[Callable[[str], bool]] = None,
    approve: Optional[Callable[[dict, str], Optional[str]]] = None,
    on_result: Optional[Callable[[dict, str, str], None]] = None,
) -> dict:
    """
    Envia as mensagens em fila (drip mode), respeitando o limite DIARIO
    (somado entre execucoes, com warm-up opcional) e o intervalo entre envios.

    `is_optout`: recebe o telefone E.164 e retorna True se for "nao contatar".
    `approve`: recebe (lead, mensagem) e retorna o texto a enviar (possivelmente
        editado) ou None para pular. Pode levantar ApprovalAbort para parar tudo.
    `on_result`: recebe (lead, resultado, detalhe) com resultado em
        {"enviado", "falha", "recusado"}; usado para atualizar o CRM.
    """
    resumo = {"enviados": 0, "erros": 0, "pulados": 0, "optout": 0, "recusados": 0}

    if not leads_with_messages:
        logger.warning("Nenhum lead com mensagem recebido para envio.")
        return resumo

    def _notify(lead: dict, resultado: str, detalhe: str = "") -> None:
        if on_result:
            try:
                on_result(lead, resultado, detalhe)
            except Exception as exc:  # noqa: BLE001 - CRM nunca deve derrubar o envio
                logger.warning("Falha ao registrar resultado '%s' no CRM: %s", resultado, exc)

    already_sent = _load_json_set(tracking_path, "enviados") if skip_already_sent else set()
    failures = load_failures(failures_path)
    limite_efetivo = _effective_daily_limit(daily_limit, warmup_enabled, warmup_state_path)
    ja_enviados_hoje = sent_today(daily_count_path)
    restante = limite_efetivo - ja_enviados_hoje

    if restante <= 0:
        logger.info(
            "Limite diario de %d mensagens ja atingido hoje (%d enviadas). Nada a enviar.",
            limite_efetivo,
            ja_enviados_hoje,
        )
        return resumo
    logger.info(
        "Limite do dia: %d | ja enviadas hoje: %d | restante nesta execucao: %d",
        limite_efetivo,
        ja_enviados_hoje,
        restante,
    )

    fila = _order_with_failures_first(leads_with_messages, failures, retry_failures_first, default_country_code)
    enviados_nesta_execucao = 0
    ultimo_envio_ts: float | None = None

    for i, lead in enumerate(fila):
        if enviados_nesta_execucao >= restante:
            logger.info("Limite diario atingido. Interrompendo envio.")
            break

        nome = lead.get("nome", "negocio sem nome")
        mensagem = lead.get("mensagem")
        telefone_normalizado = _lead_phone(lead, default_country_code)

        if not mensagem:
            logger.warning("Lead '%s' sem mensagem gerada - pulando.", nome)
            resumo["pulados"] += 1
            continue

        if not telefone_normalizado:
            logger.warning("Lead '%s' sem telefone valido - pulando.", nome)
            resumo["pulados"] += 1
            continue

        telefone_mascarado = _mask(telefone_normalizado)

        if is_optout and is_optout(telefone_normalizado):
            logger.info("Lead '%s' (%s) marcado como nao-contatar - pulando.", nome, telefone_mascarado)
            resumo["optout"] += 1
            continue

        if telefone_normalizado in already_sent:
            logger.info("Mensagem para '%s' (%s) ja enviada anteriormente - pulando.", nome, telefone_mascarado)
            resumo["pulados"] += 1
            continue

        # ---------- aprovacao manual ----------
        if approve is not None:
            try:
                aprovada = approve(lead, mensagem)
            except ApprovalAbort:
                logger.info("Envio interrompido pelo usuario (q).")
                break
            if aprovada is None:
                logger.info("Lead '%s' (%s) recusado na aprovacao manual.", nome, telefone_mascarado)
                resumo["recusados"] += 1
                _notify(lead, RESULT_RECUSADO, "pulado na aprovacao manual")
                continue
            mensagem = aprovada

        # ---------- intervalo (drip), descontando o tempo da aprovacao ----------
        if ultimo_envio_ts is not None:
            intervalo = random.uniform(min_delay_seconds, max_delay_seconds)
            falta = intervalo - (time.monotonic() - ultimo_envio_ts)
            if falta > 0:
                logger.info("Aguardando %.1fs antes do proximo envio (drip mode)...", falta)
                time.sleep(falta)

        try:
            _send_one(lead, telefone_normalizado, mensagem, wait_time_seconds)
        except Exception as exc:  # noqa: BLE001 - pywhatkit/pyautogui podem levantar varios tipos
            logger.error(
                "ENVIO FALHOU | negocio='%s' | telefone=%s | status=erro | detalhe=%s",
                nome,
                telefone_mascarado,
                exc,
            )
            resumo["erros"] += 1
            failures[telefone_normalizado] = {
                "nome": nome,
                "detalhe": str(exc),
                "quando": date.today().isoformat(),
            }
            _persist_failures(failures_path, failures)
            _notify(lead, RESULT_FALHA, str(exc))
            ultimo_envio_ts = time.monotonic()
            continue

        logger.info("ENVIO OK | negocio='%s' | telefone=%s | status=sucesso", nome, telefone_mascarado)
        resumo["enviados"] += 1
        enviados_nesta_execucao += 1
        ultimo_envio_ts = time.monotonic()
        already_sent.add(telefone_normalizado)
        _persist_json_set(tracking_path, "enviados", already_sent)
        _register_sent_today(daily_count_path)
        if telefone_normalizado in failures:
            failures.pop(telefone_normalizado, None)
            _persist_failures(failures_path, failures)
        lead["mensagem_enviada"] = mensagem
        _notify(lead, RESULT_ENVIADO, "")

    logger.info(
        "Envio finalizado. Sucessos=%d | Erros=%d | Pulados=%d | Opt-out=%d | Recusados=%d",
        resumo["enviados"],
        resumo["erros"],
        resumo["pulados"],
        resumo["optout"],
        resumo["recusados"],
    )
    return resumo
