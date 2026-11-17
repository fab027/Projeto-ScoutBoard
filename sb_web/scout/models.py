import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sb_web.ext.db import db

if TYPE_CHECKING:
    from sb_web.campeonato.models import Player

NOTA_MINIMA = 1
NOTA_MAXIMA = 10
TAMANHO_AUTOR = 60
TAMANHO_TEXTO = 1000


def _agora() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Observacao(db.Model):
    """Anotação de um observador sobre um jogador em uma temporada, com nota de 1 a 10."""
    __tablename__ = "observacoes"
    __table_args__ = (
        CheckConstraint(f"nota BETWEEN {NOTA_MINIMA} AND {NOTA_MAXIMA}", name="ck_observacao_nota"),
    )

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(
        db.Integer, db.ForeignKey("jogadores.player_id"), nullable=False, index=True
    )
    temporada: Mapped[str] = mapped_column(db.String(20), nullable=False)
    autor: Mapped[str] = mapped_column(db.String(TAMANHO_AUTOR), nullable=False)
    nota: Mapped[int] = mapped_column(db.Integer, nullable=False)
    texto: Mapped[str] = mapped_column(db.Text, nullable=False)
    # Sempre em UTC; a página só mostra a data.
    criado_em: Mapped[dt.datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=_agora, index=True
    )

    jogador: Mapped["Player"] = relationship("Player", back_populates="observacoes")

    def __repr__(self) -> str:
        return f"<Observacao id={self.id} player_id={self.player_id} nota={self.nota}>"
