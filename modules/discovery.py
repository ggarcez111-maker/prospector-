"""
modules/discovery.py

MODULO 1 - Descoberta de leads no Google Maps, sem usar a API paga do Google.

A biblioteca `google-maps-scraper` (pacote PyPI `gmaps_scraper`) sabe extrair
todos os detalhes (nome, telefone, endereco, nota, avaliacoes, site, etc.) de
UMA url de local do Google Maps por vez - ela nao pagina uma lista de
resultados de busca sozinha (quando recebe uma url de busca com varios
resultados, ela abre apenas o primeiro).

Por isso este modulo faz o trabalho em duas etapas:

  1. `collect_place_urls()`  -> abre a busca ("restaurantes em Curitiba PR")
     no Google Maps com Playwright (Firefox) e rola a lista de resultados
     (o painel `div[role="feed"]`) coletando a url de cada estabelecimento.
  2. `enrich_place_urls()`   -> usa a biblioteca `gmaps_scraper`
     (GoogleMapsScraper) para abrir cada uma dessas urls e extrair os
     dados estruturados do local.

No final, `discover_leads()` filtra apenas os locais SEM website cadastrado
e grava o resultado em `leads.json`.
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from utils.logger import get_logger

logger = get_logger(__name__)

GOOGLE_MAPS_SEARCH_URL = "https://www.google.com/maps/search/{query}"
RESULTS_FEED_SELECTOR = 'div[role="feed"]'
RESULT_LINK_SELECTOR = 'a[href*="/maps/place/"]'

# Textos que aparecem em telas de bloqueio/CAPTCHA do Google.
_CAPTCHA_MARKERS = (
    "unusual traffic",
    "trafego incomum",
    "tráfego incomum",
    "recaptcha",
    "sorry/index",
    "detectamos atividade suspeita",
)


class CaptchaDetectedError(RuntimeError):
    """Levantada quando o Google exibe uma pagina de verificacao/CAPTCHA."""


class GoogleMapsTimeoutError(RuntimeError):
    """Levantada quando um elemento esperado nao aparece a tempo."""


@dataclass
class Lead:
    nome: str
    telefone: Optional[str]
    endereco: Optional[str]
    nota: Optional[float]
    numero_avaliacoes: Optional[int]
    link_perfil: str
    website: Optional[str] = None
    categoria: Optional[str] = None
    horarios: Optional[list] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _build_search_url(query: str) -> str:
    return GOOGLE_MAPS_SEARCH_URL.format(query=quote_plus(query))


async def _check_for_captcha(page: Page) -> None:
    content = (await page.content()).lower()
    if any(marker in content for marker in _CAPTCHA_MARKERS):
        raise CaptchaDetectedError(
            "O Google exibiu uma pagina de verificacao/CAPTCHA. "
            "Tente novamente mais tarde, reduza a frequencia de buscas "
            "ou rode com headless=False para resolver manualmente."
        )


async def collect_place_urls(
    query: str,
    max_results: int = 30,
    headless: bool = True,
    language: str = "pt-BR",
    scroll_pause_seconds: float = 1.5,
    max_scroll_attempts: int = 40,
    navigation_timeout_ms: int = 30_000,
) -> list[str]:
    """
    Abre a busca no Google Maps e rola o painel de resultados coletando
    a url de cada estabelecimento encontrado, ate atingir `max_results`
    ou esgotar a lista (sem "carregar mais").
    """
    search_url = _build_search_url(query)
    logger.info("Iniciando busca no Google Maps: '%s' -> %s", query, search_url)

    collected: "dict[str, None]" = {}  # preserva ordem e evita duplicados

    async with async_playwright() as pw:
        browser = await pw.firefox.launch(headless=headless)
        context = await browser.new_context(locale=language)
        page = await context.new_page()
        page.set_default_timeout(navigation_timeout_ms)

        try:
            try:
                await page.goto(search_url, wait_until="domcontentloaded")
            except PlaywrightTimeoutError as exc:
                raise GoogleMapsTimeoutError(
                    f"Timeout ao carregar a busca '{query}' no Google Maps."
                ) from exc

            await _check_for_captcha(page)

            # Tenta aceitar cookies/consentimento, se aparecer (varia por regiao).
            for consent_text in ("Aceitar tudo", "Accept all", "I agree", "Aceito"):
                try:
                    btn = page.get_by_role("button", name=consent_text)
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        break
                except PlaywrightTimeoutError:
                    continue

            try:
                await page.wait_for_selector(RESULTS_FEED_SELECTOR, timeout=navigation_timeout_ms)
            except PlaywrightTimeoutError as exc:
                await _check_for_captcha(page)
                raise GoogleMapsTimeoutError(
                    "O painel de resultados do Google Maps nao apareceu a tempo. "
                    "A busca pode ter retornado um unico local diretamente, "
                    "ou a pagina mudou de layout."
                ) from exc

            feed = page.locator(RESULTS_FEED_SELECTOR)

            stagnant_rounds = 0
            for attempt in range(max_scroll_attempts):
                links = await page.locator(RESULT_LINK_SELECTOR).all()
                for link in links:
                    href = await link.get_attribute("href")
                    if href and href not in collected:
                        collected[href] = None

                if len(collected) >= max_results:
                    logger.info("Limite de %d resultados atingido.", max_results)
                    break

                previous_count = len(collected)

                # Rola o painel de resultados ate o ultimo item visivel.
                await feed.evaluate("node => node.scrollTo(0, node.scrollHeight)")
                await asyncio.sleep(scroll_pause_seconds)

                if len(collected) == previous_count:
                    stagnant_rounds += 1
                else:
                    stagnant_rounds = 0

                # "Voce chegou ao final da lista" / nenhum resultado novo em 3 rolagens.
                if stagnant_rounds >= 3:
                    logger.info(
                        "Fim da lista de resultados detectado apos %d tentativas.",
                        attempt + 1,
                    )
                    break

        finally:
            await context.close()
            await browser.close()

    urls = list(collected.keys())[:max_results]
    logger.info("Coletadas %d urls de estabelecimentos para '%s'.", len(urls), query)
    return urls


async def enrich_place_urls(
    urls: list[str],
    language: str = "pt-BR",
    concurrency: int = 3,
    headless: bool = True,
) -> list[dict]:
    """
    Usa a biblioteca google-maps-scraper (gmaps_scraper) para extrair os
    dados estruturados (nome, telefone, endereco, nota, avaliacoes, website)
    de cada url de estabelecimento coletada em `collect_place_urls`.
    """
    try:
        from gmaps_scraper import GoogleMapsScraper, ScrapeConfig
    except ImportError as exc:
        raise RuntimeError(
            "A biblioteca 'google-maps-scraper' nao esta instalada. "
            "Rode: pip install google-maps-scraper && playwright install firefox"
        ) from exc

    config = ScrapeConfig(language=language, headless=headless)
    semaphore = asyncio.Semaphore(concurrency)
    results: list[dict] = []

    async def _scrape_one(scraper: "GoogleMapsScraper", url: str) -> None:
        async with semaphore:
            try:
                result = await scraper.scrape(url)
            except PlaywrightTimeoutError:
                logger.warning("Timeout ao extrair detalhes de %s - pulando.", url)
                return
            except Exception as exc:  # noqa: BLE001 - qualquer falha do scraper individual
                logger.warning("Erro ao extrair detalhes de %s: %s", url, exc)
                return

            if not result.success or result.place is None:
                logger.warning("Nao foi possivel extrair dados de %s.", url)
                return

            place = result.place
            results.append(
                {
                    "nome": place.name,
                    "telefone": getattr(place, "phone", None),
                    "endereco": getattr(place, "address", None),
                    "nota": getattr(place, "rating", None),
                    "numero_avaliacoes": getattr(place, "review_count", None),
                    "link_perfil": getattr(place, "google_maps_url", None) or url,
                    "website": getattr(place, "website", None),
                    "categoria": getattr(place, "category", None),
                    "horarios": _extract_hours(place),
                }
            )
            # Pequena pausa aleatoria entre extracoes para reduzir risco de bloqueio.
            await asyncio.sleep(random.uniform(0.5, 1.5))

    async with GoogleMapsScraper(config) as scraper:
        await asyncio.gather(*(_scrape_one(scraper, url) for url in urls))

    logger.info("Detalhes extraidos com sucesso para %d de %d urls.", len(results), len(urls))
    return results


def _extract_hours(place: object) -> list[str]:
    """
    Horario de funcionamento, em melhor esforco: a biblioteca pode expor o
    campo com nomes/formatos diferentes entre versoes. Se nada vier, a demo
    simplesmente nao mostra a secao de horarios (nunca inventa).
    """
    raw = None
    for attr in ("opening_hours", "hours", "working_hours", "business_hours"):
        raw = getattr(place, attr, None)
        if raw:
            break
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw.strip()]
    if isinstance(raw, dict):
        return [f"{k}: {v}" for k, v in raw.items() if v]
    out: list[str] = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, str):
                out.append(item.strip())
            elif isinstance(item, dict):
                out.append(": ".join(str(v) for v in item.values() if v))
            else:
                out.append(str(item))
    return [x for x in out if x]


def filter_leads_without_website(places: list[dict]) -> list[Lead]:
    """Mantem apenas os estabelecimentos que NAO possuem website cadastrado."""
    leads = [
        Lead(
            nome=p.get("nome") or "Sem nome",
            telefone=p.get("telefone"),
            endereco=p.get("endereco"),
            nota=p.get("nota"),
            numero_avaliacoes=p.get("numero_avaliacoes"),
            link_perfil=p.get("link_perfil"),
            website=None,
            categoria=p.get("categoria"),
            horarios=p.get("horarios") or None,
        )
        for p in places
        if not p.get("website")
    ]
    logger.info(
        "%d de %d estabelecimentos NAO possuem website cadastrado.",
        len(leads),
        len(places),
    )
    return leads


def save_leads(leads: list[Lead], output_path: str = "leads.json") -> None:
    data = [lead.to_dict() for lead in leads]
    Path(output_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Leads salvos em '%s' (%d registros).", output_path, len(data))


async def discover_leads_async(
    query: str,
    max_results: int = 30,
    output_path: str = "leads.json",
    headless: bool = True,
    language: str = "pt-BR",
    concurrency: int = 3,
) -> list[dict]:
    try:
        urls = await collect_place_urls(
            query=query, max_results=max_results, headless=headless, language=language
        )
    except CaptchaDetectedError:
        logger.error("Busca interrompida: CAPTCHA detectado pelo Google Maps.")
        return []
    except GoogleMapsTimeoutError as exc:
        logger.error("Busca interrompida por timeout: %s", exc)
        return []

    if not urls:
        logger.warning("Nenhum estabelecimento encontrado para a busca '%s'.", query)
        return []

    places = await enrich_place_urls(
        urls, language=language, concurrency=concurrency, headless=headless
    )
    leads = filter_leads_without_website(places)
    save_leads(leads, output_path)
    return [lead.to_dict() for lead in leads]


def discover_leads(
    query: str,
    max_results: int = 30,
    output_path: str = "leads.json",
    headless: bool = True,
    language: str = "pt-BR",
    concurrency: int = 3,
) -> list[dict]:
    """Wrapper sincrono - ponto de entrada usado pelo main.py."""
    return asyncio.run(
        discover_leads_async(
            query=query,
            max_results=max_results,
            output_path=output_path,
            headless=headless,
            language=language,
            concurrency=concurrency,
        )
    )
