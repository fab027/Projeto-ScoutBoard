"""Métricas por jogador e jogo a partir dos eventos SPADL.

Substitui o cálculo que gerou dashboard_final.parquet, que repetia cada
jogador-jogo dezenas de vezes. Aqui a chave é (temporada, game_id, player_id):
o nome do jogador não é usado como chave porque há homônimos na base.

Uso (a partir da raiz do projeto):
    python -m processamento.metricas
"""

import argparse

import pandas as pd

from socceraction.spadl import config as spadl

from config import DADOS_BRUTOS, METRICAS

TEMPORADAS = range(2019, 2026)
CHAVE = ["temporada", "game_id", "player_id"]
# Partidas duram no máximo ~3 tempos; eventos acima disso têm o tempo corrompido
# (ex.: time_seconds = 308855 no jogo 1621638 de 2022).
TEMPO_MAXIMO_S = 6000

ACOES = dict(enumerate(spadl.actiontypes))
RESULTADO_SUCESSO = spadl.results.index("success")
TIPO_PASSE = "pass"
TIPOS_FINALIZACAO = ["shot", "shot_penalty", "shot_freekick"]
TIPOS_GOLEIRO = ["keeper_save", "keeper_claim", "keeper_punch", "keeper_pick_up"]

# Nome da coluna de saída -> tipos SPADL que a compõem
CONTAGENS = {
    "desarmes": ["tackle"],
    "interceptacoes": ["interception"],
    "cortes": ["clearance"],
    "faltas": ["foul"],
    "dribles": ["take_on"],
    "finalizacoes": TIPOS_FINALIZACAO,
    "acoes_goleiro": TIPOS_GOLEIRO,
    "passes": [TIPO_PASSE],
}

# Padrão SPADL: 105.0 x 68.0 (altere MAX_X para 150.0 se tiver reescalado o campo)
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

    # Inverte start_x / end_x e start_y / end_y
    df.loc[mask, "start_x"] = MAX_X - df.loc[mask, "start_x"]
    df.loc[mask, "start_y"] = MAX_Y - df.loc[mask, "start_y"]

    if "end_x" in df.columns:
        mask_end_x = mask & df["end_x"].notna()
        df.loc[mask_end_x, "end_x"] = MAX_X - df.loc[mask_end_x, "end_x"]

    if "end_y" in df.columns:
        mask_end_y = mask & df["end_y"].notna()
        df.loc[mask_end_y, "end_y"] = MAX_Y - df.loc[mask_end_y, "end_y"]

    return df.drop(columns=["_dx"])

def sem_placeholders(eventos: pd.DataFrame) -> pd.DataFrame:
    """Remove eventos sem jogador real: id ausente, id 0 ou nome numérico ("0.0").

    O `--tolerante` do coleta/whoscored.py cria esses placeholders para suprir campos
    ausentes da Opta; eles não são jogadores e não podem entrar nos rankings.
    """
    nome_numerico = eventos["player"].astype(str).str.fullmatch(r"[0-9.]+")
    sem_id = eventos["player_id"].isna() | (eventos["player_id"] == 0)
    return eventos[~(sem_id | nome_numerico)]


def metricas_por_jogador_jogo(eventos: pd.DataFrame, temporada: int) -> pd.DataFrame:
    """Calcula uma linha por (game_id, player_id) a partir dos eventos de uma temporada."""
    e = sem_placeholders(eventos)
    e = e[e["time_seconds"] <= TEMPO_MAXIMO_S].copy()
    e["tipo"] = e["type_id"].map(ACOES)
    e["sucesso"] = e["result_id"] == RESULTADO_SUCESSO

    agrupado = e.groupby(["game_id", "player_id"])
    contagens = pd.crosstab([e["game_id"], e["player_id"]], e["tipo"])

    saida = pd.DataFrame(index=contagens.index)
    for coluna, tipos in CONTAGENS.items():
        saida[coluna] = contagens.reindex(columns=tipos, fill_value=0).sum(axis=1)

    passes = e[e["tipo"] == TIPO_PASSE].groupby(["game_id", "player_id"])["sucesso"].sum()
    saida["passes_certos"] = passes.reindex(saida.index, fill_value=0)

    gols = e[e["tipo"].isin(TIPOS_FINALIZACAO) & e["sucesso"]]
    saida["gols"] = gols.groupby(["game_id", "player_id"]).size().reindex(saida.index, fill_value=0)

    # Estimativa: intervalo entre o primeiro e o último evento do jogador na partida.
    tempo = agrupado["time_seconds"]
    saida["minutos_estimados"] = (tempo.max() - tempo.min()) / 60
    saida["acoes_totais"] = agrupado.size()
    saida["posicao_x"] = agrupado["start_x"].mean()
    saida["posicao_y"] = agrupado["start_y"].mean()
    saida["team_id"] = agrupado["team_id"].first()
    saida["player"] = agrupado["player"].first()

    saida = saida.reset_index()
    saida.insert(0, "temporada", str(temporada))
    return saida


def validar_chave_unica(tabela: pd.DataFrame) -> None:
    duplicadas = tabela.duplicated(subset=CHAVE).sum()
    if duplicadas:
        raise ValueError(f"{duplicadas} linhas repetidas para a chave {CHAVE}")


def construir_tabela(pasta_origem=DADOS_BRUTOS) -> pd.DataFrame:
    partes = []
    for ano in TEMPORADAS:
        eventos = pd.read_parquet(pasta_origem / f"BRA-Brasileirao_{ano}.parquet")
        partes.append(metricas_por_jogador_jogo(eventos, ano))
    tabela = pd.concat(partes, ignore_index=True)
    validar_chave_unica(tabela)
    return tabela


if __name__ == "__main__":
    argparse.ArgumentParser(description="Gera dados/metricas_jogador_jogo.parquet a partir de dados/brutos.").parse_args()
    tabela = construir_tabela()
    tabela.to_parquet(METRICAS, index=False)
    print(f"{len(tabela)} linhas gravadas em {METRICAS}")
