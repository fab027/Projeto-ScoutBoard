"""Log da aplicação: uma linha por evento no terminal, no nível de LOG_LEVEL."""
import logging
import time

from sb_web.ext.config import CHAVE_DE_DESENVOLVIMENTO

FORMATO = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def init_app(app):
    nivel = getattr(logging, app.config.get("LOG_LEVEL", "INFO"), logging.INFO)
    # Sem efeito se o processo já configurou o log (pytest, servidor WSGI): vale a configuração dele.
    logging.Formatter.converter = time.gmtime  # horário em UTC, igual ao dos dados gravados
    logging.basicConfig(level=nivel, format=FORMATO, datefmt="%Y-%m-%dT%H:%M:%SZ")
    logging.getLogger("sb_web").setLevel(nivel)
    if app.config["SECRET_KEY"] == CHAVE_DE_DESENVOLVIMENTO and not (app.debug or app.testing):
        logging.getLogger(__name__).warning(
            "SECRET_KEY não definida: usando a chave de desenvolvimento. Defina SECRET_KEY no .env."
        )
