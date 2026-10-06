"""
main.py

Ponto de entrada do prospector. Fluxo padrao (descoberta -> score -> demo
-> hospedagem opcional -> mensagem -> CRM -> envio):

    python main.py --cidade "Curitiba PR" --negocio "restaurantes" --max-leads 20

Cada mensagem pede a sua aprovacao antes de sair (use --sem-aprovacao para
desativar). Comandos utilitarios (nao rodam o fluxo de descoberta):

    python main.py --relatorio
    python main.py --optout "+5541999998888"
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from modules.crm import CRM
from modules.demo_generator import generate_demo
from modules.discovery import discover_leads
from modules.hosting import is_configured as hosting_is_configured
from modules.approval import ask_approval
from modules.hosting import publish_demo
from modules.lead_filters import build_send_queue, filter_whatsapp_leads, make_crm_callback
from modules.lead_scoring import qualify_leads
from modules.message_generator import generate_messages_for_leads
from modules.screenshot import capture_demo_screenshot
from modules.whatsapp_sender import load_failures, send_messages
from utils.logger import get_logger

load_dotenv()
logger = get_logger("main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prospector automatico de clientes para criacao de sites."
    )
    parser.add_argument("--cidade", help='Cidade/regiao alvo, ex: "Curitiba PR"')
    parser.add_argument("--negocio", help='Tipo de negocio, ex: "restaurantes"')

    parser.add_argument("--max-leads", type=int, default=int(os.getenv("MAX_LEADS", 30)))
    parser.add_argument(
        "--daily-limit",
        type=int,
        default=int(os.getenv("DAILY_MESSAGE_LIMIT", 15)),
        help="Teto de mensagens POR DIA (somado entre execucoes).",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=os.getenv("HEADLESS", "true").lower() == "true",
    )
    parser.add_argument("--sem-envio", action="store_true", help="Nao envia WhatsApp, so gera leads/demos/mensagens.")
    parser.add_argument("--min-score", type=int, default=int(os.getenv("MIN_LEAD_SCORE", 40)))
    parser.add_argument("--sem-demo", action="store_true", help="Nao gera landing pages de demonstracao.")
    parser.add_argument(
        "--sem-hospedagem",
        action="store_true",
        help="Nao publica as demos no GitHub Pages, mesmo se configurado no .env.",
    )
    parser.add_argument(
        "--screenshot",
        action="store_true",
        default=os.getenv("SEND_SCREENSHOT", "false").lower() == "true",
        help="Captura um print de cada demo e envia como imagem (em vez de texto puro).",
    )
    parser.add_argument(
        "--warmup",
        action="store_true",
        default=os.getenv("WARMUP_ENABLED", "false").lower() == "true",
        help="Ativa rampa de aquecimento do numero (limite diario cresce aos poucos).",
    )
    parser.add_argument(
        "--sem-aprovacao",
        action="store_true",
        help="Envia sem pedir aprovacao manual de cada mensagem (nao recomendado).",
    )
    parser.add_argument(
        "--incluir-fixos",
        action="store_true",
        help="Mantem leads com telefone fixo (o WhatsApp nao os alcanca; util para ligar).",
    )
    parser.add_argument(
        "--retry-falhas",
        action="store_true",
        help="Prioriza reenviar para leads que falharam em execucoes anteriores.",
    )
    parser.add_argument("--output-dir", default=os.getenv("DEMO_OUTPUT_DIR", "demos"))
    parser.add_argument("--crm", default=os.getenv("CRM_DB", "prospector.db"))
    parser.add_argument("--leads-json", default="leads.json")
    parser.add_argument("--leads-com-mensagens-json", default="leads_com_mensagens.json")

    parser.add_argument("--relatorio", action="store_true", help="Mostra o funil de leads do CRM e encerra.")
    parser.add_argument("--optout", metavar="TELEFONE", help="Marca um telefone como 'nao contatar' e encerra.")

    return parser.parse_args()


def print_report(crm: CRM) -> None:
    report = crm.funnel_report()
    print("\n=== Relatorio do funil de leads ===")
    print(f"Total de leads no CRM : {report['total_leads']}")
    print(f"Score medio           : {report['score_medio']}")
    print(f"Maior score           : {report['maior_score']}")
    print("\nPor status:")
    for status, total in sorted(report["por_status"].items(), key=lambda x: -x[1]):
        print(f"  {status:<15} {total}")
    print("\nTop 5 leads por score:")
    for lead in report["top_leads"]:
        demo = lead.get("demo_public_url") or "(sem link publico)"
        print(f"  [{lead['lead_score']:>3}] {lead['nome']} | status={lead['status']} | demo={demo}")
    print()


def run_pipeline(args: argparse.Namespace, crm: CRM) -> int:
    if not args.cidade or not args.negocio:
        logger.error("--cidade e --negocio sao obrigatorios para rodar o pipeline de prospeccao.")
        return 1

    query = f"{args.negocio} em {args.cidade}"

    # ---------- MODULO 1: Descoberta ----------
    logger.info("[1/5] Buscando leads sem website no Google Maps...")
    leads = discover_leads(
        query=query,
        max_results=args.max_leads,
        output_path=args.leads_json,
        headless=args.headless,
        language=os.getenv("GMAPS_LANGUAGE", "pt-BR"),
    )
    if not leads:
        logger.warning("Nenhum lead sem website encontrado. Encerrando.")
        return 0

    # Filtro de celular: fixo/0800/invalido nao recebem WhatsApp, entao saem aqui,
    # ANTES de gastar demo, hospedagem e chamadas da Groq.
    cc = os.getenv("WHATSAPP_COUNTRY_CODE", "55")
    leads, phone_stats = filter_whatsapp_leads(leads, cc, include_landlines=args.incluir_fixos)
    logger.info(
        "Telefones: %d celular(es), %d fixo(s), %d invalido(s), %d sem telefone.",
        phone_stats["celular"], phone_stats["fixo"], phone_stats["invalido"], phone_stats["sem_telefone"],
    )
    if not leads:
        logger.warning("Nenhum lead com celular valido. Encerrando.")
        return 0

    # Fallback: se o Maps nao trouxe categoria, usa o termo de busca.
    for lead in leads:
        if not lead.get("categoria"):
            lead["categoria"] = args.negocio

    # ---------- Score / qualificacao ----------
    leads = qualify_leads(leads, args.min_score)
    logger.info("[2/5] Leads aprovados pelo score >= %d: %d", args.min_score, len(leads))
    if not leads:
        return 0

    # ---------- Demo + hospedagem + screenshot ----------
    if not args.sem_demo:
        logger.info("[3/5] Gerando landing pages de demonstracao...")
        pode_hospedar = hosting_is_configured() and not args.sem_hospedagem
        if not pode_hospedar and not args.sem_hospedagem:
            logger.info(
                "Publicacao automatica desativada (GITHUB_TOKEN/GITHUB_REPO nao configurados "
                "no .env) - as demos ficam disponiveis so localmente."
            )
        for lead in leads:
            lead["demo_path"] = generate_demo(lead, args.output_dir)
            slug = os.path.basename(os.path.dirname(lead["demo_path"]))

            if pode_hospedar:
                url = publish_demo(lead["demo_path"], slug)
                if url:
                    lead["demo_public_url"] = url

            if args.screenshot:
                lead["demo_screenshot"] = capture_demo_screenshot(lead["demo_path"])
    else:
        logger.info("[3/5] Geracao de demo pulada (--sem-demo).")

    # ---------- MODULO 2: Mensagens ----------
    logger.info("[4/5] Gerando mensagens personalizadas com a API da Groq...")
    try:
        leads = generate_messages_for_leads(leads, args.leads_com_mensagens_json)
    except RuntimeError as exc:
        logger.error("Falha de configuracao no modulo de mensagens: %s", exc)
        return 1
    if not leads:
        logger.warning("Nenhuma mensagem foi gerada. Encerrando antes do envio.")
        return 0

    # ---------- CRM ----------
    for lead in leads:
        lead_id = crm.upsert_lead(lead)
        lead["crm_id"] = lead_id
        crm.event(lead_id, "lead_qualificado", f"score={lead.get('lead_score')}")
        if lead.get("demo_path"):
            crm.event(lead_id, "demo_gerada", lead["demo_path"])
        if lead.get("demo_public_url"):
            crm.set_demo_public_url(lead_id, lead["demo_public_url"])

    if args.sem_envio:
        logger.info("[5/5] Envio pulado (--sem-envio).")
        return 0

    # ---------- MODULO 3: Envio ----------
    aprovar = None if args.sem_aprovacao else ask_approval
    if aprovar and not sys.stdin.isatty():
        logger.error(
            "A aprovacao manual precisa de um terminal interativo. "
            "Rode no terminal ou use --sem-aprovacao."
        )
        return 1

    failures = load_failures()
    fila = build_send_queue(leads, crm, failures=failures, retry_failures=args.retry_falhas)
    logger.info("[5/5] Enviando via WhatsApp Web (%d na fila, aprovacao manual: %s)...",
                len(fila), "nao" if args.sem_aprovacao else "sim")
    resumo = send_messages(
        fila,
        daily_limit=args.daily_limit,
        min_delay_seconds=int(os.getenv("MIN_DELAY_SECONDS", 20)),
        max_delay_seconds=int(os.getenv("MAX_DELAY_SECONDS", 40)),
        wait_time_seconds=int(os.getenv("WHATSAPP_WAIT_TIME", 25)),
        default_country_code=cc,
        retry_failures_first=args.retry_falhas,
        warmup_enabled=args.warmup,
        is_optout=crm.is_optout,
        approve=aprovar,
        on_result=make_crm_callback(crm),
    )
    logger.info("Resumo final do envio: %s", resumo)
    return 0


def main() -> int:
    args = parse_args()
    crm = CRM(args.crm, os.getenv("WHATSAPP_COUNTRY_CODE", "55"))

    try:
        if args.relatorio:
            print_report(crm)
            return 0

        if args.optout:
            try:
                e164 = crm.mark_optout(args.optout)
            except ValueError as exc:
                logger.error("%s", exc)
                return 1
            logger.info("Telefone %s marcado como nao-contatar (vale para qualquer formato).", e164)
            return 0

        return run_pipeline(args, crm)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha critica na execucao: %s", exc)
        return 1
    finally:
        crm.close()


if __name__ == "__main__":
    sys.exit(main())
