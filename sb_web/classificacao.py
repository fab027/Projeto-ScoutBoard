"""Classificação oficial da CBF com os recortes que o torcedor mais consulta.

Funções puras: recebem a temporada como coleta.cbf.temporada devolve e montam as linhas da
página Times. Recortes:
- geral: números oficiais da CBF (pontos já com eventuais punições), mais sequência recente,
  próximo jogo, jogos sem sofrer gol e médias de gols, calculados a partir dos jogos;
- casa e fora: calculados só com os jogos como mandante ou como visitante.
"""
import re

RECORTES = {"geral": "Geral", "casa": "Mandante", "fora": "Visitante"}
SEQUENCIA = 5
# Faixas usuais do Brasileirão. As vagas mudam conforme os campeões da Copa do Brasil e da Libertadores.
ZONAS = [
    (range(1, 5), "libertadores", "Libertadores (fase de grupos)"),
    (range(5, 7), "pre-libertadores", "Libertadores (fase prévia)"),
    (range(7, 13), "sul-americana", "Sul-Americana"),
    (range(17, 21), "rebaixamento", "Rebaixamento"),
]


_SUFIXOS = re.compile(r"(\s+(saf|s\.a\.f\.|fc|ec))+$", re.IGNORECASE)


def nome_exibicao(time: str) -> str:
    """'Cruzeiro Saf' -> 'Cruzeiro', 'Fortaleza Ec Saf' -> 'Fortaleza': o nome que o torcedor usa."""
    return _SUFIXOS.sub("", time or "").strip() or time


def zona(posicao: int | None) -> str | None:
    return next((classe for faixa, classe, _ in ZONAS if posicao in faixa), None)


def _jogos_disputados(temporada: dict) -> list[dict]:
    """Cada jogo uma vez (ele aparece na página dos dois times), em ordem de data."""
    unicos = {}
    for time_ in temporada["times"].values():
        for jogo in time_["jogos"]:
            unicos[(jogo["rodada"], jogo["mandante"], jogo["visitante"])] = jogo
    return sorted(unicos.values(), key=lambda jogo: (jogo["data"] or "9999", jogo["rodada"] or 0))


def _feito(jogo: dict) -> bool:
    return jogo["gols_mandante"] is not None and jogo["gols_visitante"] is not None


def _resultado(gols: int, sofridos: int) -> str:
    return "V" if gols > sofridos else "E" if gols == sofridos else "D"


def _campanhas(jogos: list[dict], nomes: dict[int, str]) -> dict[tuple[int, str], dict]:
    """(cbf_id, recorte) -> totais e jogos daquele time, para geral, casa e fora."""
    campanhas: dict[tuple[int, str], dict] = {}

    def campanha(cbf_id: int, recorte: str) -> dict:
        return campanhas.setdefault(
            (cbf_id, recorte),
            {"jogos": 0, "vitorias": 0, "empates": 0, "derrotas": 0, "gols_pro": 0, "gols_contra": 0,
             "sem_sofrer": 0, "sequencia": [], "proximo": None},
        )

    for jogo in jogos:
        lados = [
            (jogo["mandante"], jogo["visitante"], jogo["gols_mandante"], jogo["gols_visitante"], "casa"),
            (jogo["visitante"], jogo["mandante"], jogo["gols_visitante"], jogo["gols_mandante"], "fora"),
        ]
        for cbf_id, adversario, gols, sofridos, mando in lados:
            if not _feito(jogo):
                geral = campanha(cbf_id, "geral")
                if geral["proximo"] is None:
                    geral["proximo"] = {"adversario": nomes.get(adversario, ""), "adversario_id": adversario,
                                        "casa": mando == "casa", "data": jogo["data"], "rodada": jogo["rodada"]}
                continue
            resultado = _resultado(gols, sofridos)
            for recorte in ("geral", mando):
                c = campanha(cbf_id, recorte)
                c["jogos"] += 1
                c["vitorias"] += resultado == "V"
                c["empates"] += resultado == "E"
                c["derrotas"] += resultado == "D"
                c["gols_pro"] += gols
                c["gols_contra"] += sofridos
                c["sem_sofrer"] += sofridos == 0
                c["sequencia"].append({
                    "resultado": resultado, "placar": f"{gols}x{sofridos}", "casa": mando == "casa",
                    "adversario": nomes.get(adversario, ""), "rodada": jogo["rodada"],
                })
    return campanhas


def _completar(linha: dict, campanha: dict | None) -> dict:
    """Médias de gols e, quando os jogos do time já foram lidos (`campanha`), sequência e jogos sem sofrer gol.

    Sem os jogos, a sequência é a que a própria tabela da CBF traz (só V, E ou D, sem placar).
    """
    jogos = linha["jogos"] or 0
    if campanha is None:
        sequencia = [{"resultado": r, "placar": None} for r in linha.get("ultimos", [])]
    else:
        sequencia = campanha["sequencia"][-SEQUENCIA:]
    return {
        **linha,
        "sem_sofrer": campanha["sem_sofrer"] if campanha else None,
        "gols_por_jogo": round(linha["gols_pro"] / jogos, 2) if jogos else None,
        "sofridos_por_jogo": round(linha["gols_contra"] / jogos, 2) if jogos else None,
        "sequencia": sequencia,
    }


def _proximo(linha: dict, campanha: dict | None, nomes: dict[int, str], escudos: dict[int, str]) -> dict | None:
    """Próximo adversário com o escudo: o que a tabela da CBF traz (ela não lista os jogos a fazer)
    ou, na falta dele, o primeiro jogo a fazer da lista de jogos."""
    if linha.get("proximo"):
        adversario = linha["proximo"]
        proximo = {"adversario": nomes.get(adversario["adversario_id"]) or adversario["adversario"],
                   "adversario_id": adversario["adversario_id"], "escudo": adversario["escudo"]}
    elif campanha and campanha["proximo"]:
        proximo = dict(campanha["proximo"])
    else:
        return None
    proximo["escudo"] = escudos.get(proximo["adversario_id"]) or proximo.get("escudo")
    return proximo


def montar(temporada: dict, recorte: str = "geral", links: dict[int, int] | None = None) -> dict:
    """Linhas da tabela no `recorte`, destaques da temporada e artilharia.

    `links` mapeia o id da CBF para o team_id da base, para ligar a linha ao painel do time.
    O recorte geral funciona só com a tabela; mandante e visitante precisam dos jogos de todos
    os times (coleta.cbf.Cache.completa). O que depende de jogos ainda não lidos fica vazio.
    """
    if recorte not in RECORTES:
        raise ValueError(f"Recorte inválido: {recorte}")
    lidos = set(temporada.get("times", {}))
    links = links or {}
    oficial = [{**linha, "time": nome_exibicao(linha["time"])} for linha in temporada["classificacao"]]
    # A CBF chama Mineiro e Goianiense só de "Atlético" em algumas temporadas: a UF desfaz o empate.
    repetidos = {l["time"] for l in oficial if sum(o["time"] == l["time"] for o in oficial) > 1}
    oficial = [{**l, "time": f"{l['time']}-{l['uf']}"} if l["time"] in repetidos and l.get("uf") else l
               for l in oficial]
    nomes = {linha["cbf_id"]: linha["time"] for linha in oficial}
    escudos = {linha["cbf_id"]: linha["escudo"] for linha in oficial}
    campanhas = _campanhas(_jogos_disputados(temporada), nomes)
    vazia = {"jogos": 0, "vitorias": 0, "empates": 0, "derrotas": 0, "gols_pro": 0, "gols_contra": 0,
             "sem_sofrer": 0, "sequencia": [], "proximo": None}

    geral = []
    for linha in oficial:
        lido = str(linha["cbf_id"]) in lidos
        campanha = campanhas.get((linha["cbf_id"], "geral"), vazia) if lido else None
        geral.append({
            **_completar(linha, campanha),
            "team_id": links.get(linha["cbf_id"]),
            "zona": zona(linha["posicao"]),
            "proximo": _proximo(linha, campanha, nomes, escudos),
        })

    if recorte == "geral":
        linhas = geral
    else:
        linhas = []
        for linha in oficial:
            c = campanhas.get((linha["cbf_id"], recorte), vazia)
            pontos = 3 * c["vitorias"] + c["empates"]
            linhas.append(_completar({
                "cbf_id": linha["cbf_id"], "time": linha["time"], "uf": linha["uf"], "escudo": linha["escudo"],
                "team_id": links.get(linha["cbf_id"]), "pontos": pontos,
                **{k: c[k] for k in ("jogos", "vitorias", "empates", "derrotas", "gols_pro", "gols_contra")},
                "saldo": c["gols_pro"] - c["gols_contra"],
                "aproveitamento": round(100 * pontos / (3 * c["jogos"])) if c["jogos"] else None,
                "evolucao": 0, "zona": None, "proximo": None,
            }, c))
        linhas.sort(key=lambda l: (l["pontos"], l["vitorias"], l["saldo"], l["gols_pro"]), reverse=True)
        for posicao, linha in enumerate(linhas, start=1):
            linha["posicao"] = posicao

    return {
        "fonte": temporada.get("fonte", "CBF"),
        "recorte": recorte,
        "rodada": temporada.get("rodada"),
        "encerrada": temporada.get("encerrada", False),
        "linhas": linhas,
        "destaques": destaques(geral, campanhas, completa=len(lidos) >= len(oficial)),
        "artilharia": temporada.get("artilharia", [])[:10],
        "assistencias": temporada.get("assistencias", [])[:10],
    }


def destaques(geral: list[dict], campanhas: dict, completa: bool = True) -> list[dict]:
    """Os números que resumem a temporada: ataque, defesa, disciplina e, com todos os jogos lidos
    (`completa`), mando de campo e jogos sem sofrer gol."""
    com_jogos = [linha for linha in geral if linha["jogos"]]
    if not com_jogos:
        return []

    def aproveitamento(linha, recorte):
        c = campanhas.get((linha["cbf_id"], recorte))
        return round(100 * (3 * c["vitorias"] + c["empates"]) / (3 * c["jogos"])) if c and c["jogos"] else -1

    def cartao(titulo, linha, valor, sufixo):
        return {"titulo": titulo, "time": linha["time"], "escudo": linha["escudo"], "team_id": linha["team_id"],
                "valor": valor, "sufixo": sufixo}

    ataque = max(com_jogos, key=lambda l: (l["gols_pro"], -l["jogos"]))
    defesa = min(com_jogos, key=lambda l: (l["gols_contra"], l["jogos"]))
    mandante = max(com_jogos, key=lambda l: aproveitamento(l, "casa"))
    visitante = max(com_jogos, key=lambda l: aproveitamento(l, "fora"))
    saida = [
        cartao("Melhor ataque", ataque, ataque["gols_pro"], "gols"),
        cartao("Melhor defesa", defesa, defesa["gols_contra"], "gols sofridos"),
    ]
    if completa:
        muralha = max(com_jogos, key=lambda l: l["sem_sofrer"] or 0)
        saida += [
            cartao("Melhor mandante", mandante, aproveitamento(mandante, "casa"), "% em casa"),
            cartao("Melhor visitante", visitante, aproveitamento(visitante, "fora"), "% fora"),
            cartao("Mais jogos sem sofrer gol", muralha, muralha["sem_sofrer"], "jogos"),
        ]
    if all(l["amarelos"] is not None for l in com_jogos):  # a ESPN não informa cartões
        disciplina = min(com_jogos, key=lambda l: l["amarelos"] + 3 * (l["vermelhos"] or 0))
        saida.append(cartao("Mais disciplinado", disciplina, disciplina["amarelos"] + (disciplina["vermelhos"] or 0),
                            "cartões"))
    return saida
