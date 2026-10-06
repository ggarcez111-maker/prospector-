"""
modules/hosting.py

Publica automaticamente cada landing page de demonstracao em um repositorio
GitHub Pages, para que o link enviado no WhatsApp funcione de verdade
(sem isso, a demo fica só em disco local e não tem URL pública).

100% gratuito: usa um repositorio GitHub existente (publico ou privado com
Pages habilitado) e a API REST de Conteudo do GitHub para criar/atualizar
o arquivo. Requer um Personal Access Token com escopo "repo" (ou "public_repo"
para repositorios publicos), criado em:
https://github.com/settings/tokens

Configuracao (.env):
  GITHUB_TOKEN=ghp_xxx
  GITHUB_REPO=usuario/repositorio
  GITHUB_BRANCH=gh-pages          (branch usada pelo GitHub Pages)
  GITHUB_PAGES_BASE_URL=          (opcional; sobrescreve a URL calculada,
                                    util se voce usa dominio customizado)

Se GITHUB_TOKEN ou GITHUB_REPO nao estiverem configurados, `is_configured()`
retorna False e o main.py simplesmente pula a publicacao (a demo continua
disponivel localmente, só sem link publico).
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

from utils.logger import get_logger

logger = get_logger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def is_configured() -> bool:
    return bool(os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_REPO"))


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _pages_url(repo: str, remote_path: str) -> str:
    override = os.getenv("GITHUB_PAGES_BASE_URL")
    if override:
        return f"{override.rstrip('/')}/{remote_path}"
    owner, _, name = repo.partition("/")
    # Formato padrao do GitHub Pages para repositorios de projeto.
    return f"https://{owner}.github.io/{name}/{remote_path}"


def publish_demo(
    local_html_path: str,
    slug: str,
    timeout: int = 20,
    max_retries: int = 3,
) -> str | None:
    """
    Envia o arquivo HTML local para `demos/<slug>/index.html` no repositorio
    configurado e retorna a URL publica do GitHub Pages, ou None se a
    publicacao nao estiver configurada ou falhar apos as tentativas.
    """
    if not is_configured():
        logger.info(
            "Publicacao automatica de demo desativada (GITHUB_TOKEN/GITHUB_REPO "
            "nao configurados) - a demo continua disponivel so localmente."
        )
        return None

    repo = os.getenv("GITHUB_REPO", "")
    branch = os.getenv("GITHUB_BRANCH", "gh-pages")
    remote_path = f"demos/{slug}/index.html"
    api_url = f"{GITHUB_API_BASE}/repos/{repo}/contents/{remote_path}"

    try:
        content_bytes = Path(local_html_path).read_bytes()
    except OSError as exc:
        logger.error("Nao foi possivel ler o arquivo de demo '%s': %s", local_html_path, exc)
        return None

    content_b64 = base64.b64encode(content_bytes).decode("ascii")

    for attempt in range(1, max_retries + 1):
        try:
            # Verifica se o arquivo ja existe (precisa do sha para atualizar).
            sha = None
            existing = requests.get(
                api_url,
                headers=_headers(),
                params={"ref": branch},
                timeout=timeout,
            )
            if existing.status_code == 200:
                sha = existing.json().get("sha")
            elif existing.status_code not in (404,):
                logger.warning(
                    "Verificacao previa do GitHub retornou status %d para '%s'.",
                    existing.status_code,
                    remote_path,
                )

            payload = {
                "message": f"docs: publica demo de {slug}",
                "content": content_b64,
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha

            response = requests.put(api_url, headers=_headers(), json=payload, timeout=timeout)

            if response.status_code in (200, 201):
                url = _pages_url(repo, f"demos/{slug}/")
                logger.info("Demo publicada com sucesso: %s", url)
                return url

            if response.status_code == 409:
                # Conflito de SHA (corrida entre execucoes) - tenta de novo.
                logger.warning("Conflito ao publicar '%s' (tentativa %d/%d).", slug, attempt, max_retries)
                continue

            if response.status_code in (401, 403):
                logger.error(
                    "GitHub recusou a publicacao (status %d) - verifique GITHUB_TOKEN "
                    "e as permissoes do repositorio '%s'. Detalhe: %s",
                    response.status_code,
                    repo,
                    response.text[:300],
                )
                return None

            if response.status_code == 404:
                logger.error(
                    "Repositorio '%s' ou branch '%s' nao encontrado. "
                    "Verifique GITHUB_REPO/GITHUB_BRANCH.",
                    repo,
                    branch,
                )
                return None

            logger.warning(
                "GitHub retornou status inesperado %d ao publicar '%s': %s",
                response.status_code,
                slug,
                response.text[:300],
            )

        except requests.exceptions.Timeout:
            logger.warning("Timeout ao publicar demo '%s' (tentativa %d/%d).", slug, attempt, max_retries)
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "Erro de rede ao publicar demo '%s' (tentativa %d/%d): %s",
                slug,
                attempt,
                max_retries,
                exc,
            )

    logger.error("Nao foi possivel publicar a demo de '%s' apos %d tentativas.", slug, max_retries)
    return None
