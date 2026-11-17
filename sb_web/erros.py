"""Respostas de erro do site: página no padrão visual para pessoas, JSON para a API."""
import logging

from flask import jsonify, render_template, request
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import SQLAlchemyError

from sb_web.ext.db import db

log = logging.getLogger(__name__)

MENSAGENS = {
    400: ("Requisição inválida", "Os dados enviados não puderam ser lidos."),
    404: ("Página não encontrada", "O endereço não existe ou mudou de lugar."),
    500: ("Erro interno", "Algo deu errado do nosso lado. Tente de novo em instantes."),
}


def _resposta(status: int, detalhe: str | None = None):
    titulo, mensagem = MENSAGENS[status]
    if request.path.startswith("/api/"):
        return jsonify({"erro": detalhe or mensagem}), status
    return render_template("erro.html", pagina="erro", status=status, titulo=titulo,
                           mensagem=detalhe or mensagem), status


def init_app(app):
    @app.errorhandler(400)
    def requisicao_invalida(_erro):
        return _resposta(400)

    @app.errorhandler(404)
    def nao_encontrada(_erro):
        return _resposta(404)

    @app.errorhandler(CSRFError)
    def csrf_invalido(erro):
        log.warning("Formulário recusado em %s: %s", request.path, erro.description)
        return _resposta(400, "O formulário expirou ou veio de outra página. Recarregue e envie de novo.")

    @app.errorhandler(SQLAlchemyError)
    def erro_de_banco(erro):
        db.session.rollback()
        log.exception("Erro de banco em %s %s", request.method, request.path, exc_info=erro)
        return _resposta(500)

    @app.errorhandler(500)
    def erro_interno(erro):
        log.error("Erro interno em %s %s: %s", request.method, request.path, erro)
        return _resposta(500)
