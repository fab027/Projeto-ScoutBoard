"""Coleta o histórico de técnicos dos clubes do Brasileirão pela API SPARQL do Wikidata.

Por que Wikidata e não raspagem de sites: o Sofascore bloqueia acesso automatizado
e muda o HTML sem aviso. O Wikidata tem API documentada, dados abertos e formato
estável. (Escudos e fotos vêm da ESPN e do TheSportsDB, em coleta/atualizacao.py.)

Proteções contra a falha silenciosa (dados que param de chegar sem erro):
- a coleta falha alto se a resposta vier vazia, com esquema diferente ou com
  queda de volume em relação à última coleta bem-sucedida;
- em caso de falha, o arquivo anterior é mantido e o erro vai para o status;
- o status registra quando foi a última coleta boa (testado em test_treinadores.py).

Uso (a partir da raiz do projeto):
    python -m coleta.treinadores
    set SCOUTBOARD_CONTATO=seu-email-ou-site   (opcional, identifica o robô)
"""
import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests

from config import MAPEAMENTO_TIMES, TREINADORES, TREINADORES_STATUS
from coleta.nomes import normalizar as _normalizar
from coleta.wikipedia import tecnico, wikitexto

MAPEAMENTO = MAPEAMENTO_TIMES
SAIDA = TREINADORES
STATUS = TREINADORES_STATUS

ENDPOINT = "https://query.wikidata.org/sparql"
CONTATO = os.environ.get("SCOUTBOARD_CONTATO", "contato nao informado")
USER_AGENT = f"ScoutBoard-TreinadorBot/0.1 (projeto academico; {CONTATO})"
TENTATIVAS = 4
CODIGOS_RETENTAVEIS = {429, 500, 502, 503, 504}
QUEDA_MAXIMA = 0.8  # aborta se o número de técnicos cair abaixo de 80% da coleta anterior
COLUNAS = ["team_id", "time_base", "qid_clube", "treinador", "inicio", "fim", "atual", "fonte", "foto"]
FONTE_WIKIDATA = "Wikidata"
FONTE_WIKIPEDIA = "Wikipédia (pt), infobox do clube"
PAUSA_WIKIPEDIA = 2.0

CONSULTA = """
SELECT ?club ?coach ?coachLabel ?start ?end ?img WHERE {{
  VALUES ?club {{ {clubes} }}
  ?club p:P286 ?st .
  ?st ps:P286 ?coach .
  OPTIONAL {{ ?st pq:P580 ?start . }}
  OPTIONAL {{ ?st pq:P582 ?end . }}
  OPTIONAL {{ ?coach wdt:P18 ?img . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "pt,en". }}
}}
"""


def carregar_mapeamento(caminho: Path = MAPEAMENTO) -> pd.DataFrame:
    return pd.read_csv(caminho, dtype=str)


def montar_consulta(qids: list[str]) -> str:
    return CONSULTA.format(clubes=" ".join(f"wd:{q}" for q in qids))


def requisitar(consulta: str, sessao=None) -> dict:
    """Executa a consulta com novas tentativas e espera exponencial."""
    sessao = sessao or requests
    ultimo_erro = None
    for tentativa in range(TENTATIVAS):
        try:
            resposta = sessao.get(
                ENDPOINT,
                params={"query": consulta},
                headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
                timeout=60,
            )
            if resposta.status_code == 200:
                return resposta.json()
            ultimo_erro = f"HTTP {resposta.status_code}"
            if resposta.status_code not in CODIGOS_RETENTAVEIS:
                break
        except requests.RequestException as erro:
            ultimo_erro = str(erro)
        time.sleep(2**tentativa)
    raise RuntimeError(f"Falha na consulta ao Wikidata após {TENTATIVAS} tentativas: {ultimo_erro}")


def _arquivo_da_foto(endereco: str | None) -> str | None:
    """Nome do arquivo no Wikimedia Commons a partir do endereço que o Wikidata dá para a imagem (P18)."""
    if not endereco or "Special:FilePath/" not in endereco:
        return None
    return unquote(endereco.rsplit("Special:FilePath/", 1)[1]).replace("_", " ")


def interpretar(resposta: dict) -> pd.DataFrame:
    """Transforma o JSON SPARQL em uma linha por (clube, técnico, período).

    `foto` é o arquivo da imagem do técnico no Wikimedia Commons, quando o Wikidata tem uma;
    quem tem mais de uma imagem fica com a primeira.
    """
    if "results" not in resposta or "bindings" not in resposta["results"]:
        raise ValueError("Resposta do Wikidata fora do formato SPARQL esperado")
    linhas = [
        {
            "qid_clube": item["club"]["value"].rsplit("/", 1)[-1],
            "treinador": item["coachLabel"]["value"],
            "inicio": item.get("start", {}).get("value"),
            "fim": item.get("end", {}).get("value"),
            "foto": _arquivo_da_foto(item.get("img", {}).get("value")),
        }
        for item in resposta["results"]["bindings"]
    ]
    df = pd.DataFrame(linhas, columns=["qid_clube", "treinador", "inicio", "fim", "foto"])
    df = df.drop_duplicates(["qid_clube", "treinador", "inicio", "fim"], ignore_index=True)
    for coluna in ["inicio", "fim"]:
        df[coluna] = pd.to_datetime(df[coluna].str[:10], errors="coerce")
    return df


def montar_tabela(dados: pd.DataFrame, mapeamento: pd.DataFrame) -> pd.DataFrame:
    """Liga os técnicos aos team_id da base e marca o técnico atual de cada time."""
    tabela = dados.merge(
        mapeamento.rename(columns={"qid_wikidata": "qid_clube"})[["team_id", "time_base", "qid_clube"]],
        on="qid_clube",
        how="inner",
    )
    tabela["atual"] = False
    tabela["fonte"] = FONTE_WIKIDATA
    sem_fim = tabela[tabela["fim"].isna()].sort_values("inicio", na_position="first")
    atuais = sem_fim.groupby("team_id").tail(1).index
    tabela.loc[atuais, "atual"] = True
    return tabela[COLUNAS].sort_values(["team_id", "inicio"]).reset_index(drop=True)


def definir_atuais(
    tabela: pd.DataFrame, atuais: dict[str, str], mapeamento: pd.DataFrame, fonte: str
) -> tuple[pd.DataFrame, list[dict]]:
    """Põe o técnico informado por uma fonte como atual de cada time, sem apagar o histórico.

    Quem deixa de ser atual vira histórico (atual=False). Se o nome não existe na tabela,
    entra como nova linha com a fonte informada. Devolve a tabela e as trocas feitas.
    """
    trocas = []
    tabela = tabela.copy()
    nomes_time = dict(zip(mapeamento["team_id"].astype(str), mapeamento["time_base"]))
    qids = dict(zip(mapeamento["team_id"].astype(str), mapeamento["qid_wikidata"]))
    for team_id, nome in atuais.items():
        do_time = tabela["team_id"] == team_id
        anteriores = tabela.loc[do_time & tabela["atual"], "treinador"]
        anterior = anteriores.iloc[0] if not anteriores.empty else None
        if anterior is not None and _normalizar(anterior) == _normalizar(nome):
            tabela.loc[do_time & tabela["treinador"].map(_normalizar).eq(_normalizar(nome)), "fonte"] = fonte
            continue
        mesmo_nome = do_time & tabela["treinador"].map(_normalizar).eq(_normalizar(nome))
        tabela.loc[do_time, "atual"] = False
        if mesmo_nome.any():
            tabela.loc[mesmo_nome, "atual"] = True
            tabela.loc[mesmo_nome, "fonte"] = fonte
        else:
            nova = pd.DataFrame([{
                "team_id": team_id,
                "time_base": nomes_time.get(team_id, ""),
                "qid_clube": qids.get(team_id, ""),
                "treinador": nome,
                "inicio": pd.NaT,
                "fim": pd.NaT,
                "atual": True,
                "fonte": fonte,
            }])
            tabela = pd.concat([tabela, nova], ignore_index=True)
        trocas.append({"team_id": team_id, "time": nomes_time.get(team_id, ""), "antes": anterior, "depois": nome})
    return tabela, trocas


def complementar_com_wikipedia(tabela: pd.DataFrame, mapeamento: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Técnico atual pela Wikipédia (pt), que costuma ser atualizada com mais rapidez.

    Quando o Wikidata tem outro técnico atual, a Wikipédia vence e a divergência fica
    registrada em `conflitos`, para conferência. Sem resposta da Wikipédia, vale o Wikidata.
    """
    tabela = tabela.assign(team_id=tabela["team_id"].astype(str))
    atuais_wikidata = tabela[tabela["atual"]].set_index("team_id")["treinador"].to_dict()
    pela_wikipedia, conflitos, erros = {}, [], []
    for _, linha in mapeamento.iterrows():
        team_id = str(linha["team_id"])
        try:
            texto = wikitexto(linha["nome_wikidata"])
        except Exception as erro:
            erros.append({"time": linha["time_base"], "erro": str(erro)})
            continue
        finally:
            time.sleep(PAUSA_WIKIPEDIA)
        nome = tecnico(texto) if texto else None
        if not nome:
            continue
        pela_wikipedia[team_id] = nome
        if team_id in atuais_wikidata and _normalizar(atuais_wikidata[team_id]) != _normalizar(nome):
            conflitos.append({"time": linha["time_base"], "wikidata": atuais_wikidata[team_id], "wikipedia": nome})
    combinada, trocas = definir_atuais(tabela, pela_wikipedia, mapeamento, FONTE_WIKIPEDIA)
    return combinada, {
        "conflitos": conflitos,
        "erros_wikipedia": erros,
        "atuais_pela_wikipedia": len(trocas),
    }


def validar(tabela: pd.DataFrame, mapeamento: pd.DataFrame, anterior: dict | None) -> dict:
    """Retorna as métricas da coleta e levanta erro se algo indicar falha silenciosa."""
    if tabela.empty:
        raise ValueError("Coleta vazia: nenhum técnico retornado")
    faltando_colunas = set(COLUNAS) - set(tabela.columns)
    if faltando_colunas:
        raise ValueError(f"Colunas ausentes: {sorted(faltando_colunas)}")

    times_mapeados = set(mapeamento["team_id"])
    times_com_dados = set(tabela["team_id"].astype(str))
    faltantes = sorted(times_mapeados - times_com_dados)
    if len(faltantes) > 0.1 * len(times_mapeados):
        raise ValueError(f"Mais de 10% dos times sem dados: {faltantes}")

    metricas = {
        "registros": len(tabela),
        "times_mapeados": len(times_mapeados),
        "times_com_dados": len(times_com_dados),
        "times_com_tecnico_atual": tabela.loc[tabela["atual"], "team_id"].nunique(),
        "times_sem_dados": faltantes,
    }
    if anterior and anterior.get("registros") and metricas["registros"] < QUEDA_MAXIMA * anterior["registros"]:
        raise ValueError(
            f"Queda de volume: {metricas['registros']} registros contra "
            f"{anterior['registros']} na coleta anterior"
        )
    return metricas


def ler_status() -> dict | None:
    if STATUS.exists():
        return json.loads(STATUS.read_text(encoding="utf-8"))
    return None


def gravar_status(dados: dict) -> None:
    STATUS.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def coletar(sessao=None) -> dict:
    agora = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    anterior = ler_status()
    try:
        mapeamento = carregar_mapeamento()
        consulta = montar_consulta(mapeamento["qid_wikidata"].tolist())
        dados = interpretar(requisitar(consulta, sessao))
        tabela = montar_tabela(dados, mapeamento)
        tabela, complementos = complementar_com_wikipedia(tabela, mapeamento)
        metricas = validar(tabela, mapeamento, anterior)
        metricas.update(complementos)
    except (RuntimeError, ValueError, KeyError) as erro:
        gravar_status({**(anterior or {}), "ultima_tentativa": agora, "ultimo_erro": str(erro)})
        raise

    tabela.to_parquet(SAIDA, index=False)
    status = {**metricas, "coletado_em": agora, "ultima_tentativa": agora, "ultimo_erro": None}
    gravar_status(status)
    return status


if __name__ == "__main__":
    # Sem argumentos próprios; o parser existe para que --help não dispare a coleta.
    argparse.ArgumentParser(description="Coleta o histórico de técnicos dos clubes (Wikidata).").parse_args()
    resultado = coletar()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
