"""Leitura e gravação das observações no banco (SQLAlchemy)."""
import logging

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from sb_web.campeonato.models import Player
from sb_web.ext.db import db
from sb_web.scout.models import Observacao

log = logging.getLogger(__name__)
LIMITE_LISTA = 100


def listar(player_id: int | None = None, limite: int = LIMITE_LISTA) -> list[Observacao]:
    """Observações mais recentes primeiro, com o jogador carregado na mesma consulta."""
    consulta = db.select(Observacao).options(joinedload(Observacao.jogador))
    if player_id is not None:
        consulta = consulta.where(Observacao.player_id == player_id)
    consulta = consulta.order_by(Observacao.criado_em.desc(), Observacao.id.desc()).limit(limite)
    return list(db.session.scalars(consulta))


def resumo_por_jogador(limite: int = 10) -> list[dict]:
    """Jogadores mais bem avaliados: média das notas e quantidade de observações de cada um."""
    media = func.avg(Observacao.nota)
    consulta = (
        db.select(Player.player_id, Player.player, func.count(Observacao.id), media)
        .join(Observacao, Observacao.player_id == Player.player_id)
        .group_by(Player.player_id, Player.player)
        .order_by(media.desc(), func.count(Observacao.id).desc(), Player.player)
        .limit(limite)
    )
    return [
        {"player_id": player_id, "player": nome, "observacoes": quantidade, "media": round(float(nota), 1)}
        for player_id, nome, quantidade, nota in db.session.execute(consulta)
    ]


def registrar(*, player_id: int, nome: str, temporada: str, autor: str, nota: int, texto: str) -> Observacao:
    """Grava a observação; o jogador entra na tabela `jogadores` se o banco ainda não o tem.

    As duas tabelas são gravadas na mesma transação: sem jogador, não fica observação órfã.
    """
    try:
        jogador = db.session.get(Player, player_id)
        if jogador is None:
            jogador = Player(player_id=player_id, player=nome)
            db.session.add(jogador)
        observacao = Observacao(jogador=jogador, temporada=temporada, autor=autor, nota=nota, texto=texto)
        db.session.add(observacao)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    log.info("Observação %s gravada para o jogador %s (nota %s)", observacao.id, player_id, nota)
    return observacao


def excluir(observacao_id: int) -> bool:
    """Apaga a observação; False se ela não existe."""
    observacao = db.session.get(Observacao, observacao_id)
    if observacao is None:
        return False
    try:
        db.session.delete(observacao)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    log.info("Observação %s excluída", observacao_id)
    return True
