"""Comando importar-brutos: grava competições, times, jogadores, jogos, elencos e eventos dos .parquet."""
import pandas as pd

from sb_web import create_app
from sb_web.analytics.models import MatchEvent
from sb_web.campeonato.models import Competition, Match, Player, Season, SquadMember, Team
from sb_web.ext.db import db


def _eventos() -> pd.DataFrame:
    """Dois jogos de 2024. No primeiro, o time 10 (mandante) joga com o 20; no segundo, com o 30."""
    df = pd.DataFrame(
        [
            (1, 1, 10, 1, 10, 20, 0),
            (1, 2, 10, 2, 10, 20, 11),
            (1, 3, 20, 3, 10, 20, 0),
            (2, 4, 10, 1, 10, 30, 0),
            (2, 5, 30, 4, 10, 30, 0),
        ],
        columns=["game_id", "action_id", "team_id", "player_id", "home_team_id", "away_team_id", "type_id"],
    )
    df["team"] = df["team_id"].map({10: "Time 10", 20: "Time 20", 30: "Time 30"})
    df["player"] = df["player_id"].map({1: "Jogador 1", 2: "Jogador 2", 3: "Jogador 3", 4: "Jogador 4"})
    df["period_id"] = 1
    df["time_seconds"] = [10.0, 20.0, 30.0, 40.0, 50.0]
    df["original_event_id"] = [f"ev{n}" for n in df["action_id"]]
    df["start_x"] = [20.0, 90.0, 30.0, 50.0, 60.0]
    df["start_y"] = [30.0, 34.0, 30.0, 34.0, 30.0]
    df["end_x"] = [40.0, 100.0, 40.0, 60.0, 70.0]
    df["end_y"] = [30.0, 34.0, 30.0, 34.0, 30.0]
    df["result_id"] = 1
    df["bodypart_id"] = 0
    return df


def _app_e_cli():
    app = create_app(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://")
    return app, app.test_cli_runner()


def _contagens(app) -> dict:
    with app.app_context():
        return {
            "competicoes": db.session.query(Competition).count(),
            "temporadas": db.session.query(Season).count(),
            "times": db.session.query(Team).count(),
            "jogadores": db.session.query(Player).count(),
            "jogos": db.session.query(Match).count(),
            "elencos": db.session.query(SquadMember).count(),
            "eventos": db.session.query(MatchEvent).count(),
        }


def test_importa_o_parquet_e_grava_todas_as_tabelas(tmp_path):
    _eventos().to_parquet(tmp_path / "BRA-Brasileirao_2024.parquet", index=False)
    app, cli = _app_e_cli()

    resultado = cli.invoke(args=["importar-brutos", "--pasta-brutos", str(tmp_path)])

    assert resultado.exit_code == 0, resultado.output
    assert _contagens(app) == {
        "competicoes": 1, "temporadas": 1, "times": 3, "jogadores": 4,
        "jogos": 2, "elencos": 4, "eventos": 5,
    }
    with app.app_context():
        jogos = {(j.game_id, j.home_team_id, j.away_team_id) for j in db.session.query(Match)}
    assert jogos == {(1, 10, 20), (2, 10, 30)}


def test_segunda_importacao_nao_duplica_nada(tmp_path):
    _eventos().to_parquet(tmp_path / "BRA-Brasileirao_2024.parquet", index=False)
    app, cli = _app_e_cli()

    cli.invoke(args=["importar-brutos", "--pasta-brutos", str(tmp_path)])
    antes = _contagens(app)
    resultado = cli.invoke(args=["importar-brutos", "--pasta-brutos", str(tmp_path)])

    assert resultado.exit_code == 0, resultado.output
    assert _contagens(app) == antes


def test_sem_colunas_de_mandante_o_jogo_sai_dos_times_que_aparecem(tmp_path):
    """Sem home_team_id e away_team_id, o primeiro time do jogo vira mandante e o segundo, visitante."""
    _eventos().drop(columns=["home_team_id", "away_team_id"]).to_parquet(
        tmp_path / "BRA-Brasileirao_2024.parquet", index=False
    )
    app, cli = _app_e_cli()

    cli.invoke(args=["importar-brutos", "--pasta-brutos", str(tmp_path)])

    with app.app_context():
        jogos = {(j.game_id, j.home_team_id, j.away_team_id) for j in db.session.query(Match)}
    assert jogos == {(1, 10, 20), (2, 10, 30)}


def test_pasta_sem_arquivos_avisa_e_nao_grava(tmp_path):
    app, cli = _app_e_cli()

    resultado = cli.invoke(args=["importar-brutos", "--pasta-brutos", str(tmp_path)])

    assert resultado.exit_code == 0
    assert "Nenhum arquivo encontrado" in resultado.output
    assert _contagens(app)["eventos"] == 0


def test_colunas_opcionais_ausentes_viram_nulas(tmp_path):
    """Sem player, player_id, end_x, end_y e original_event_id, os eventos entram com esses campos vazios."""
    eventos = _eventos().drop(columns=["player", "player_id", "end_x", "end_y", "original_event_id"])
    eventos["start_x"] = [None, 90.0, 30.0, 50.0, 60.0]
    eventos.to_parquet(tmp_path / "BRA-Brasileirao_2024.parquet", index=False)
    app, cli = _app_e_cli()

    resultado = cli.invoke(args=["importar-brutos", "--pasta-brutos", str(tmp_path)])

    assert resultado.exit_code == 0, resultado.output
    with app.app_context():
        evento = db.session.query(MatchEvent).filter_by(action_id=1).one()
        assert evento.player_id is None
        assert evento.end_x is None
        assert evento.original_event_id is None
        assert evento.start_x == 0.0  # campo vazio no arquivo vira 0.0
        assert db.session.query(MatchEvent).count() == 5
        assert db.session.query(Player).count() == 0
