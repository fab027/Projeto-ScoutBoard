"""Log da aplicação: uma linha por evento no terminal, no nível de LOG_LEVEL."""
import logging
import time

FORMATO = "%(asctime)s %(levelname)s %(name)s: %(message)s"
FORMATO_DATA = "%Y-%m-%dT%H:%M:%SZ"


def init_app(app):
    nivel = getattr(logging, app.config.get("LOG_LEVEL", "INFO"), logging.INFO)
    formatador = logging.Formatter(FORMATO, datefmt=FORMATO_DATA)
    formatador.converter = time.gmtime  # horário em UTC, igual ao dos dados gravados
    manipulador = logging.StreamHandler()
    manipulador.setFormatter(formatador)
    # Sem efeito se o processo já configurou o log (pytest, servidor WSGI): vale a configuração dele.
    logging.basicConfig(level=nivel, handlers=[manipulador])
    logging.getLogger("sb_web").setLevel(nivel)
    if not app.config["SECRET_KEY_DEFINIDA"] and not (app.debug or app.testing):
        logging.getLogger(__name__).warning(
            "SECRET_KEY não definida: chave sorteada a cada início. Formulários abertos perdem a validade "
            "ao reiniciar; defina SECRET_KEY no .env."
        )
