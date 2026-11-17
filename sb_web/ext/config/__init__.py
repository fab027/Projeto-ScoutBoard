"""Configuração da aplicação, lida das variáveis de ambiente (arquivo .env; modelo em .env.example)."""
import os

import config as _projeto  # noqa: F401 - carrega o .env antes de as variáveis serem lidas

CHAVE_DE_DESENVOLVIMENTO = "dev-secret-scoutboard"


def _ligado(nome: str) -> bool:
    return os.getenv(nome, "").strip().lower() in {"1", "true", "sim", "on"}


def init_app(app):
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", CHAVE_DE_DESENVOLVIMENTO)
    app.config["DEBUG"] = _ligado("FLASK_DEBUG")
    app.config["LOG_LEVEL"] = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "sqlite:///scoutboard.db",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
