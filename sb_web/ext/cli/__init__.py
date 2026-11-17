"""Comando `importar-brutos`: grava no banco os eventos dos .parquet de dados/brutos.

As tabelas são preenchidas só com o que ainda não existe, então rodar de novo não duplica nada.
"""
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import click
import pandas as pd

from sb_web.analytics.models import MatchEvent
from sb_web.campeonato.models import Competition, Match, Player, Season, SquadMember, Team
from sb_web.ext.db import db

# Reconhece padrões como:
# - BRA-Brasileirao2019.parquet -> pais='BRA', liga='Brasileirao', temporada='2019'
# - ENG-PremierLeague2024-2025.parquet -> pais='ENG', liga='PremierLeague', temporada='2024-2025'
PADRAO_NOME_ARQUIVO = re.compile(
    r"^(?P<pais>[A-Za-z]{2,3})-(?P<liga>.+?)[-_]?(?P<temporada>(?:19|20)\d{2}(?:[-_](?:\d{2}|\d{4}))?)$"
)

# Colunas que podem faltar no arquivo; quando faltam, entram vazias e viram NULL no banco.
COLUNAS_OPCIONAIS = ["original_event_id", "end_x", "end_y", "player_id", "player"]
COLUNAS_EVENTO = [
    "action_id", "game_id", "team_id", "player_id", "period_id", "time_seconds", "original_event_id",
    "start_x", "start_y", "end_x", "end_y", "type_id", "result_id", "bodypart_id",
]
# Valores assumidos quando o evento não traz o campo.
PERIODO_PADRAO = 1
VALOR_PADRAO = 0


def extrair_metadados_arquivo(stem: str):
    """Extrai (pais, liga, temporada) a partir do nome base do arquivo .parquet."""
    match = PADRAO_NOME_ARQUIVO.match(stem.strip())
    if not match:
        return None
    pais = match.group("pais").upper()
    liga = match.group("liga").strip("_- ")
    temporada = match.group("temporada").replace("_", "-")
    return pais, liga, temporada


def _eh_nulo(val) -> bool:
    return val is None or (isinstance(val, float) and math.isnan(val)) or pd.isna(val)


def _int_opcional(val):
    return None if _eh_nulo(val) else int(val)


def _int_ou(val, padrao: int) -> int:
    return padrao if _eh_nulo(val) else int(val)


def _float_opcional(val):
    return None if _eh_nulo(val) else float(val)


def _float_ou(val, padrao: float) -> float:
    return padrao if _eh_nulo(val) else float(val)


def _str_opcional(val):
    if _eh_nulo(val):
        return None
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)


@dataclass
class _JaNoBanco:
    """IDs que já estão gravados, para não inserir de novo nem consultar o banco a cada linha."""

    times: set = field(default_factory=set)
    jogadores: set = field(default_factory=set)
    jogos: set = field(default_factory=set)
    elencos: set = field(default_factory=set)
    jogos_com_eventos: set = field(default_factory=set)

    @classmethod
    def carregar(cls) -> "_JaNoBanco":
        return cls(
            times=set(db.session.scalars(db.select(Team.team_id)).all()),
            jogadores=set(db.session.scalars(db.select(Player.player_id)).all()),
            jogos=set(db.session.scalars(db.select(Match.game_id)).all()),
            elencos=set(db.session.execute(
                db.select(SquadMember.temporada_id, SquadMember.team_id, SquadMember.player_id)
            ).all()),
            jogos_com_eventos=set(db.session.scalars(db.select(MatchEvent.game_id).distinct()).all()),
        )


def _garantir_temporada(pais: str, liga: str, temporada_str: str) -> Season:
    competicao = db.session.scalar(db.select(Competition).filter_by(pais=pais, liga=liga))
    if not competicao:
        competicao = Competition(pais=pais, liga=liga)
        db.session.add(competicao)
        db.session.flush()

    temporada = db.session.scalar(
        db.select(Season).filter_by(competicao_id=competicao.id, temporada=temporada_str)
    )
    if not temporada:
        temporada = Season(competicao_id=competicao.id, temporada=temporada_str)
        db.session.add(temporada)
        db.session.flush()
    return temporada


def _ler_eventos(arquivo: Path) -> pd.DataFrame:
    df = pd.read_parquet(arquivo)
    if not {"game_id", "action_id"}.issubset(df.columns):
        df = df.reset_index()
    for coluna in COLUNAS_OPCIONAIS:
        if coluna not in df.columns:
            df[coluna] = None
    return df.dropna(subset=["game_id", "team_id", "action_id"])


def _inserir_nomes(modelo, df: pd.DataFrame, coluna_id: str, coluna_nome: str, prefixo: str,
                   existentes: set) -> None:
    """Times e jogadores: uma linha por id, com o nome que aparece por último no arquivo."""
    por_id = df[[coluna_id, coluna_nome]].dropna(subset=[coluna_id]).drop_duplicates(
        subset=[coluna_id], keep="last"
    )
    novos = []
    for id_bruto, nome in zip(por_id[coluna_id].tolist(), por_id[coluna_nome].tolist()):
        id_int = int(id_bruto)
        if id_int in existentes:
            continue
        nome_limpo = str(nome).strip() if not _eh_nulo(nome) else f"{prefixo} {id_int}"
        novos.append({coluna_id: id_int, coluna_nome: nome_limpo})
        existentes.add(id_int)
    if novos:
        db.session.execute(db.insert(modelo), novos)


def _pares_mandante_visitante(df: pd.DataFrame) -> list[tuple[int, int, int]]:
    """(game_id, mandante, visitante) de cada jogo. Sem as colunas de mandante e visitante, o primeiro
    time que aparece no jogo é o mandante e o segundo é o visitante."""
    if {"home_team_id", "away_team_id"}.issubset(df.columns):
        por_jogo = df[["game_id", "home_team_id", "away_team_id"]].drop_duplicates(subset=["game_id"])
        return [
            (int(g), int(h), int(a))
            for g, h, a in zip(por_jogo["game_id"].tolist(), por_jogo["home_team_id"].tolist(),
                               por_jogo["away_team_id"].tolist())
        ]
    pares = []
    for game_id, times_do_jogo in df.groupby("game_id", sort=False)["team_id"]:
        unicos = times_do_jogo.unique()
        mandante = int(unicos[0])
        visitante = int(unicos[1]) if len(unicos) > 1 else mandante
        pares.append((int(game_id), mandante, visitante))
    return pares


def _inserir_jogos(df: pd.DataFrame, temporada_id: int, existentes: set) -> None:
    novos = [
        {"game_id": g, "temporada_id": temporada_id, "home_team_id": h, "away_team_id": a}
        for g, h, a in _pares_mandante_visitante(df)
        if g not in existentes
    ]
    existentes.update(jogo["game_id"] for jogo in novos)
    if novos:
        db.session.execute(db.insert(Match), novos)


def _inserir_elencos(df: pd.DataFrame, temporada_id: int, existentes: set) -> None:
    """Quem jogou por cada time na temporada. Um atleta pode aparecer em dois clubes no mesmo ano."""
    por_elenco = df[["team_id", "player_id"]].dropna(subset=["team_id", "player_id"]).drop_duplicates()
    novos = []
    for t_id, p_id in zip(por_elenco["team_id"].tolist(), por_elenco["player_id"].tolist()):
        chave = (temporada_id, int(t_id), int(p_id))
        if chave not in existentes:
            novos.append({"temporada_id": temporada_id, "team_id": int(t_id), "player_id": int(p_id)})
            existentes.add(chave)
    if novos:
        db.session.execute(db.insert(SquadMember), novos)


def _linha_evento(registro: dict) -> dict:
    return {
        "action_id": int(registro["action_id"]),
        "game_id": int(registro["game_id"]),
        "team_id": int(registro["team_id"]),
        "player_id": _int_opcional(registro["player_id"]),
        "period_id": _int_ou(registro["period_id"], PERIODO_PADRAO),
        "time_seconds": _float_ou(registro["time_seconds"], 0.0),
        "original_event_id": _str_opcional(registro["original_event_id"]),
        "start_x": _float_ou(registro["start_x"], 0.0),
        "start_y": _float_ou(registro["start_y"], 0.0),
        "end_x": _float_opcional(registro["end_x"]),
        "end_y": _float_opcional(registro["end_y"]),
        "type_id": _int_ou(registro["type_id"], VALOR_PADRAO),
        "result_id": _int_ou(registro["result_id"], VALOR_PADRAO),
        "bodypart_id": _int_ou(registro["bodypart_id"], VALOR_PADRAO),
    }


def _inserir_eventos(df: pd.DataFrame, jogos_com_eventos: set, tamanho_lote: int) -> int:
    """Grava os eventos dos jogos que ainda não têm nenhum no banco. Devolve quantos entraram."""
    df_eventos = df[~df["game_id"].astype(int).isin(jogos_com_eventos)].drop_duplicates(
        subset=["game_id", "action_id"], keep="first"
    )
    total = len(df_eventos)
    for inicio in range(0, total, tamanho_lote):
        fatia = df_eventos.iloc[inicio: inicio + tamanho_lote]
        lote = [_linha_evento(registro) for registro in fatia[COLUNAS_EVENTO].to_dict("records")]
        db.session.execute(db.insert(MatchEvent), lote)
        db.session.commit()
    if total:
        jogos_com_eventos.update(df_eventos["game_id"].astype(int).unique().tolist())
    return total


def importar_brutos(pasta_brutos: str, padrao: str, tamanho_lote: int) -> None:
    """Extrai país, liga e temporada do nome do .parquet e popula o banco relacional."""
    click.echo("1. Garantindo a estrutura de tabelas no banco de dados...")
    db.create_all()

    dir_brutos = Path(pasta_brutos)
    arquivos = sorted(dir_brutos.glob(padrao))
    if not arquivos:
        click.secho(f"Nenhum arquivo encontrado em '{dir_brutos}' com o padrão '{padrao}'.", fg="red")
        return

    existentes = _JaNoBanco.carregar()
    total_eventos = 0

    for arquivo in arquivos:
        metadados = extrair_metadados_arquivo(arquivo.stem)
        if not metadados:
            click.secho(
                f"   [Ignorado] '{arquivo.name}' fora do padrão <PAIS>-<Liga><Temporada>.parquet.",
                fg="yellow",
            )
            continue

        pais, liga, temporada_str = metadados
        click.echo(
            f"\n2. Processando '{arquivo.name}' -> País: {pais} | Liga: {liga} | Temporada: {temporada_str}"
        )
        temporada = _garantir_temporada(pais, liga, temporada_str)
        df = _ler_eventos(arquivo)

        _inserir_nomes(Team, df, "team_id", "team", "Time", existentes.times)
        _inserir_nomes(Player, df, "player_id", "player", "Jogador", existentes.jogadores)
        _inserir_jogos(df, temporada.id, existentes.jogos)
        _inserir_elencos(df, temporada.id, existentes.elencos)
        db.session.commit()

        qtd_eventos = _inserir_eventos(df, existentes.jogos_com_eventos, tamanho_lote)
        if qtd_eventos == 0:
            click.echo("   -> Eventos desta temporada já constam no banco. Pulando inserção.")
            continue
        total_eventos += qtd_eventos
        click.secho(f"   -> {qtd_eventos} eventos gravados de '{arquivo.name}'.", fg="cyan")

    click.secho(
        f"\nImportação concluída! Total no banco: {len(existentes.times)} clubes, "
        f"{len(existentes.jogadores)} jogadores, {len(existentes.jogos)} partidas e "
        f"{total_eventos} novos eventos inseridos.",
        fg="green",
    )


def init_app(app):
    @app.cli.command("importar-brutos")
    @click.option(
        "--pasta-brutos",
        default="dados/brutos",
        show_default=True,
        help="Diretório onde estão os arquivos .parquet brutos.",
    )
    @click.option(
        "--padrao",
        default="BRA-Brasileirao_20*.parquet",
        show_default=True,
        help="Filtro glob dos arquivos a importar (ex: '*.parquet' para todas as ligas).",
    )
    @click.option(
        "--tamanho-lote",
        default=25000,
        show_default=True,
        help="Quantidade de eventos inseridos por transação no banco.",
    )
    def comando(pasta_brutos, padrao, tamanho_lote):
        """Extrai país, liga e temporada do nome do .parquet e popula o banco relacional."""
        importar_brutos(pasta_brutos, padrao, tamanho_lote)
