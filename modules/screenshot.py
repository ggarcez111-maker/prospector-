"""
modules/screenshot.py

Gera um print (PNG) da landing page de demonstracao, para enviar como
imagem junto com a mensagem no WhatsApp (pywhatkit.sendwhats_image aceita
legenda). Usa o Playwright (Firefox) que ja e dependencia do projeto -
nao precisa instalar nada alem do que o Modulo 1 ja requer.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from utils.logger import get_logger

logger = get_logger(__name__)


def capture_demo_screenshot(
    html_path: str,
    output_path: str | None = None,
    viewport_width: int = 1200,
    viewport_height: int = 800,
) -> str | None:
    """
    Renderiza o arquivo HTML local e salva um screenshot PNG ao lado dele
    (ou em `output_path`, se informado). Retorna o caminho do PNG, ou None
    se a captura falhar (nao interrompe o fluxo principal).
    """
    html_file = Path(html_path)
    if not html_file.exists():
        logger.warning("Arquivo de demo '%s' nao encontrado para screenshot.", html_path)
        return None

    target = Path(output_path) if output_path else html_file.with_suffix(".png")

    try:
        with sync_playwright() as pw:
            browser = pw.firefox.launch(headless=True)
            page = browser.new_page(viewport={"width": viewport_width, "height": viewport_height})
            page.goto(html_file.resolve().as_uri())
            page.screenshot(path=str(target))
            browser.close()
        logger.info("Screenshot da demo gerado em '%s'.", target)
        return str(target)
    except Exception as exc:  # noqa: BLE001 - qualquer falha de renderizacao nao deve travar o fluxo
        logger.warning("Nao foi possivel gerar screenshot de '%s': %s", html_path, exc)
        return None
