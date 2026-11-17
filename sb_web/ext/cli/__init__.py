import math
import re
from pathlib import Path
import click
import pandas as pd
from sb_web.ext.db import db
from sb_web.campeonato.models import (
    Competition,
    Season,
    Team,
    Player,
    SquadMember,
    Match,
)
from sb_web.analytics.models import MatchEvent

# Reconhece padrões como:
# - BRA-Brasileirao2019.parquet -> pais='BRA', liga='Brasileirao', temporada='2019'
# - ENG-PremierLeague2024-2025.parquet -> pais='ENG', liga='PremierLeague', temporada='2024-2025'
PADRAO_NOME_ARQUIVO = re.compile(
    r"^(?P<pais>[A-Za-z]{2,3})-(?P<liga>.+?)[-_]?(?P<temporada>(?:19|20)\d{2}(?:[-_](?:\d{2}|\d{4}))?)$"
)


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


def _float_opcional(val):
    return None if _eh_nulo(val) else float(val)


def _str_opcional(val):
    if _eh_nulo(val):
        return None
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)


# Dimensões do campo no padrão SPADL (metros); a orientação dos times usa essas medidas.
MAX_X = 105.0
MAX_Y = 68.0


def normalizar_orientacao_spadl(df: pd.DataFrame) -> pd.DataFrame:
    """
    Garante que todos os times ataquem sempre da esquerda para a direita (0 -> MAX_X)
    em todas as partidas, invertendo X e Y quando o time ataca de MAX_X -> 0.
    """
    df = df.copy()
    chaves = ["game_id", "team_id"]
    if "period_id" in df.columns:
        chaves.append("period_id")

    # 1. Critério principal: média de start_x das finalizações (type_id == 11)
    chutes = df[df["type_id"] == 11].groupby(chaves)["start_x"].mean()
    ataca_para_esquerda = chutes < (MAX_X / 2.0)

    # 2. Fallback (caso um time não tenha finalizado no período): avanço médio dos passes (dx < 0)
    df["_dx"] = df["end_x"] - df["start_x"]
    passes_dx = df[df["type_id"] == 0].groupby(chaves)["_dx"].mean()
    sem_chute_invertido = passes_dx < 0

    # Combina os dois critérios (priorizando a direção das finalizações)
    inverter_grupo = ataca_para_esquerda.reindex(passes_dx.index).fillna(sem_chute_invertido)
    grupos_invertidos = inverter_grupo[inverter_grupo].index

    # Cria máscara booleana para as linhas que precisam de inversão
    mask = df.set_index(chaves).index.isin(grupos_invertidos)

# Inverte start_x e end_x apenas nos jogos com direção 105 -> 0 (mask)
    df.loc[mask, "start_x"] = MAX_X - df.loc[mask, "start_x"]
    if "end_x" in df.columns:
        mask_end_x = mask & df["end_x"].notna()
        df.loc[mask_end_x, "end_x"] = MAX_X - df.loc[mask_end_x, "end_x"]

    # Espelha start_y e end_y nos jogos de direção 0 -> 105 (~mask) para corrigir os lados do campo
    df.loc[~mask, "start_y"] = MAX_Y - df.loc[~mask, "start_y"]
    if "end_y" in df.columns:
        mask_end_y = (~mask) & df["end_y"].notna()
        df.loc[mask_end_y, "end_y"] = MAX_Y - df.loc[mask_end_y, "end_y"]

    return df.drop(columns=["_dx"])     


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
    def importar_brutos(pasta_brutos, padrao, tamanho_lote):
        """Extrai país, liga e temporada do nome do .parquet e popula o banco relacional."""
        click.echo("1. Garantindo a estrutura de tabelas no banco de dados...")
        db.create_all()

        dir_brutos = Path(pasta_brutos)
        arquivos = sorted(dir_brutos.glob(padrao))
        if not arquivos:
            click.secho(
                f"Nenhum arquivo encontrado em '{dir_brutos}' com o padrão '{padrao}'.",
                fg="red",
            )
            return

        # Caches em memória dos IDs já persistidos para evitar consultas repetidas e duplicações
        times_existentes = set(db.session.scalars(db.select(Team.team_id)).all())
        jogadores_existentes = set(db.session.scalars(db.select(Player.player_id)).all())
        jogos_existentes = set(db.session.scalars(db.select(Match.game_id)).all())
        elencos_existentes = set(
            db.session.execute(
                db.select(SquadMember.temporada_id, SquadMember.team_id, SquadMember.player_id)
            ).all()
        )
        jogos_com_eventos = set(
            db.session.scalars(db.select(MatchEvent.game_id).distinct()).all()
        )

        total_eventos_importados = 0

        for arq in arquivos:
            metadados = extrair_metadados_arquivo(arq.stem)
            if not metadados:
                click.secho(
                    f"   [Ignorado] '{arq.name}' fora do padrão <PAIS>-<Liga><Temporada>.parquet.",
                    fg="yellow",
                )
                continue

            pais, liga, temporada_str = metadados
            click.echo(
                f"\n2. Processando '{arq.name}' -> País: {pais} | Liga: {liga} | Temporada: {temporada_str}"
            )

            # 2.1 Competição (competicoes)
            competicao = db.session.scalar(
                db.select(Competition).filter_by(pais=pais, liga=liga)
            )
            if not competicao:
                competicao = Competition(pais=pais, liga=liga)
                db.session.add(competicao)
                db.session.flush()

            # 2.2 Temporada (temporadas)
            temporada = db.session.scalar(
                db.select(Season).filter_by(
                    competicao_id=competicao.id, temporada=temporada_str
                )
            )
            if not temporada:
                temporada = Season(competicao_id=competicao.id, temporada=temporada_str)
                db.session.add(temporada)
                db.session.flush()

            # Leitura do Parquet e garantia de colunas caso game_id/action_id estejam no índice
            df = pd.read_parquet(arq)
            if not {"game_id", "action_id"}.issubset(df.columns):
                df = df.reset_index()

            for col_opc in ["original_event_id", "end_x", "end_y", "player_id", "player"]:
                if col_opc not in df.columns:
                    df[col_opc] = None
                    
            

            df = df.dropna(subset=["game_id", "team_id", "action_id"])

            # 2.3 Times únicos pelo team_id (times)
            df_times = (
                df[["team_id", "team"]]
                .dropna(subset=["team_id"])
                .drop_duplicates(subset=["team_id"], keep="last")
            )
            novos_times = []
            for t_id, t_nome in zip(df_times["team_id"].tolist(), df_times["team"].tolist()):
                tid_int = int(t_id)
                if tid_int not in times_existentes:
                    nome_limpo = str(t_nome).strip() if not _eh_nulo(t_nome) else f"Time {tid_int}"
                    novos_times.append({"team_id": tid_int, "team": nome_limpo})
                    times_existentes.add(tid_int)
            if novos_times:
                db.session.execute(db.insert(Team), novos_times)

            # 2.4 Jogadores únicos pelo player_id — preserva homônimos e evita duplicar transferidos
            df_jogadores = (
                df[["player_id", "player"]]
                .dropna(subset=["player_id"])
                .drop_duplicates(subset=["player_id"], keep="last")
            )
            novos_jogadores = []
            for p_id, p_nome in zip(
                df_jogadores["player_id"].tolist(), df_jogadores["player"].tolist()
            ):
                pid_int = int(p_id)
                if pid_int not in jogadores_existentes:
                    nome_limpo = (
                        str(p_nome).strip() if not _eh_nulo(p_nome) else f"Jogador {pid_int}"
                    )
                    novos_jogadores.append({"player_id": pid_int, "player": nome_limpo})
                    jogadores_existentes.add(pid_int)
            if novos_jogadores:
                db.session.execute(db.insert(Player), novos_jogadores)

            # 2.5 Jogos da temporada (jogos)
            novos_jogos = []
            if {"home_team_id", "away_team_id"}.issubset(df.columns):
                df_jogos = df[["game_id", "home_team_id", "away_team_id"]].drop_duplicates(
                    subset=["game_id"]
                )
                for g_id, h_id, a_id in zip(
                    df_jogos["game_id"].tolist(),
                    df_jogos["home_team_id"].tolist(),
                    df_jogos["away_team_id"].tolist(),
                ):
                    gid_int = int(g_id)
                    if gid_int not in jogos_existentes:
                        novos_jogos.append(
                            {
                                "game_id": gid_int,
                                "temporada_id": temporada.id,
                                "home_team_id": int(h_id),
                                "away_team_id": int(a_id),
                            }
                        )
                        jogos_existentes.add(gid_int)
            else:
                for g_id, times_jogo in df.groupby("game_id", sort=False)["team_id"]:
                    gid_int = int(g_id)
                    if gid_int not in jogos_existentes:
                        unicos = times_jogo.unique()
                        home_id = int(unicos[0])
                        away_id = int(unicos[1]) if len(unicos) > 1 else home_id
                        novos_jogos.append(
                            {
                                "game_id": gid_int,
                                "temporada_id": temporada.id,
                                "home_team_id": home_id,
                                "away_team_id": away_id,
                            }
                        )
                        jogos_existentes.add(gid_int)
            if novos_jogos:
                db.session.execute(db.insert(Match), novos_jogos)

            # 2.6 Elencos na temporada (elencos_temporada) — suporta atletas em 2+ clubes no mesmo ano
            df_elencos = (
                df[["team_id", "player_id"]]
                .dropna(subset=["team_id", "player_id"])
                .drop_duplicates()
            )
            novos_elencos = []
            for t_id, p_id in zip(
                df_elencos["team_id"].tolist(), df_elencos["player_id"].tolist()
            ):
                chave_elenco = (temporada.id, int(t_id), int(p_id))
                if chave_elenco not in elencos_existentes:
                    novos_elencos.append(
                        {
                            "temporada_id": temporada.id,
                            "team_id": int(t_id),
                            "player_id": int(p_id),
                        }
                    )
                    elencos_existentes.add(chave_elenco)
            if novos_elencos:
                db.session.execute(db.insert(SquadMember), novos_elencos)

            db.session.commit()

            # 2.7 Eventos da partida (eventos_partida) — ignora jogos já importados anteriormente
            df_ev = df[~df["game_id"].astype(int).isin(jogos_com_eventos)].drop_duplicates(
                subset=["game_id", "action_id"], keep="first"
            )
            qtd_eventos_arq = len(df_ev)
            if qtd_eventos_arq == 0:
                click.echo("   -> Eventos desta temporada já constam no banco. Pulando inserção.")
                continue

            for inicio in range(0, qtd_eventos_arq, tamanho_lote):
                fatia = df_ev.iloc[inicio : inicio + tamanho_lote]
                lote_dicts = [
                    {
                        "action_id": int(act_id),
                        "game_id": int(g_id),
                        "team_id": int(t_id),
                        "player_id": _int_opcional(p_id),
                        "period_id": 1 if _eh_nulo(per_id) else int(per_id),
                        "time_seconds": 0.0 if _eh_nulo(t_sec) else float(t_sec),
                        "original_event_id": _str_opcional(orig_id),
                        "start_x": 0.0 if _eh_nulo(sx) else float(sx),
                        "start_y": 0.0 if _eh_nulo(sy) else float(sy),
                        "end_x": _float_opcional(ex),
                        "end_y": _float_opcional(ey),
                        "type_id": 0 if _eh_nulo(tp_id) else int(tp_id),
                        "result_id": 0 if _eh_nulo(res_id) else int(res_id),
                        "bodypart_id": 0 if _eh_nulo(bp_id) else int(bp_id),
                    }
                    for (
                        act_id, g_id, t_id, p_id, per_id, t_sec,
                        orig_id, sx, sy, ex, ey, tp_id, res_id, bp_id
                    ) in zip(
                        fatia["action_id"].tolist(),
                        fatia["game_id"].tolist(),
                        fatia["team_id"].tolist(),
                        fatia["player_id"].tolist(),
                        fatia["period_id"].tolist(),
                        fatia["time_seconds"].tolist(),
                        fatia["original_event_id"].tolist(),
                        fatia["start_x"].tolist(),
                        fatia["start_y"].tolist(),
                        fatia["end_x"].tolist(),
                        fatia["end_y"].tolist(),
                        fatia["type_id"].tolist(),
                        fatia["result_id"].tolist(),
                        fatia["bodypart_id"].tolist(),
                    )
                ]
                db.session.execute(db.insert(MatchEvent), lote_dicts)
                db.session.commit()

            jogos_com_eventos.update(df_ev["game_id"].astype(int).unique().tolist())
            total_eventos_importados += qtd_eventos_arq
            click.secho(f"   -> {qtd_eventos_arq} eventos gravados de '{arq.name}'.", fg="cyan")

        click.secho(
            f"\nImportação concluída! Total no banco: {len(times_existentes)} clubes, "
            f"{len(jogadores_existentes)} jogadores, {len(jogos_existentes)} partidas e "
            f"{total_eventos_importados} novos eventos inseridos.",
            fg="green",
        )