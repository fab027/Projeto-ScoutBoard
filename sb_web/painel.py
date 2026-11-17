"""Cálculos do painel a partir de metricas_jogador_jogo e treinadores.

Todas as funções são puras: recebem DataFrames e devolvem listas de dicionários
prontos para JSON. As rotas Flask ficam em rotas.py.

Limitações conhecidas:
- Gols são os chutes com resultado "success" (o dado não separa gol de gol contra).
- Minutos são estimados pelo intervalo entre o primeiro e o último evento do jogador.
- Pontuação de times é derivada dos gols dos jogos presentes na base.
- Escudos e fotos vêm do Wikimedia Commons e da CBF pelas rotas /escudo e /foto (rotas.py);
  se nenhuma fonte tiver a imagem, a página mostra as iniciais ou um distintivo.
"""
import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from config import DADOS
from coleta.nomes import normalizar

METRICAS_RANKING = {
    "gols": "Gols",
    "passes_certos": "Passes certos",
    "desarmes": "Desarmes",
    "interceptacoes": "Interceptações",
    "finalizacoes": "Finalizações",
    "dribles": "Dribles",
    "cortes": "Cortes",
    "acoes_totais": "Ações",
}
METRICAS_DISPERSAO = dict(METRICAS_RANKING)
PREMIOS = [
    ("Artilheiro", "gols"),
    ("Mais passes certos", "passes_certos"),
    ("Mais desarmes", "desarmes"),
    ("Mais interceptações", "interceptacoes"),
]
MINIMO_MINUTOS_PADRAO = 90
MINIMO_MINUTOS_PERCENTIL = 450  # cinco jogos inteiros: abaixo disso o "por 90 minutos" engana
LIMITE_PAGINA = 50
COMPRIMENTO_CAMPO = 105.0
LARGURA_CAMPO = 68.0


@dataclass
class Dados:
    """Tabelas carregadas uma vez por processo, com os recortes que não mudam entre requisições."""

    metricas: pd.DataFrame
    treinadores: pd.DataFrame
    nomes: dict
    divergencias: list | None = None
    temporadas: list = field(init=False)
    _por_temporada: dict = field(init=False, repr=False)
    _jogos: dict = field(init=False, repr=False, default_factory=dict)
    _agregados: dict = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self):
        self._por_temporada = dict(tuple(self.metricas.groupby("temporada", sort=True)))
        self.temporadas = list(self._por_temporada)

    def temporada(self, temporada: str) -> pd.DataFrame:
        """Linhas da temporada; ValueError se ela não existe na base."""
        if temporada not in self._por_temporada:
            raise ValueError(f"Temporada inválida: {temporada}")
        return self._por_temporada[temporada]

    def jogos(self, temporada: str) -> list:
        if temporada not in self._jogos:
            self._jogos[temporada] = opcoes_jogos(self.temporada(temporada), self.nomes)
        return self._jogos[temporada]

    def agregado(self, temporada: str) -> pd.DataFrame:
        """Soma por jogador da temporada inteira, o recorte mais pedido. Não altere o resultado."""
        if temporada not in self._agregados:
            self._agregados[temporada] = agregar_jogadores(self.temporada(temporada), self.nomes)
        return self._agregados[temporada]

    @cached_property
    def ultimos(self) -> pd.DataFrame:
        """Linha mais recente de cada jogador, com o nome já normalizado para a busca."""
        ultimo = self.metricas.sort_values("temporada").drop_duplicates("player_id", keep="last")
        ultimo = ultimo[["player_id", "player", "team_id", "temporada"]]
        return ultimo.assign(nome_normalizado=ultimo["player"].map(normalizar))

    @cached_property
    def treinadores_normalizados(self) -> pd.Series:
        return self.treinadores["treinador"].map(normalizar)

    @cached_property
    def fotos_treinadores(self) -> dict:
        """Nome normalizado do técnico -> arquivo da foto dele no Wikimedia Commons.

        A coluna `foto` vem da coleta de técnicos (P18 do Wikidata); um treinadores.parquet
        gravado antes dela não tem fotos, até a próxima coleta.
        """
        if "foto" not in self.treinadores:
            return {}
        com_foto = self.treinadores[self.treinadores["foto"].fillna("").astype(bool)]
        return dict(zip(com_foto["treinador"].map(normalizar), com_foto["foto"]))

    def times(self, temporada: str) -> list:
        return [
            {"team_id": int(t), "time": self.nomes.get(int(t), f"Time {t}")}
            for t in sorted(self.temporada(temporada)["team_id"].unique())
        ]


def _normalizar_posicoes(metricas: pd.DataFrame) -> pd.DataFrame:
    """Garante que todos os times ataquem da esquerda para a direita (0 -> 105) em cada jogo."""
    df = metricas.copy()
    validos = df.dropna(subset=["posicao_x", "posicao_y"]).copy()
    if validos.empty:
        return df

    # Pesos ofensivos e defensivos para achar a direção de ataque do time na partida
    validos["_peso_atq"] = (
        validos["finalizacoes"] * 3 + validos["gols"] * 5 + validos["dribles"] * 2
    )
    validos["_peso_def"] = (
        validos["cortes"] * 3 + validos["interceptacoes"] + validos["desarmes"]
    )
    validos["_x_atq"] = validos["posicao_x"] * validos["_peso_atq"]
    validos["_x_def"] = validos["posicao_x"] * validos["_peso_def"]

    g = validos.groupby(["game_id", "team_id"])
    resumo = g.agg(
        soma_x_atq=("_x_atq", "sum"),
        soma_peso_atq=("_peso_atq", "sum"),
        soma_x_def=("_x_def", "sum"),
        soma_peso_def=("_peso_def", "sum"),
        min_x=("posicao_x", "min"),
        max_x=("posicao_x", "max"),
    )

    x_atq = resumo["soma_x_atq"] / resumo["soma_peso_atq"].where(resumo["soma_peso_atq"] > 0)
    x_def = resumo["soma_x_def"] / resumo["soma_peso_def"].where(resumo["soma_peso_def"] > 0)

    # Se o ataque médio está à esquerda da defesa média (x_atq < x_def), o time ataca de 105 -> 0.
    # Fallback pela posição do goleiro/extremos caso falte ação ofensiva/defensiva registrada.
    meio_extremos = (resumo["min_x"] + resumo["max_x"]) / 2.0
    invertido = (x_atq < x_def).where(
        x_atq.notna() & x_def.notna(),
        meio_extremos > (COMPRIMENTO_CAMPO / 2.0),
    )

    chaves_invertidas = invertido[invertido].index
    mask = df.set_index(["game_id", "team_id"]).index.isin(chaves_invertidas)

    # Inverte o X nos jogos em que o time atacou de 105 -> 0
    df.loc[mask, "posicao_x"] = COMPRIMENTO_CAMPO - df.loc[mask, "posicao_x"]

    # Espelha o Y nos demais jogos (~mask) para alinhar esquerda e direita com o campo visual
    df.loc[~mask, "posicao_y"] = LARGURA_CAMPO - df.loc[~mask, "posicao_y"]
    return df


def carregar(pasta: Path = DADOS) -> Dados:
    """Lê as tabelas geradas pela coleta e pelo processamento a partir de `pasta`."""
    metricas = pd.read_parquet(pasta / "metricas_jogador_jogo.parquet")
    metricas["team_id"] = metricas["team_id"].astype(int)
    metricas["player_id"] = metricas["player_id"].astype(int)
    metricas = _normalizar_posicoes(metricas)

    treinadores = pd.read_parquet(pasta / "treinadores.parquet")
    treinadores["team_id"] = treinadores["team_id"].astype(int)

    nomes_times = pd.read_csv(pasta / "treinadores_times.csv", dtype=str)
    nomes = dict(zip(nomes_times["team_id"].astype(int), nomes_times["time_base"]))
    status_arquivo = pasta / "treinadores_status.json"
    status = json.loads(status_arquivo.read_text(encoding="utf-8")) if status_arquivo.exists() else {}
    return Dados(metricas, treinadores, nomes, status.get("conflitos", []))


def _json_registros(df: pd.DataFrame) -> list:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _com_imagens(registros: list, temporada: str | None = None) -> list:
    """Acrescenta o endereço da foto (por player_id) e do escudo (por team_id), servidos por rotas.py.

    A temporada vai no endereço para que só ela seja consultada nas fontes externas; sem ela,
    vale a do próprio registro (busca) ou a mais recente na base.
    """
    for registro in registros:
        ano = temporada or registro.get("temporada")
        sufixo = f"?temporada={ano}" if ano else ""
        if "player_id" in registro:
            registro["foto"] = f"/foto/jogador/{registro['player_id']}{sufixo}"
        if "team_id" in registro:
            registro["escudo"] = f"/escudo/{registro['team_id']}{sufixo}"
    return registros


def agregar_jogadores(f: pd.DataFrame, nomes: dict) -> pd.DataFrame:
    """Soma as métricas de cada jogador no recorte e calcula a posição média ponderada."""
    f = f.assign(
        _px=f["posicao_x"] * f["acoes_totais"],
        _py=f["posicao_y"] * f["acoes_totais"],
    )
    g = f.groupby("player_id")
    colunas = list(METRICAS_RANKING)
    agg = g.agg(
        player=("player", "last"),
        team_id=("team_id", "last"),
        jogos=("game_id", "nunique"),
        minutos=("minutos_estimados", "sum"),
        **{c: (c, "sum") for c in colunas},
    )
    acoes = agg["acoes_totais"].where(agg["acoes_totais"] > 0)
    agg["posicao_x"] = g["_px"].sum() / acoes
    agg["posicao_y"] = g["_py"].sum() / acoes
    agg["time"] = agg["team_id"].map(nomes)
    return agg.reset_index()


def ranking_jogadores(agg: pd.DataFrame, metrica: str, limite: int = 10) -> list:
    ordenado = agg.sort_values([metrica, "minutos"], ascending=False).head(limite)
    return _json_registros(ordenado[["player_id", "player", "team_id", "time", "jogos", metrica]])


def artilharia(dados: "Dados", temporada: str, limite: int = 10) -> list:
    """Artilharia da temporada pela base, com o clube em que o jogador estava naquele ano.

    Mais completa que a lista da CBF, que deixa de fora quem saiu do futebol brasileiro
    (em 2020, Claudinho, Thiago Galhardo e Marinho) e mostra o clube atual de cada um.
    Desempate: menos jogos.
    """
    agg = dados.agregado(temporada)
    topo = agg[agg["gols"] > 0].sort_values(["gols", "jogos"], ascending=[False, True]).head(limite)
    registros = _json_registros(topo[["player_id", "player", "team_id", "time", "jogos", "gols"]])
    return _com_imagens(registros, temporada)


def lista_jogadores(agg: pd.DataFrame) -> list:
    colunas = ["player_id", "player", "team_id", "time", "jogos", "minutos", *METRICAS_RANKING]
    return _json_registros(agg.sort_values("acoes_totais", ascending=False)[colunas])


def ranking_times(f: pd.DataFrame, nomes: dict) -> list:
    """Tabela de times a partir dos gols de cada lado nos jogos do recorte (3 pontos por vitória)."""
    jogos = f.groupby(["game_id", "team_id"], as_index=False)["gols"].sum()
    jogos["n_times"] = jogos.groupby("game_id")["team_id"].transform("size")
    jogos = jogos[jogos["n_times"] == 2].copy()
    total = jogos.groupby("game_id")["gols"].transform("sum")
    jogos["sofridos"] = total - jogos["gols"]
    jogos["vitorias"] = (jogos["gols"] > jogos["sofridos"]).astype(int)
    jogos["empates"] = (jogos["gols"] == jogos["sofridos"]).astype(int)
    jogos["pontos"] = 3 * jogos["vitorias"] + jogos["empates"]

    tabela = jogos.groupby("team_id").agg(
        jogos=("game_id", "nunique"),
        vitorias=("vitorias", "sum"),
        empates=("empates", "sum"),
        pontos=("pontos", "sum"),
        gols_pro=("gols", "sum"),
        gols_contra=("sofridos", "sum"),
    ).reset_index()
    tabela["derrotas"] = tabela["jogos"] - tabela["vitorias"] - tabela["empates"]
    tabela["saldo"] = tabela["gols_pro"] - tabela["gols_contra"]
    tabela["time"] = tabela["team_id"].map(nomes)
    tabela = tabela.sort_values(["pontos", "saldo", "gols_pro"], ascending=False)
    return _json_registros(tabela)


def premios(agg: pd.DataFrame) -> list:
    saida = []
    if agg.empty:
        return saida
    for titulo, metrica in PREMIOS:
        topo = agg.sort_values([metrica, "minutos"], ascending=False).iloc[0]
        saida.append(
            {
                "titulo": titulo,
                "metrica": metrica,
                "player_id": int(topo["player_id"]),
                "player": topo["player"],
                "team_id": int(topo["team_id"]),
                "time": topo["time"],
                "valor": int(topo[metrica]),
            }
        )
    return saida


def dispersao(agg: pd.DataFrame, x: str, y: str, minimo_minutos: float) -> list:
    """Valores por 90 minutos, para comparar jogadores com tempos de jogo diferentes."""
    d = agg[(agg["minutos"] > 0) & (agg["minutos"] >= minimo_minutos)].copy()
    fator = 90 / d["minutos"]
    d["x"] = d[x] * fator
    d["y"] = d[y] * fator
    return _json_registros(d[["player_id", "player", "team_id", "time", "x", "y"]])


def posicoes(agg: pd.DataFrame) -> list:
    colunas = ["player_id", "player", "team_id", "time", "posicao_x", "posicao_y", "acoes_totais"]
    return _json_registros(agg.dropna(subset=["posicao_x", "posicao_y"])[colunas])


def percentis(agg: pd.DataFrame, player_id: int, minimo_minutos: float = MINIMO_MINUTOS_PERCENTIL) -> list:
    """Cada métrica do jogador por 90 minutos e o percentil dela entre os jogadores da temporada.

    Entram na comparação os jogadores com pelo menos `minimo_minutos`. O percentil é a fatia deles
    com valor menor ou igual ao do jogador (99 = entre os melhores). Sem minutos suficientes, o
    jogador não é comparado e a lista sai vazia.
    """
    grupo = agg[agg["minutos"] >= minimo_minutos]
    linha = grupo[grupo["player_id"] == player_id]
    if linha.empty:
        return []
    saida = []
    for metrica, rotulo in METRICAS_RANKING.items():
        por_90 = 90 * grupo[metrica] / grupo["minutos"]
        valor = float(por_90.loc[linha.index[0]])
        saida.append({
            "metrica": metrica, "rotulo": rotulo, "total": int(linha[metrica].iloc[0]),
            "por_90": round(valor, 2), "percentil": int(round(100 * (por_90 <= valor).mean())),
        })
    return saida


def foto_treinador(nome: str | None, fotos: dict | None) -> str | None:
    """Endereço (servido por rotas.py) da foto do técnico, só para quem tem foto no Commons."""
    if not nome or normalizar(nome) not in (fotos or {}):
        return None
    return f"/foto/treinador?nome={quote(nome)}"


def treinador(t: pd.DataFrame, nomes: dict, team_id, divergencias: list | None = None,
              fotos: dict | None = None) -> dict | None:
    if team_id is None:
        return None
    nome_time = nomes.get(team_id, f"Time {team_id}")
    outra = next((d for d in (divergencias or []) if d.get("time") == nome_time), None)
    historico = t[t["team_id"] == team_id].sort_values("inicio", na_position="first").copy()
    historico["inicio"] = historico["inicio"].dt.strftime("%Y-%m-%d")
    historico["fim"] = historico["fim"].dt.strftime("%Y-%m-%d")
    atuais = historico[historico["atual"]]
    fonte_atual = atuais["fonte"].iloc[0] if not atuais.empty and "fonte" in atuais else None
    return {
        "team_id": int(team_id),
        "time": nome_time,
        "atual": atuais["treinador"].iloc[0] if not atuais.empty else None,
        "foto": foto_treinador(atuais["treinador"].iloc[0], fotos) if not atuais.empty else None,
        "fonte": fonte_atual,
        # Quando a Wikipédia (fonte do técnico atual) diverge do Wikidata, o Wikidata aparece como outra fonte.
        "outra_fonte": {"treinador": outra["wikidata"], "fonte": "Wikidata"} if outra else None,
        "historico": _json_registros(historico[["treinador", "inicio", "fim", "atual"]]),
    }


def opcoes_jogos(base: pd.DataFrame, nomes: dict) -> list:
    pares = base[["game_id", "team_id"]].drop_duplicates().sort_values(["game_id", "team_id"])
    rotulos = pares["team_id"].map(lambda t: nomes.get(t, f"Time {t}"))
    por_jogo = rotulos.groupby(pares["game_id"]).agg(" x ".join)
    return [{"game_id": int(jogo), "rotulo": rotulo} for jogo, rotulo in por_jogo.items()]


def buscar(dados: Dados, termo: str, limite: int = 30) -> dict:
    """Jogadores (na última temporada em que aparecem) e treinadores cujo nome contém o termo."""
    termo_normalizado = normalizar(termo)
    vazio = {"jogadores": [], "treinadores": []}
    if len(termo_normalizado) < 2:
        return vazio

    ultimo = dados.ultimos[dados.ultimos["nome_normalizado"].str.contains(termo_normalizado, regex=False)]
    jogadores = ultimo.sort_values("player").head(limite)[["player_id", "player", "team_id", "temporada"]]
    jogadores = _com_imagens(_json_registros(jogadores.assign(time=jogadores["team_id"].map(dados.nomes))))

    t = dados.treinadores[dados.treinadores_normalizados.str.contains(termo_normalizado, regex=False)]
    t = t.assign(atual=t["atual"].astype(bool))
    treinadores = (
        t.groupby(["treinador", "team_id"], as_index=False)
        .agg(atual=("atual", "max"), inicio=("inicio", "max"))
        .sort_values(["atual", "treinador"], ascending=[False, True])
        .head(limite)
    )
    treinadores = treinadores.assign(time=treinadores["team_id"].map(dados.nomes))
    treinadores["inicio"] = treinadores["inicio"].dt.strftime("%Y-%m-%d")
    treinadores = _com_imagens(_json_registros(treinadores))
    for registro in treinadores:
        foto = foto_treinador(registro["treinador"], dados.fotos_treinadores)
        if foto:
            registro["foto"] = foto
    return {"jogadores": jogadores, "treinadores": treinadores}


def pagina_rankings(dados: Dados, temporada: str, metrica: str = "gols") -> dict:
    agg = dados.agregado(temporada)
    if metrica not in METRICAS_RANKING:
        raise ValueError(f"Métrica inválida: {metrica}")
    return {
        "temporada": temporada,
        "metrica": metrica,
        "temporadas": dados.temporadas,
        "metricas": METRICAS_RANKING,
        "ranking": _com_imagens(ranking_jogadores(agg, metrica, LIMITE_PAGINA), temporada),
        "premios": _com_imagens(premios(agg), temporada),
    }


def pagina_jogadores(dados: Dados, temporada: str, time: int | None = None, termo: str = "") -> dict:
    if time is None:
        agg = dados.agregado(temporada)
    else:
        base = dados.temporada(temporada)
        agg = agregar_jogadores(base[base["team_id"] == time], dados.nomes)
    termo_normalizado = normalizar(termo)
    if termo_normalizado:
        agg = agg[agg["player"].map(normalizar).str.contains(termo_normalizado, regex=False)]
    return {
        "temporada": temporada,
        "time": time,
        "termo": termo,
        "temporadas": dados.temporadas,
        "times": dados.times(temporada),
        "jogadores": _com_imagens(lista_jogadores(agg), temporada),
    }


def pagina_times(dados: Dados, temporada: str) -> dict:
    base = dados.temporada(temporada)
    return {
        "temporada": temporada,
        "temporadas": dados.temporadas,
        "tabela": _com_imagens(ranking_times(base, dados.nomes), temporada),
    }


def painel(
    dados: Dados,
    temporada: str,
    jogo: int | None = None,
    time: int | None = None,
    jogador: int | None = None,
    x: str = "finalizacoes",
    y: str = "passes_certos",
) -> dict:
    """Dados da página inicial (app.js): filtros, dispersão, posições, jogador e técnico."""
    base = dados.temporada(temporada)
    for metrica in (x, y):
        if metrica not in METRICAS_DISPERSAO:
            raise ValueError(f"Métrica inválida: {metrica}")
    if jogo is not None and not (base["game_id"] == jogo).any():
        raise ValueError(f"Jogo {jogo} não existe na temporada {temporada}")
    if jogo is None and time is None:
        agg = dados.agregado(temporada)
    else:
        f_jogo = base if jogo is None else base[base["game_id"] == jogo]
        agg = agregar_jogadores(f_jogo if time is None else f_jogo[f_jogo["team_id"] == time], dados.nomes)
    if jogador is not None and not (agg["player_id"] == jogador).any():
        raise ValueError(f"Jogador {jogador} não está no recorte selecionado")

    detalhe = None
    time_treinador = time
    if jogador is not None:
        linha = agg[agg["player_id"] == jogador]
        detalhe = _com_imagens(_json_registros(linha), temporada)[0]
        # Percentil sempre contra a temporada inteira, mesmo com o recorte num time.
        detalhe["percentis"] = [] if jogo is not None else percentis(dados.agregado(temporada), jogador)
        time_treinador = int(linha["team_id"].iloc[0])

    minimo = 0 if jogo is not None else MINIMO_MINUTOS_PADRAO
    return {
        "filtros": {"temporada": temporada, "jogo": jogo, "time": time, "jogador": jogador, "x": x, "y": y},
        "opcoes": {
            "temporadas": dados.temporadas,
            "jogos": dados.jogos(temporada),
            "times": dados.times(temporada),
            "jogadores": _json_registros(agg.sort_values("player")[["player_id", "player", "time"]]),
            "metricas": METRICAS_DISPERSAO,
        },
        "dispersao": dispersao(agg, x, y, minimo),
        "posicoes": posicoes(agg),
        "treinador": treinador(dados.treinadores, dados.nomes, time_treinador, dados.divergencias,
                               dados.fotos_treinadores),
        "jogador": detalhe,
    }
