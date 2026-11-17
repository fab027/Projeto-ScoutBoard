"""Configuração da aplicação, lida das variáveis de ambiente (arquivo .env; modelo em .env.example)."""
import os
import secrets

import config as _projeto  # noqa: F401 - carrega o .env antes de as variáveis serem lidas

# Chave fixa só no modo de depuração: o recarregador do Flask recria o app a cada alteração e uma chave
# aleatória mudaria junto, invalidando os formulários abertos. Fora dele, a chave é sorteada a cada início.
CHAVE_DE_DESENVOLVIMENTO = "dev-secret-scoutboard"


def _ligado(nome: str) -> bool:
    return os.getenv(nome, "").strip().lower() in {"1", "true", "sim", "on"}


def init_app(app):
    chave = os.getenv("SECRET_KEY", "").strip()
    depuracao = _ligado("FLASK_DEBUG")
    app.config["SECRET_KEY_DEFINIDA"] = bool(chave)
    app.config["SECRET_KEY"] = chave or (CHAVE_DE_DESENVOLVIMENTO if depuracao else secrets.token_hex(32))
    app.config["DEBUG"] = depuracao
    app.config["LOG_LEVEL"] = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "sqlite:///scoutboard.db",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
