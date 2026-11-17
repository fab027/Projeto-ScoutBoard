"""Brasileirão Série A pela API pública da ESPN (sem chave): reserva da CBF.

Usada quando o site da CBF não responde (ele bloqueia o IP por alguns minutos depois de
rajadas). Devolve a temporada no mesmo formato de coleta.cbf.temporada, para que a página
de classificação funcione igual. A ESPN não informa cartões nem elencos com foto.

Endereços usados (ano = temporada), cada um só quando a página precisa dele:
- /v2/sports/soccer/bra.1/standings?season={ano}: classificação e escudos
- /site/v2/sports/soccer/bra.1/teams/{id}/schedule?season={ano}: jogos de cada time
- /site/v2/sports/soccer/bra.1/statistics?season={ano}: artilharia e assistências
"""
import re
import time

import requests

from config import USER_AGENT

BASE = "https://site.api.espn.com/apis"
LIGA = "soccer/bra.1"
TENTATIVAS = 3
JOGOS_NA_TEMPORADA = 38
LIDERES = 10

_sessao = requests.Session()
_sessao.headers["User-Agent"] = USER_AGENT
_NOME_COM_UF = re.compile(r"^(.*\S)-([A-Z]{2})$")


def json_de(endereco: str) -> dict:
    for tentativa in range(TENTATIVAS):
        try:
            resposta = _sessao.get(endereco, timeout=20)
            if resposta.status_code < 500 or tentativa == TENTATIVAS - 1:
                resposta.raise_for_status()
                return resposta.json()
        except requests.ConnectionError:
            if tentativa == TENTATIVAS - 1:
                raise
        time.sleep(1 + tentativa)
    raise RuntimeError(f"Falha ao acessar {endereco}")


def _logo(time_: dict) -> str | None:
    logos = time_.get("logos") or []
    padrao = [logo for logo in logos if "default" in logo.get("rel", [])]
    return (padrao or logos or [{}])[0].get("href")


def _numero(estatisticas: dict, nome: str) -> int | None:
    valor = (estatisticas.get(nome) or {}).get("value")
    return int(valor) if valor is not None else None


def ler_classificacao(dados: dict) -> list[dict]:
    entradas = dados["children"][0]["standings"]["entries"]
    linhas = []
    for posicao, entrada in enumerate(entradas, start=1):
        time_ = entrada["team"]
        estatisticas = {s["name"]: s for s in entrada["stats"]}
        com_uf = _NOME_COM_UF.match(time_["displayName"])
        pontos, jogos = _numero(estatisticas, "points"), _numero(estatisticas, "gamesPlayed")
        linhas.append({
            "cbf_id": int(time_["id"]),
            "time": time_["displayName"],
            "uf": com_uf.group(2) if com_uf else None,
            "escudo": _logo(time_),
            "posicao": _numero(estatisticas, "rank") or posicao,
            "evolucao": _numero(estatisticas, "rankChange") or 0,
            "pontos": pontos,
            "jogos": jogos,
            "vitorias": _numero(estatisticas, "wins"),
            "empates": _numero(estatisticas, "ties"),
            "derrotas": _numero(estatisticas, "losses"),
            "gols_pro": _numero(estatisticas, "pointsFor"),
            "gols_contra": _numero(estatisticas, "pointsAgainst"),
            "saldo": _numero(estatisticas, "pointDifferential"),
            "amarelos": None,
            "vermelhos": None,
            "aproveitamento": round(100 * pontos / (3 * jogos)) if jogos else None,
            "rodada": jogos,
        })
    return linhas


def _gols(competidor: dict, feito: bool) -> int | None:
    """Placar de um lado da partida; None enquanto o jogo não terminou."""
    placar = competidor.get("score")
    valor = placar.get("value") if isinstance(placar, dict) else placar
    return int(float(valor)) if feito and valor not in (None, "") else None


def ler_jogos(dados: dict) -> list[dict]:
    jogos = []
    for evento in dados.get("events", []):
        disputa = evento["competitions"][0]
        lados = {c["homeAway"]: c for c in disputa["competitors"]}
        feito = bool(disputa.get("status", {}).get("type", {}).get("completed"))

        jogos.append({
            "id": int(evento["id"]),
            "rodada": None,
            "data": (evento.get("date") or "")[:10] or None,
            "mandante": int(lados["home"]["team"]["id"]),
            "visitante": int(lados["away"]["team"]["id"]),
            "gols_mandante": _gols(lados["home"], feito),
            "gols_visitante": _gols(lados["away"], feito),
        })
    return jogos


def ler_lideres(dados: dict, categoria: str) -> list[dict]:
    """Artilharia (`goalsLeaders`) ou assistências (`assistsLeaders`), no formato da artilharia da CBF."""
    grupo = next((g for g in dados.get("stats", []) if g.get("name") == categoria), {})
    saida = []
    for lider in grupo.get("leaders", [])[:LIDERES]:
        atleta, time_ = lider["athlete"], lider["athlete"].get("team") or {}
        saida.append({
            "atleta_id": int(atleta["id"]),
            "nome": atleta.get("displayName"),
            "apelido": atleta.get("displayName"),
            "gols": int(lider.get("value") or 0),
            "cbf_id": int(time_["id"]) if time_.get("id") else None,
            "clube": time_.get("displayName"),
            "escudo": _logo(time_),
        })
    return saida


def tabela(ano: str, buscar=json_de) -> dict:
    """Classificação, artilharia e assistências da temporada `ano` (duas requisições).

    Os jogos de cada time entram depois, sob demanda (`time_da_temporada`), no mesmo formato
    de coleta.cbf.tabela.
    """
    dados = buscar(f"{BASE}/v2/sports/{LIGA}/standings?season={ano}")
    if str((dados.get("season") or {}).get("year")) != str(ano):
        raise ValueError(f"A ESPN não tem a temporada {ano}")
    classificacao = ler_classificacao(dados)
    try:
        lideres = buscar(f"{BASE}/site/v2/sports/{LIGA}/statistics?season={ano}")
    except (requests.RequestException, ValueError):
        lideres = {}
    return {
        "ano": str(ano),
        "fonte": "ESPN",
        "rodada": max((linha["jogos"] or 0 for linha in classificacao), default=0),
        "classificacao": classificacao,
        "artilharia": ler_lideres(lideres, "goalsLeaders"),
        "assistencias": ler_lideres(lideres, "assistsLeaders"),
        "times": {},
        "encerrada": all((linha["jogos"] or 0) >= JOGOS_NA_TEMPORADA for linha in classificacao),
    }


def time_da_temporada(ano: str, time_id: int, buscar=json_de) -> dict:
    """Jogos de um time na temporada (uma requisição). A ESPN não traz elenco com foto."""
    return {"atletas": [], "jogos": ler_jogos(buscar(f"{BASE}/site/v2/sports/{LIGA}/teams/{time_id}/schedule?season={ano}"))}
