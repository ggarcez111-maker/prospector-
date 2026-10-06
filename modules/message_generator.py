"""
modules/message_generator.py

MODULO 2 - Geracao de mensagem de abordagem personalizada usando a API
gratuita da Groq (compativel com o SDK/endpoint da OpenAI).

A chave e lida de GROQ_API_KEY (variavel de ambiente / .env).
Modelo: llama-3.3-70b-versatile
Base URL: https://api.groq.com/openai/v1
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from utils.logger import get_logger

load_dotenv()

logger = get_logger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

# Estilos rotacionados entre leads para evitar que dezenas de mensagens
# saiam com a mesma estrutura de frase (padrao repetitivo e um dos
# gatilhos de bloqueio de spam do WhatsApp).
_ESTILOS = [
    "direto e objetivo, quase telegrafico",
    "consultivo e simpatico, como quem quer ajudar",
    "casual e descontraido, como uma mensagem entre conhecidos",
]

_BASE_RULES = (
    "Voce escreve mensagens curtas de prospeccao comercial em portugues do Brasil, "
    "para serem enviadas por WhatsApp a pequenos negocios locais. "
    "Regras obrigatorias:\n"
    "- No maximo 3 linhas.\n"
    "- Escreva no estilo: {estilo}.\n"
    "- Sempre mencione o nome do negocio.\n"
    "- Diga que voce encontrou o negocio no Google e percebeu uma oportunidade de melhorar a presenca online.\n"
    "- Nao use emojis em excesso (no maximo 1).\n"
    "- Responda APENAS com o texto da mensagem, sem aspas e sem explicacoes.\n"
)

_SYSTEM_PROMPT_SEM_DEMO = _BASE_RULES + (
    "- Ofereca uma demonstracao gratuita SEM afirmar que ela ja foi enviada.\n"
    "- Termine perguntando se a pessoa quer receber o link da demonstracao."
)

_SYSTEM_PROMPT_COM_DEMO = _BASE_RULES + (
    "- A demonstracao ja existe e o link sera anexado logo apos a sua mensagem "
    "(nao invente nem escreva o link, apenas diga que esta enviando a seguir).\n"
    "- Termine convidando a pessoa a dar uma olhada na demonstracao."
)

_FALLBACK_TEMPLATES_SEM_DEMO = [
    "Olá! Vi o {nome} no Google e percebi uma oportunidade de melhorar a presença online. "
    "Posso te mostrar uma demonstração gratuita de como poderia ficar?",
    "Oi! Passei pelo perfil do {nome} no Google e notei que dá pra melhorar bastante a "
    "presença online. Topa ver uma demo gratuita?",
    "Olá, tudo bem? Encontrei o {nome} pelo Google e tenho uma ideia de site que pode ajudar "
    "a atrair mais clientes. Quer que eu te mostre?",
]

_FALLBACK_TEMPLATES_COM_DEMO = [
    "Olá! Vi o {nome} no Google e preparei uma demonstração gratuita de site — link logo abaixo.",
    "Oi! Passei pelo perfil do {nome} e já montei uma demo gratuita de como o site poderia "
    "ficar. Segue o link:",
]


def _get_client() -> OpenAI:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY nao encontrada. Defina essa variavel no arquivo .env "
            "(veja .env.example)."
        )
    return OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)


def generate_message(
    lead: dict,
    client: OpenAI | None = None,
    max_retries: int = 3,
    retry_backoff_seconds: float = 2.0,
) -> str:
    """
    Gera uma mensagem curta e personalizada para um lead, com retentativas
    em caso de rate limit / timeout / erro transitorio.
    Se todas as tentativas falharem, cai em um template local (fallback),
    garantindo que o fluxo nunca trave por causa da API.
    """
    nome_negocio = lead.get("nome", "seu negócio")
    tem_demo_publica = bool(lead.get("demo_public_url"))
    client = client or _get_client()

    estilo = random.choice(_ESTILOS)
    system_prompt = (_SYSTEM_PROMPT_COM_DEMO if tem_demo_publica else _SYSTEM_PROMPT_SEM_DEMO).format(
        estilo=estilo
    )

    user_prompt = (
        f"Nome do negocio: {nome_negocio}\n"
        f"Endereco: {lead.get('endereco') or 'nao informado'}\n"
        f"Nota no Google: {lead.get('nota') or 'sem avaliacoes'}\n"
        "Escreva a mensagem de prospeccao seguindo as regras do sistema."
    )

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=150,
                temperature=0.7,
                timeout=20,
            )
            mensagem = response.choices[0].message.content.strip().strip('"')
            if mensagem:
                logger.info("Mensagem gerada para '%s'.", nome_negocio)
                if tem_demo_publica:
                    mensagem = f"{mensagem}\n{lead['demo_public_url']}"
                return mensagem
            raise ValueError("Resposta vazia da API Groq.")

        except RateLimitError:
            wait = retry_backoff_seconds * attempt
            logger.warning(
                "Rate limit da Groq atingido (tentativa %d/%d). Aguardando %.1fs.",
                attempt,
                max_retries,
                wait,
            )
            time.sleep(wait)
        except APITimeoutError:
            logger.warning(
                "Timeout na chamada a Groq para '%s' (tentativa %d/%d).",
                nome_negocio,
                attempt,
                max_retries,
            )
            time.sleep(retry_backoff_seconds)
        except APIConnectionError as exc:
            logger.warning(
                "Erro de conexao com a Groq (tentativa %d/%d): %s",
                attempt,
                max_retries,
                exc,
            )
            time.sleep(retry_backoff_seconds)
        except APIStatusError as exc:
            # Erros 4xx/5xx retornados pela API
            logger.error(
                "Groq retornou status %s para '%s': %s",
                exc.status_code,
                nome_negocio,
                exc.message,
            )
            if 400 <= exc.status_code < 500 and exc.status_code != 429:
                # Erro do cliente (ex: payload invalido) - nao adianta retentar
                break
            time.sleep(retry_backoff_seconds * attempt)
        except Exception as exc:  # noqa: BLE001
            logger.error("Erro inesperado ao gerar mensagem para '%s': %s", nome_negocio, exc)
            break

    logger.warning(
        "Usando mensagem de fallback (template local) para '%s' apos falhas na API.",
        nome_negocio,
    )
    templates = _FALLBACK_TEMPLATES_COM_DEMO if tem_demo_publica else _FALLBACK_TEMPLATES_SEM_DEMO
    mensagem = random.choice(templates).format(nome=nome_negocio)
    if tem_demo_publica:
        mensagem = f"{mensagem}\n{lead['demo_public_url']}"
    return mensagem


def generate_messages_for_leads(
    leads: list[dict],
    output_path: str = "leads_com_mensagens.json",
) -> list[dict]:
    """Gera uma mensagem para cada lead e salva o resultado combinado em JSON."""
    if not leads:
        logger.warning("Nenhum lead recebido para gerar mensagens.")
        return []

    client = _get_client()
    enriched: list[dict] = []

    for i, lead in enumerate(leads, start=1):
        logger.info("Gerando mensagem %d/%d...", i, len(leads))
        mensagem = generate_message(lead, client=client)
        enriched.append({**lead, "mensagem": mensagem})

    Path(output_path).write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Mensagens geradas e salvas em '%s' (%d registros).", output_path, len(enriched))
    return enriched
