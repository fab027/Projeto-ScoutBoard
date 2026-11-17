from typing import Optional, TYPE_CHECKING
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sb_web.ext.db import db

if TYPE_CHECKING:
    from sb_web.campeonato.models import Match, Team, Player


class MatchEvent(db.Model):
    __tablename__ = "eventos_partida"
    __table_args__ = (
        UniqueConstraint("game_id", "action_id", name="uq_evento_jogo_action"),
    )

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    action_id: Mapped[int] = mapped_column(db.Integer, nullable=False)

    game_id: Mapped[int] = mapped_column(
        db.Integer, db.ForeignKey("jogos.game_id"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(
        db.Integer, db.ForeignKey("times.team_id"), nullable=False, index=True
    )
    player_id: Mapped[int | None] = mapped_column(
        db.Integer, db.ForeignKey("jogadores.player_id"), nullable=True, index=True
    )

    period_id: Mapped[int] = mapped_column(db.Integer, nullable=False)
    time_seconds: Mapped[float] = mapped_column(db.Float, nullable=False)
    original_event_id: Mapped[str | None] = mapped_column(db.String(64), nullable=True)

    start_x: Mapped[float] = mapped_column(db.Float, nullable=False)
    start_y: Mapped[float] = mapped_column(db.Float, nullable=False)
    end_x: Mapped[float | None] = mapped_column(db.Float, nullable=True)
    end_y: Mapped[float | None] = mapped_column(db.Float, nullable=True)

    type_id: Mapped[int] = mapped_column(db.Integer, nullable=False, index=True)
    result_id: Mapped[int] = mapped_column(db.Integer, nullable=False)
    bodypart_id: Mapped[int] = mapped_column(db.Integer, nullable=False)

    jogo: Mapped["Match"] = relationship("Match", back_populates="eventos")
    team_rel: Mapped["Team"] = relationship("Team", back_populates="eventos")
    player_rel: Mapped[Optional["Player"]] = relationship("Player", back_populates="eventos")

    def __repr__(self) -> str:
        return (
            f"<MatchEvent id={self.id} game_id={self.game_id} "
            f"action_id={self.action_id} type_id={self.type_id}>"
        )