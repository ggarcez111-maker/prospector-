"""
utils/logger.py

Configuracao centralizada de logging para o projeto.
Cria (ou reaproveita) um logger que escreve simultaneamente:
  - no console (stdout), formato enxuto
  - em arquivo de log (por padrao 'envios.log' na raiz do projeto),
    formato detalhado com timestamp

Uso:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("mensagem")
"""

import logging
import os
import sys

_LOG_FILE = os.getenv("LOG_FILE", "envios.log")
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

_CONFIGURED = False


def _configure_root_logger() -> None:
    """Configura o logger raiz uma unica vez para todo o processo."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))

    # Evita handlers duplicados se a funcao for chamada mais de uma vez
    if root.handlers:
        _CONFIGURED = True
        return

    formatter_console = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    formatter_file = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setFormatter(formatter_console)
    console_handler.setLevel(logging.INFO)

    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter_file)
    file_handler.setLevel(logging.DEBUG)

    root.addHandler(console_handler)
    root.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger nomeado, garantindo que o root ja esteja configurado."""
    _configure_root_logger()
    return logging.getLogger(name)
