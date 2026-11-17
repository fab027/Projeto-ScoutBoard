"""Aplicação Flask do ScoutBoard: site, banco de dados e comandos de terminal.

A partir da raiz do projeto:
    python iniciar.py                       # sobe o site
    flask --app app importar-brutos         # preenche o banco com dados/brutos
"""
from flask import Flask

from sb_web import erros
from sb_web.ext.cli import init_app as init_cli
from sb_web.ext.config import init_app as init_config
from sb_web.ext.csrf import init_app as init_csrf
from sb_web.ext.db import create_tables, register_models
from sb_web.ext.db import init_app as init_db
from sb_web.ext.log import init_app as init_log
from sb_web.rotas import site_bp
from sb_web.scout.rotas import scout_bp


def create_app(**config) -> Flask:
    """`config` sobrescreve as configurações padrão (ex.: TESTING nos testes)."""
    app = Flask(__name__)

    # Inicializa configurações, log e banco de dados
    init_config(app)
    app.config.update(config)
    init_log(app)
    init_csrf(app)
    # Em debug o Flask indenta o JSON; a API do painel tem centenas de jogadores e o app.js não precisa disso.
    app.json.compact = True
    init_db(app)
    register_models()
    create_tables(app)

    # Registra os comandos de terminal (CLI)
    init_cli(app)

    # Registra as rotas e as respostas de erro
    app.register_blueprint(site_bp)
    app.register_blueprint(scout_bp)
    erros.init_app(app)

    return app
