"""Garante que a raiz do projeto esteja no caminho de importação dos testes."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def jogo(rodada, mandante, visitante, gols_mandante=None, gols_visitante=None, data=None):
    return {
        "id": rodada * 100 + mandante % 100, "rodada": rodada, "data": data or f"2025-05-{rodada:02d}",
        "mandante": mandante, "visitante": visitante,
        "gols_mandante": gols_mandante, "gols_visitante": gols_visitante,
    }


def linha_tabela(cbf_id, time, uf, posicao, pontos, jogos, v, e, d, gp, gc, evolucao=0, ca=10, cv=1):
    return {
        "cbf_id": cbf_id, "time": time, "uf": uf, "escudo": f"https://conteudo.cbf.com.br/clubes/{cbf_id}/escudo.jpg",
        "posicao": posicao, "evolucao": evolucao, "pontos": pontos, "jogos": jogos, "vitorias": v, "empates": e,
        "derrotas": d, "gols_pro": gp, "gols_contra": gc, "saldo": gp - gc, "amarelos": ca, "vermelhos": cv,
        "aproveitamento": round(100 * pontos / (3 * jogos)) if jogos else None, "rodada": jogos,
    }


def temporada_falsa(ano="2025"):
    """Três times da CBF com nomes que existem na base: Flamengo, Palmeiras e Ceará."""
    jogos = [
        jogo(1, 20016, 20002, 2, 1),   # Flamengo 2x1 Palmeiras
        jogo(2, 20031, 20016, 0, 0),   # Ceará 0x0 Flamengo
        jogo(3, 20002, 20031, 3, 0),   # Palmeiras 3x0 Ceará
        jogo(4, 20016, 20031),         # Flamengo x Ceará, ainda não jogado
    ]
    return {
        "ano": ano,
        "rodada": 3,
        "encerrada": False,
        "classificacao": [
            linha_tabela(20016, "Flamengo", "RJ", 1, 4, 2, 1, 1, 0, 2, 1, evolucao=1),
            linha_tabela(20002, "Palmeiras", "SP", 2, 3, 2, 1, 0, 1, 4, 2, evolucao=-1),
            linha_tabela(20031, "Ceará", "CE", 3, 1, 2, 0, 1, 1, 0, 3),
        ],
        "artilharia": [{"atleta_id": 7, "nome": "Pedro Fachineti", "apelido": "Pedro", "gols": 2,
                        "cbf_id": 20016, "clube": "Flamengo-RJ", "escudo": None}],
        "times": {
            str(cbf_id): {
                "atletas": [{"atleta_id": 521990, "nome": "Giorgian Daniel de Arrascaeta Benedetti",
                             "apelido": "De Arrascaeta"}] if cbf_id == 20016 else [],
                "jogos": [j for j in jogos if cbf_id in (j["mandante"], j["visitante"])],
            }
            for cbf_id in (20016, 20002, 20031)
        },
    }


class CacheFalso:
    """Substitui coleta.cbf.Cache: nada de rede nos testes."""

    def __init__(self, falhar=False, fonte="CBF"):
        self.falhar = falhar
        self.fonte = fonte
        self.fotos = []

    def temporada(self, ano):
        if self.falhar:
            raise ValueError(f"{self.fonte} fora do ar")
        temporada = {**temporada_falsa(str(ano)), "fonte": self.fonte}
        if self.fonte == "ESPN":  # a ESPN não informa cartões
            temporada["classificacao"] = [{**l, "amarelos": None, "vermelhos": None} for l in temporada["classificacao"]]
        return temporada

    def completa(self, ano):
        return self.temporada(ano)

    def time(self, ano, time_id):
        return self.temporada(ano)["times"].get(str(time_id), {"atletas": [], "jogos": []})

    def atleta(self, ano, atleta_id):
        self.fotos.append((ano, atleta_id))
        foto = (b"\xff\xd8jpeg", "image/jpeg") if atleta_id == 521990 else None
        return {"partidas": PARTIDAS.get(atleta_id), "foto": foto}

    def foto(self, ano, atleta_id):
        return self.atleta(ano, atleta_id)["foto"]


# Partidas na CBF dos atletas do elenco falso (para o desempate de homônimos).
PARTIDAS = {521990: 30}


class FotosFalsas:
    """Substitui coleta.thesportsdb.Fotos: só "Bruno Henrique" tem foto."""

    def __init__(self):
        self.buscas = []

    def foto(self, nomes, clubes):
        self.buscas.append((tuple(nomes), tuple(clubes)))
        return "https://r2.thesportsdb.com/bruno.png" if "Bruno Henrique" in nomes else None


class CommonsFalso:
    """Substitui coleta.commons.Commons: só o Palmeiras tem escudo e só "Raphael Veiga" tem foto de jogador."""

    ESCUDO = "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/10/Palmeiras_logo.svg/120px-Palmeiras_logo.svg.png"
    FOTO = "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/Raphael_Veiga.jpg/120px-Raphael_Veiga.jpg"

    def __init__(self, time_com_escudo=None):
        self.time_com_escudo = time_com_escudo
        self.buscas = []

    def escudo(self, team_id):
        return self.ESCUDO if team_id == self.time_com_escudo else None

    def foto_jogador(self, nomes, team_ids, temporadas=()):
        self.buscas.append((tuple(nomes), tuple(team_ids), tuple(temporadas)))
        return self.FOTO if "Raphael Veiga" in nomes else None

    def foto(self, arquivo):
        return f"https://commons.wikimedia.org/wiki/Special:FilePath/{arquivo.replace(' ', '_')}?width=120"

    def creditos(self, arquivos=()):
        return [{"uso": "Escudo", "arquivo": "Palmeiras logo.svg", "autor": "Sociedade Esportiva Palmeiras",
                 "licenca": "Public domain", "pagina": "https://commons.wikimedia.org/wiki/File:Palmeiras_logo.svg"},
                *({"uso": "Foto", "arquivo": a, "autor": None, "licenca": None,
                   "pagina": f"https://commons.wikimedia.org/wiki/File:{a}"} for a in arquivos)]


@pytest.fixture
def cache_cbf():
    return CacheFalso()


@pytest.fixture
def reserva_espn():
    """ESPN falsa; por padrão também fora do ar, para os testes não dependerem da reserva."""
    return CacheFalso(falhar=True, fonte="ESPN")


@pytest.fixture
def fotos_reserva():
    return FotosFalsas()


@pytest.fixture
def fotmob_falso():
    """Ids do FotMob: vazio por padrão, para os testes das outras fontes; cada teste põe os que quer."""
    from coleta import fotmob

    return fotmob.Imagens({"jogadores": {}, "times": {}})


@pytest.fixture
def commons_falso():
    """Commons falso em que só o Palmeiras tem escudo: os outros times usam a reserva (CBF ou ESPN)."""
    from sb_web import rotas

    return CommonsFalso(next(t for t, nome in rotas.dados().nomes.items() if nome == "Palmeiras"))


@pytest.fixture
def cliente(monkeypatch, cache_cbf, reserva_espn, fotos_reserva, commons_falso, fotmob_falso):
    """Cliente HTTP do site com os dados reais de dados/, fontes externas falsas e SQLite em memória."""
    from sb_web import create_app, rotas
    from sb_web.fonte_cbf import FonteCBF

    # fotos_lentas ligado: os testes das fotos da CBF e do TheSportsDB continuam valendo.
    fonte = FonteCBF(rotas.dados(), cache_cbf, reserva_espn, fotos_reserva, commons_falso, fotmob_falso,
                     fotos_lentas=True)
    monkeypatch.setattr(rotas, "fonte", lambda: fonte)
    # CSRF desligado: os testes enviam os formulários direto; test_observacoes cobre o token à parte.
    return create_app(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://", WTF_CSRF_ENABLED=False).test_client()


def pagina_next(*pedacos: str) -> str:
    """HTML no formato do site da CBF: cada pedaço do fluxo do Next.js num `self.__next_f.push`."""
    scripts = "".join(f"<script>self.__next_f.push([1,{json.dumps(p)}])</script>" for p in pedacos)
    return f"<html><body>{scripts}</body></html>"
