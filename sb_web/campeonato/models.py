from typing import TYPE_CHECKING
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sb_web.ext.db import db

if TYPE_CHECKING:
    from sb_web.analytics.models import MatchEvent
    from sb_web.scout.models import Observacao


class Competition(db.Model):
    __tablename__ = "competicoes"
    __table_args__ = (
        UniqueConstraint("pais", "liga", name="uq_competicao_pais_liga"),
    )

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    pais: Mapped[str] = mapped_column(db.String(10), nullable=False, index=True)
    liga: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)

    temporadas: Mapped[list["Season"]] = relationship(
        "Season", back_populates="competicao", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Competition id={self.id} pais='{self.pais}' liga='{self.liga}'>"


class Season(db.Model):
    __tablename__ = "temporadas"
    __table_args__ = (
        UniqueConstraint("competicao_id", "temporada", name="uq_temporada_competicao_ano"),
    )

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    competicao_id: Mapped[int] = mapped_column(
        db.Integer, db.ForeignKey("competicoes.id"), nullable=False, index=True
    )
    temporada: Mapped[str] = mapped_column(db.String(20), nullable=False, index=True)

    competicao: Mapped["Competition"] = relationship("Competition", back_populates="temporadas")
    jogos: Mapped[list["Match"]] = relationship(
        "Match", back_populates="temporada_rel", cascade="all, delete-orphan"
    )
    elencos: Mapped[list["SquadMember"]] = relationship(
        "SquadMember", back_populates="temporada_rel", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Season id={self.id} competicao_id={self.competicao_id} temporada='{self.temporada}'>"


class Team(db.Model):
    __tablename__ = "times"

    team_id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=False)
    team: Mapped[str] = mapped_column(db.String(150), nullable=False, index=True)

    jogos_casa: Mapped[list["Match"]] = relationship(
        "Match", back_populates="home_team", foreign_keys="Match.home_team_id"
    )
    jogos_fora: Mapped[list["Match"]] = relationship(
        "Match", back_populates="away_team", foreign_keys="Match.away_team_id"
    )
    elencos: Mapped[list["SquadMember"]] = relationship("SquadMember", back_populates="team_rel")
    eventos: Mapped[list["MatchEvent"]] = relationship("MatchEvent", back_populates="team_rel")

    def __repr__(self) -> str:
        return f"<Team team_id={self.team_id} team='{self.team}'>"


class Player(db.Model):
    __tablename__ = "jogadores"

    player_id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=False)
    player: Mapped[str] = mapped_column(db.String(150), nullable=False, index=True)

    elencos: Mapped[list["SquadMember"]] = relationship("SquadMember", back_populates="player_rel")
    eventos: Mapped[list["MatchEvent"]] = relationship("MatchEvent", back_populates="player_rel")
    observacoes: Mapped[list["Observacao"]] = relationship(
        "Observacao", back_populates="jogador", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Player player_id={self.player_id} player='{self.player}'>"


class SquadMember(db.Model):
    """Tabela associativa: registra em qual time o jogador atuou em cada temporada."""
    __tablename__ = "elencos_temporada"
    __table_args__ = (
        UniqueConstraint(
            "temporada_id", "team_id", "player_id", name="uq_elenco_temp_time_jogador"
        ),
    )

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    temporada_id: Mapped[int] = mapped_column(
        db.Integer, db.ForeignKey("temporadas.id"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(
        db.Integer, db.ForeignKey("times.team_id"), nullable=False, index=True
    )
    player_id: Mapped[int] = mapped_column(
        db.Integer, db.ForeignKey("jogadores.player_id"), nullable=False, index=True
    )

    temporada_rel: Mapped["Season"] = relationship("Season", back_populates="elencos")
    team_rel: Mapped["Team"] = relationship("Team", back_populates="elencos")
    player_rel: Mapped["Player"] = relationship("Player", back_populates="elencos")


class Match(db.Model):
    __tablename__ = "jogos"

    game_id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=False)
    temporada_id: Mapped[int] = mapped_column(
        db.Integer, db.ForeignKey("temporadas.id"), nullable=False, index=True
    )
    home_team_id: Mapped[int] = mapped_column(
        db.Integer, db.ForeignKey("times.team_id"), nullable=False, index=True
    )
    away_team_id: Mapped[int] = mapped_column(
        db.Integer, db.ForeignKey("times.team_id"), nullable=False, index=True
    )

    temporada_rel: Mapped["Season"] = relationship("Season", back_populates="jogos")
    home_team: Mapped["Team"] = relationship(
        "Team", back_populates="jogos_casa", foreign_keys=[home_team_id]
    )
    away_team: Mapped["Team"] = relationship(
        "Team", back_populates="jogos_fora", foreign_keys=[away_team_id]
    )
    eventos: Mapped[list["MatchEvent"]] = relationship(
        "MatchEvent", back_populates="jogo", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Match game_id={self.game_id} "
            f"home={self.home_team_id} away={self.away_team_id}>"
        )