import itertools
import base64
import json

import pytest

from coleta import cbf
from conftest import CacheFalso, CommonsFalso, FotosFalsas, pagina_next, temporada_falsa
from coleta import espn, thesportsdb
from sb_web import classificacao, rotas

LINHA_CBF = {
    "cod_time": "20016", "uf_time": "RJ", "time": "Flamengo",
    "escudo": "https://conteudo.cbf.com.br/clubes/20016/escudo.jpg", "evolucao": 0, "posicao": "1",
    "pontos": "79", "jogos": "38", "vitorias": "23", "empates": "10", "derrotas": "5", "gols_pro": "78",
    "gols_contra": "27", "gols_saldo": "51", "cartoes_vermelho": "5", "cartoes_amarelo": "78",
    "aproveitamento": "69", "rodada": "38", "ultimos_jogos": ["E", "V", "E"], "proximo_jogo": ["nenhum"],
}


# ---------- Leitura das páginas ----------

def test_ler_tabela_converte_numeros_e_traz_artilharia():
    artilharia = [{"id": "541499", "gols": "21", "nome": "Kaio Jorge Pinto Ramos", "apelido": "Kaio Jorge",
                   "foto": "$2d", "clube": {"id": "59849", "nome": "Cruzeiro-MG", "url_escudo": "x.jpg"}}]
    texto = (
        '29:["$","$L2c",null,{"initialData":{"atletas":' + json.dumps(artilharia) + "}}]"
        + '28:["$","$L39",null,{"title":"GRUPO ÚNICO","data":' + json.dumps([LINHA_CBF]) + "}]"
    )
    # O fluxo chega partido em vários push: a leitura precisa juntar os pedaços.
    dados = cbf.ler_tabela(pagina_next(texto[:50], texto[50:]))
    assert dados["rodada"] == 38
    flamengo = dados["classificacao"][0]
    assert flamengo["cbf_id"] == 20016 and flamengo["pontos"] == 79 and flamengo["saldo"] == 51
    assert flamengo["amarelos"] == 78 and flamengo["aproveitamento"] == 69
    assert dados["artilharia"] == [{"atleta_id": 541499, "nome": "Kaio Jorge Pinto Ramos", "apelido": "Kaio Jorge",
                                    "gols": 21, "cbf_id": 59849, "clube": "Cruzeiro-MG", "escudo": "x.jpg"}]


def test_ler_tabela_sem_classificacao_avisa():
    with pytest.raises(ValueError, match="Classificação"):
        cbf.ler_tabela(pagina_next('1:["$","div",null,{}]'))


def test_ler_time_traz_elenco_e_jogos_com_data_ordenavel():
    atletas = [{"atleta_id": "610639", "atleta_nome": "Francisco Dyogo Bento Alves", "Atleta_apelido": "Dyogo"}]
    jogos = [{"id_jogo": "829862", "rodada": "37", "data": " 03/12/2025",
              "mandante": {"id": "20016", "gols": "1"}, "visitante": {"id": "20031", "gols": ""}}]
    dados = cbf.ler_time(pagina_next('{"jogos":' + json.dumps(jogos) + ',"atletas":' + json.dumps(atletas) + "}"))
    assert dados["atletas"] == [{"atleta_id": 610639, "nome": "Francisco Dyogo Bento Alves", "apelido": "Dyogo"}]
    assert dados["jogos"] == [{"id": 829862, "rodada": 37, "data": "2025-12-03", "mandante": 20016,
                               "visitante": 20031, "gols_mandante": 1, "gols_visitante": None}]


def _foto(html):
    return cbf._foto_do_fluxo(cbf.fluxo(html))


def test_foto_resolve_bloco_de_texto_do_next():
    imagem = b"\xff\xd8\xff\xe0foto"
    uri = "data:image/jpeg;base64," + base64.b64encode(imagem).decode()
    html = pagina_next('23:{"atleta_foto":"$26","atleta_id":"1"}', f"26:T{len(uri):x},", uri)
    assert _foto(html) == (imagem, "image/jpeg")


def test_foto_sem_foto_devolve_none():
    assert _foto(pagina_next('{"atleta_foto":"","atleta_id":"1"}')) is None
    assert _foto(pagina_next('{"atleta_id":"1"}')) is None


# ---------- Casamento com a base ----------

CLASSIFICACAO_2019 = [
    {"cbf_id": 20003, "time": "Atlético", "uf": "MG"},
    {"cbf_id": 20093, "time": "Atlético", "uf": "GO"},
    {"cbf_id": 20052, "time": "Athletico Paranaense", "uf": "PR"},
    {"cbf_id": 20045, "time": "Csa", "uf": "AL"},
    {"cbf_id": 20010, "time": "Sport", "uf": "PE"},
    {"cbf_id": 60646, "time": "Vasco da Gama S.a.f.", "uf": "RJ"},
    {"cbf_id": 20008, "time": "Santos Fc", "uf": "SP"},
]


def test_casar_times_usa_uf_siglas_e_apelidos():
    nossos = {1: "Atletico MG", 2: "Atletico GO", 3: "Athletico Paranaense", 4: "CS Alagoano",
              5: "Sport Recife", 6: "Vasco da Gama", 7: "Santos FC", 8: "Remo"}
    assert cbf.casar_times(nossos, CLASSIFICACAO_2019) == {
        1: 20003, 2: 20093, 3: 20052, 4: 20045, 5: 20010, 6: 60646, 7: 20008,
    }


def test_casar_times_ambiguo_fica_de_fora():
    assert cbf.casar_times({1: "Atletico"}, CLASSIFICACAO_2019) == {}


ELENCO = [
    {"atleta_id": 1, "nome": "Agustin Daniel Rossi", "apelido": "ROSSI"},
    {"atleta_id": 2, "nome": "Pedro Francisco Fachineti dos Santos", "apelido": "Pedro"},
    {"atleta_id": 3, "nome": "Pedro Guilherme Abreu dos Santos", "apelido": "Pedro"},
    {"atleta_id": 4, "nome": "Emerson Aparecido Leite de Souza Junior", "apelido": "Emerson"},
    {"atleta_id": 5, "nome": "Diego Alves Carreira", "apelido": "Diego Alves"},
    {"atleta_id": 6, "nome": "Leonardo Pereira", "apelido": "Leo Pereira"},
]


@pytest.mark.parametrize("nome, esperado", [
    ("Agustín Rossi", 1),        # palavras do nome dentro do nome completo
    ("Léo Pereira", 6),          # apelido igual, sem acento
    ("Emerson Royal", 4),        # apelido inteiro dentro do nome da base
    ("Pedro", None),             # dois "Pedro" no elenco: na dúvida, nenhum
    ("Diego", None),             # uma palavra só não casa com "Diego Alves"
    ("Fulano de Tal", None),
])
def test_casar_atleta(nome, esperado):
    atleta = cbf.casar_atleta(nome, ELENCO)
    assert (atleta["atleta_id"] if atleta else None) == esperado


# ---------- Cache ----------

def _buscar_falso(chamadas, falhar=False, rodadas=38, linha=None):
    linha = linha or dict(LINHA_CBF)
    jogos = [{"id_jogo": str(r), "rodada": str(r), "data": "01/05/2025",
              "mandante": {"id": "20016", "gols": "1"}, "visitante": {"id": "20031", "gols": "0"}}
             for r in range(1, rodadas + 1)]

    def buscar(caminho):
        chamadas.append(caminho)
        if falhar:
            raise cbf.requests.ConnectionError("sem rede")
        if caminho.startswith("tabelas/"):
            return pagina_next('{"data":' + json.dumps([linha]) + "}")
        return pagina_next('{"jogos":' + json.dumps(jogos) + ',"atletas":[{"atleta_id":"1"}]}')

    return buscar


def test_tabela_e_buscada_sozinha_e_os_times_so_quando_pedidos(tmp_path):
    chamadas = []
    cache = cbf.Cache(tmp_path, _buscar_falso(chamadas))
    primeira = cache.temporada("2019")
    assert primeira["encerrada"] is True and primeira["times"] == {}
    assert primeira["classificacao"][0]["ultimos"] == ["E", "V", "E"]
    assert chamadas == ["tabelas/campeonato-brasileiro/serie-a/2019"]  # só a tabela

    assert len(cache.time("2019", 20016)["jogos"]) == 38
    assert chamadas[-1] == "times/campeonato-brasileiro/serie-a/2019/20016"
    cache.time("2019", 20016)
    assert len(chamadas) == 2  # o time já lido não é buscado de novo

    # Depois de reiniciar e sem rede, a tabela e o time lido continuam no disco.
    sem_rede = cbf.Cache(tmp_path, _buscar_falso([], falhar=True))
    assert sem_rede.temporada("2019")["classificacao"][0]["time"] == "Flamengo"
    assert "20016" in sem_rede.temporada("2019")["times"]


def test_completa_le_so_os_times_que_faltam(tmp_path):
    chamadas = []
    cache = cbf.Cache(tmp_path, _buscar_falso(chamadas))
    cache.time("2019", 20016)
    cache.completa("2019")
    assert chamadas.count("times/campeonato-brasileiro/serie-a/2019/20016") == 1


def test_temporada_em_andamento_e_conferida_so_pela_tabela_quando_nada_mudou(tmp_path):
    chamadas = []
    linha_33 = {**LINHA_CBF, "jogos": "33"}
    cache = cbf.Cache(tmp_path, _buscar_falso(chamadas, rodadas=33, linha=linha_33))

    def vencer_validade():
        cache._memoria["2026"] = (float("-inf"), cache._memoria["2026"][1])

    assert cache.temporada("2026")["encerrada"] is False
    cache.time("2026", 20016)
    assert len(chamadas) == 2  # tabela e o time pedido
    vencer_validade()
    cache.temporada("2026")
    assert len(chamadas) == 3  # validade vencida: só a tabela, que não mudou
    assert "20016" in cache.temporada("2026")["times"]  # e o time lido continua valendo

    # Tabela mudou (jogo novo): os times guardados saem e só voltam quando pedidos.
    vencer_validade()
    cache.buscar = _buscar_falso(chamadas, rodadas=34, linha={**LINHA_CBF, "jogos": "34", "pontos": "82"})
    assert cache.temporada("2026")["times"] == {}

    # Sem rede: segue com a versão que estava em memória.
    vencer_validade()
    cache.buscar = _buscar_falso([], falhar=True)
    assert cache.temporada("2026")["ano"] == "2026"


def test_queda_de_conexao_pausa_a_coleta_e_falha_na_hora(monkeypatch):
    chamadas = []

    def cai(*_, **__):
        chamadas.append(1)
        raise cbf.requests.ConnectionError("conexão derrubada")

    monkeypatch.setattr(cbf, "INTERVALO", 0)
    monkeypatch.setattr(cbf.time, "sleep", lambda _: None)
    monkeypatch.setattr(cbf._sessao, "get", cai)
    monkeypatch.setattr(cbf, "_pausa_ate", [0.0])
    with pytest.raises(cbf.requests.ConnectionError):
        cbf.baixar_pagina("x")
    assert len(chamadas) == 1  # conexão derrubada é bloqueio: não insiste
    with pytest.raises(cbf.requests.ConnectionError, match="indisponível"):
        cbf.baixar_pagina("y")
    assert len(chamadas) == 1  # durante a pausa, nem tenta


def test_escudo_e_foto_consultam_so_a_temporada_da_pagina(cliente, cache_cbf, monkeypatch):
    pedidas = []
    original = cache_cbf.temporada
    monkeypatch.setattr(cache_cbf, "temporada", lambda ano: pedidas.append(str(ano)) or original(ano))
    flamengo = next(t for t, nome in rotas.dados().nomes.items() if nome == "Flamengo")
    assert cliente.get(f"/escudo/{flamengo}?temporada=2022").status_code == 302
    assert set(pedidas) == {"2022"}
    pedidas.clear()
    assert cliente.get(f"/foto/jogador/{_player_id('Giorgian de Arrascaeta')}?temporada=2024").status_code == 200
    assert set(pedidas) == {"2024"} and cache_cbf.fotos == [("2024", 521990)]


def test_ritmo_espaca_as_requisicoes(monkeypatch):
    instantes = []
    monkeypatch.setattr(cbf, "INTERVALO", 0.05)
    monkeypatch.setattr(cbf._sessao, "get", lambda *a, **k: instantes.append(cbf.time.monotonic()) or
                        type("R", (), {"status_code": 200, "text": "ok", "raise_for_status": lambda self: None})())
    for _ in range(3):
        cbf.baixar_pagina("x")
    assert min(b - a for a, b in itertools.pairwise(instantes)) >= 0.045


# ---------- Classificação ----------

def test_montar_geral_usa_numeros_oficiais_e_calcula_sequencia_e_proximo():
    tabela = classificacao.montar(temporada_falsa(), "geral", {20016: 1239})
    flamengo, _palmeiras, ceara = tabela["linhas"]
    assert flamengo["pontos"] == 4 and flamengo["team_id"] == 1239 and flamengo["zona"] == "libertadores"
    assert [j["resultado"] for j in flamengo["sequencia"]] == ["V", "E"]
    assert flamengo["sem_sofrer"] == 1
    assert flamengo["proximo"] == {"adversario": "Ceará", "adversario_id": 20031, "casa": True,
                                   "data": "2025-05-04", "rodada": 4,
                                   "escudo": "https://conteudo.cbf.com.br/clubes/20031/escudo.jpg"}
    assert ceara["gols_por_jogo"] == 0.0 and ceara["sofridos_por_jogo"] == 1.5
    assert tabela["artilharia"][0]["apelido"] == "Pedro"


def test_montar_casa_e_fora_contam_so_o_mando():
    casa = {l["time"]: l for l in classificacao.montar(temporada_falsa(), "casa")["linhas"]}
    assert (casa["Flamengo"]["jogos"], casa["Flamengo"]["pontos"]) == (1, 3)
    assert (casa["Ceará"]["jogos"], casa["Ceará"]["pontos"]) == (1, 1)
    fora = classificacao.montar(temporada_falsa(), "fora")["linhas"]
    # Fora: Flamengo empatou com o Ceará; Palmeiras (-1) e Ceará (-3) perderam e o saldo desempata.
    assert [l["time"] for l in fora] == ["Flamengo", "Palmeiras", "Ceará"]
    assert [l["posicao"] for l in fora] == [1, 2, 3]


def test_destaques_da_temporada():
    destaques = {d["titulo"]: d for d in classificacao.montar(temporada_falsa())["destaques"]}
    assert destaques["Melhor ataque"]["time"] == "Palmeiras"
    assert destaques["Melhor defesa"]["time"] == "Flamengo"
    assert destaques["Melhor mandante"]["valor"] == 100


@pytest.mark.parametrize("oficial, exibido", [
    ("Cruzeiro Saf", "Cruzeiro"), ("Fortaleza Ec Saf", "Fortaleza"), ("Vasco da Gama S.a.f.", "Vasco da Gama"),
    ("Santos Fc", "Santos"), ("Red Bull Bragantino", "Red Bull Bragantino"),
])
def test_nome_de_exibicao_tira_sufixos_societarios(oficial, exibido):
    assert classificacao.nome_exibicao(oficial) == exibido


def test_clubes_de_mesmo_nome_ganham_a_uf():
    temporada = temporada_falsa()
    temporada["classificacao"][0] = {**temporada["classificacao"][0], "time": "Atlético", "uf": "MG"}
    temporada["classificacao"][2] = {**temporada["classificacao"][2], "time": "Atlético", "uf": "GO"}
    nomes = [l["time"] for l in classificacao.montar(temporada)["linhas"]]
    assert nomes == ["Atlético-MG", "Palmeiras", "Atlético-GO"]


def test_montar_rejeita_recorte_invalido():
    with pytest.raises(ValueError, match="Recorte"):
        classificacao.montar(temporada_falsa(), "nada")


# ---------- Rotas ----------

def _player_id(nome):
    m = rotas.dados().metricas
    return int(m[(m["player"] == nome) & (m["temporada"] == "2025")]["player_id"].iloc[0])


def test_foto_do_jogador_vem_da_cbf_sem_gravar_nada(cliente, cache_cbf):
    resposta = cliente.get(f"/foto/jogador/{_player_id('Giorgian de Arrascaeta')}")
    assert resposta.status_code == 200
    assert resposta.mimetype == "image/jpeg" and resposta.data == b"\xff\xd8jpeg"
    assert "max-age" in resposta.headers["Cache-Control"]
    assert cache_cbf.fotos == [("2025", 521990)]


def test_jogador_sem_casamento_na_cbf_usa_o_thesportsdb(cliente, fotos_reserva):
    resposta = cliente.get(f"/foto/jogador/{_player_id('Bruno Henrique')}")
    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "https://r2.thesportsdb.com/bruno.png"
    nomes, clubes = fotos_reserva.buscas[-1]
    assert nomes == ("Bruno Henrique",) and clubes  # vai com os clubes da base, para conferir no TheSportsDB


def test_foto_da_cbf_falhando_tenta_o_thesportsdb_tambem_pelo_apelido_e_nome_completo(
        cliente, cache_cbf, fotos_reserva, monkeypatch):
    monkeypatch.setattr(cache_cbf, "foto", lambda ano, atleta_id: None)
    assert cliente.get(f"/foto/jogador/{_player_id('Giorgian de Arrascaeta')}").status_code == 404
    nomes, _ = fotos_reserva.buscas[-1]
    assert nomes == ("Giorgian de Arrascaeta", "De Arrascaeta", "Giorgian Daniel de Arrascaeta Benedetti")


def test_homonimos_no_elenco_sao_desempatados_pelos_jogos(cliente, cache_cbf, monkeypatch):
    from conftest import PARTIDAS
    from sb_web.fonte_cbf import FonteCBF

    arrascaeta = _player_id("Giorgian de Arrascaeta")
    base = rotas.dados().temporada("2025")
    jogos = base.loc[base["player_id"] == arrascaeta, "game_id"].nunique()
    elenco = [{"atleta_id": 1, "nome": "Giorgian Daniel de Arrascaeta Benedetti", "apelido": "De Arrascaeta"},
              {"atleta_id": 2, "nome": "Giorgian de Arrascaeta Filho", "apelido": "De Arrascaeta"}]
    monkeypatch.setattr(cache_cbf, "time", lambda ano, time_id: {"atletas": elenco, "jogos": []})
    monkeypatch.setitem(PARTIDAS, 1, jogos)
    monkeypatch.setitem(PARTIDAS, 2, 1)
    assert FonteCBF(rotas.dados(), cache_cbf, cache_cbf, None).atleta(arrascaeta, "2025")["atleta_id"] == 1

    monkeypatch.setitem(PARTIDAS, 2, jogos - 1)  # jogos parecidos: na dúvida, nenhum
    assert FonteCBF(rotas.dados(), cache_cbf, cache_cbf, None).atleta(arrascaeta, "2025") is None


def test_jogador_sem_foto_em_nenhuma_fonte_da_404(cliente):
    assert cliente.get(f"/foto/jogador/{_player_id('Pedro')}").status_code == 404
    assert cliente.get("/foto/jogador/999999999").status_code == 404


def test_escudo_redireciona_para_a_cbf(cliente):
    flamengo = next(t for t, nome in rotas.dados().nomes.items() if nome == "Flamengo")
    resposta = cliente.get(f"/escudo/{flamengo}?temporada=2025")
    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "https://conteudo.cbf.com.br/clubes/20016/escudo.jpg"
    assert cliente.get("/escudo/1").status_code == 404


def test_pagina_times_mostra_tabela_oficial_recortes_e_artilharia(cliente):
    corpo = cliente.get("/times?temporada=2025").get_data(as_text=True)
    assert "Classificação do Brasileirão" in corpo
    assert "zona-libertadores" in corpo and 'class="num pts">4<' in corpo
    assert "Mandante" in corpo and "Visitante" in corpo
    # Temporada da base: artilharia pelo parquet, com link para o jogador e foto pela rota da base.
    assert "Artilharia" in corpo and "Kaio Jorge" in corpo and "/foto/atleta/" not in corpo
    assert f"/foto/jogador/{_player_id('Kaio Jorge')}?temporada=2025" in corpo
    # Temporada só da CBF (2026): artilharia da CBF.
    assert "/foto/atleta/2026/7" in cliente.get("/times?temporada=2026").get_data(as_text=True)
    assert "Ataque e defesa" in corpo
    fora = cliente.get("/times?temporada=2025&recorte=fora").get_data(as_text=True)
    assert "Campanha como visitante" in fora


def test_pagina_times_aceita_temporada_so_da_cbf(cliente):
    assert cliente.get("/times?temporada=2026").status_code == 200
    assert cliente.get("/times?temporada=1990").status_code == 400
    assert cliente.get("/times?recorte=nada").status_code == 400


def test_pagina_times_sem_cbf_usa_a_espn(cliente, cache_cbf, reserva_espn):
    cache_cbf.falhar, reserva_espn.falhar = True, False
    corpo = cliente.get("/times?temporada=2025").get_data(as_text=True)
    assert "Dados da ESPN: o site da CBF não respondeu agora" in corpo
    assert "zona-libertadores" in corpo
    assert "Mais disciplinado" not in corpo  # a ESPN não informa cartões
    assert "/foto/nome?nome=Pedro" in cliente.get("/times?temporada=2026").get_data(as_text=True)
    flamengo = next(t for t, nome in rotas.dados().nomes.items() if nome == "Flamengo")
    assert cliente.get(f"/escudo/{flamengo}").status_code == 302


def test_pagina_times_sem_cbf_nem_espn_usa_a_base(cliente, monkeypatch):
    from sb_web.fonte_cbf import FonteCBF

    fonte = FonteCBF(rotas.dados(), CacheFalso(falhar=True), CacheFalso(falhar=True), FotosFalsasSemNada(), CommonsFalso())
    monkeypatch.setattr(rotas, "fonte", lambda: fonte)
    resposta = cliente.get("/times?temporada=2025")
    assert resposta.status_code == 200
    assert "A CBF não respondeu agora" in resposta.get_data(as_text=True)
    assert cliente.get("/times?temporada=2026").status_code == 503
    assert cliente.get("/foto/jogador/1").status_code == 404


class FotosFalsasSemNada(FotosFalsas):
    def foto(self, nome, clubes):
        return None


# ---------- Reservas: ESPN e TheSportsDB ----------

def _entrada_espn(time_id, nome, pontos, jogos, posicao):
    valores = {"points": pontos, "gamesPlayed": jogos, "wins": 1, "ties": 1, "losses": 0, "pointsFor": 3,
               "pointsAgainst": 1, "pointDifferential": 2, "rank": posicao, "rankChange": -1}
    return {"team": {"id": str(time_id), "displayName": nome,
                     "logos": [{"href": f"https://a.espncdn.com/{time_id}.png", "rel": ["full", "default"]}]},
            "stats": [{"name": k, "value": v} for k, v in valores.items()]}


def test_espn_classificacao_no_formato_da_cbf():
    dados = {"children": [{"standings": {"entries": [_entrada_espn(7632, "Atlético-MG", 4, 2, 1)]}}]}
    linha = espn.ler_classificacao(dados)[0]
    assert linha["cbf_id"] == 7632 and linha["uf"] == "MG" and linha["escudo"] == "https://a.espncdn.com/7632.png"
    assert (linha["pontos"], linha["saldo"], linha["evolucao"], linha["aproveitamento"]) == (4, 2, -1, 67)
    assert linha["amarelos"] is None


def test_espn_jogos_so_tem_placar_quando_encerrados():
    def evento(id_, feito):
        return {"id": str(id_), "date": "2025-05-01T19:00Z", "competitions": [{
            "status": {"type": {"completed": feito}},
            "competitors": [{"homeAway": "home", "team": {"id": "819"}, "score": {"value": 2.0}},
                            {"homeAway": "away", "team": {"id": "2029"}, "score": {"value": 1.0}}]}]}
    jogos = espn.ler_jogos({"events": [evento(1, True), evento(2, False)]})
    assert jogos[0] == {"id": 1, "rodada": None, "data": "2025-05-01", "mandante": 819, "visitante": 2029,
                        "gols_mandante": 2, "gols_visitante": 1}
    assert jogos[1]["gols_mandante"] is None


def test_espn_artilharia():
    dados = {"stats": [{"name": "goalsLeaders", "leaders": [{"value": 21.0, "athlete": {
        "id": "1", "displayName": "Kaio Jorge", "team": {"id": "2022", "displayName": "Cruzeiro", "logos": []}}}]}]}
    assert espn.ler_lideres(dados, "goalsLeaders") == [{"atleta_id": 1, "nome": "Kaio Jorge", "apelido": "Kaio Jorge",
                                                        "gols": 21, "cbf_id": 2022, "clube": "Cruzeiro", "escudo": None}]


def test_espn_temporada_errada_e_recusada():
    with pytest.raises(ValueError, match="2030"):
        espn.tabela("2030", buscar=lambda _: {"season": {"year": 2026}})


def test_casar_times_com_nomes_da_espn():
    espn_2025 = [{"cbf_id": 7632, "time": "Atlético-MG", "uf": "MG"}, {"cbf_id": 3458, "time": "Athletico-PR", "uf": "PR"},
                 {"cbf_id": 6086, "time": "Botafogo", "uf": None}, {"cbf_id": 7635, "time": "Sport", "uf": None}]
    nossos = {1: "Atletico MG", 2: "Athletico Paranaense", 3: "Botafogo RJ", 4: "Sport Recife"}
    assert cbf.casar_times(nossos, espn_2025) == {1: 7632, 2: 3458, 3: 6086, 4: 7635}


JOGADORES_TSDB = [
    {"strPlayer": "Rayan Aït-Nouri", "strTeam": "Manchester City", "strSport": "Soccer", "strCutout": "x.png"},
    {"strPlayer": "Giorgian De Arrascaeta", "strTeam": "Flamengo", "strSport": "Soccer", "strCutout": "arrasca.png"},
    {"strPlayer": "Hulk", "strTeam": "Atlético Mineiro", "strSport": "Soccer", "strThumb": "hulk.jpg"},
]


@pytest.mark.parametrize("nome, clubes, esperado", [
    ("Giorgian de Arrascaeta", ["Flamengo"], "arrasca.png"),
    ("Hulk", ["Atletico MG"], "hulk.jpg"),             # UF da base não atrapalha
    ("Rayan", ["Vasco da Gama"], None),                  # nome diferente
    ("Giorgian de Arrascaeta", ["Palmeiras"], None),     # homônimo de outro clube
])
def test_thesportsdb_exige_nome_igual_e_clube_que_confere(nome, clubes, esperado):
    assert thesportsdb.escolher_foto(JOGADORES_TSDB, nome, clubes) == esperado


def test_thesportsdb_guarda_o_endereco_e_nao_busca_de_novo(tmp_path):
    buscas = []
    fotos = thesportsdb.Fotos(tmp_path / "fotos.json", lambda nome: buscas.append(nome) or JOGADORES_TSDB)
    assert fotos.foto(["Hulk"], ["Atletico MG"]) == "hulk.jpg"
    assert thesportsdb.Fotos(tmp_path / "fotos.json", lambda nome: 1 / 0).foto(["Hulk"], ["Atletico MG"]) == "hulk.jpg"
    assert buscas == ["Hulk"]


def test_thesportsdb_tenta_os_outros_nomes_do_jogador(tmp_path):
    buscas = []
    fotos = thesportsdb.Fotos(tmp_path / "fotos.json", lambda nome: buscas.append(nome) or JOGADORES_TSDB)
    assert fotos.foto(["Arrascaeta", "Giorgian De Arrascaeta"], ["Flamengo"]) == "arrasca.png"
    assert buscas == ["Arrascaeta", "Giorgian De Arrascaeta"]


class _Resposta429:
    status_code = 429
    text = ""

    def raise_for_status(self):
        raise thesportsdb.requests.HTTPError("429")


def test_thesportsdb_no_limite_pausa_as_buscas(monkeypatch):
    monkeypatch.setattr(thesportsdb, "PAUSA", 0)
    monkeypatch.setattr(thesportsdb, "_pausa_ate", [0.0])
    monkeypatch.setattr(thesportsdb._sessao, "get", lambda *a, **k: _Resposta429())
    with pytest.raises(thesportsdb.requests.HTTPError):
        thesportsdb.buscar_jogadores("Hulk")
    with pytest.raises(thesportsdb.requests.ConnectionError, match="limite"):
        thesportsdb.buscar_jogadores("Hulk")


# ---------- Clube de cada artilheiro na temporada ----------

def test_artilharia_da_base_tem_os_gols_e_o_clube_daquela_temporada():
    from sb_web import painel

    lista = painel.artilharia(rotas.dados(), "2020")
    gabigol = next(a for a in lista if a["player"] == "Gabriel Barbosa")
    assert (gabigol["time"], gabigol["gols"]) == ("Flamengo", 14)
    assert gabigol["foto"].endswith("?temporada=2020") and gabigol["escudo"].endswith("?temporada=2020")
    # A lista da CBF de 2020 deixa de fora quem saiu do Brasil; a da base não.
    assert {"Claudinho", "Luciano"} <= {a["player"] for a in lista}
    assert [a["gols"] for a in lista] == sorted((a["gols"] for a in lista), reverse=True)


def test_clube_atual_da_cbf_e_trocado_pelo_da_temporada_na_base(cliente):
    fonte = rotas.fonte()
    temporada = fonte.temporada("2020")
    gabigol = {"atleta_id": 9, "nome": "Gabriel Barbosa Almeida", "apelido": "Gabriel Barbosa", "gols": 14,
               "cbf_id": 20008, "clube": "Santos FC-SP", "escudo": "santos.jpg"}
    corrigido = fonte.corrigir_clubes("2020", temporada, [gabigol])[0]
    assert (corrigido["clube"], corrigido["cbf_id"]) == ("Flamengo-RJ", 20016)
    assert corrigido["escudo"] == "https://conteudo.cbf.com.br/clubes/20016/escudo.jpg"


def test_fora_da_base_o_clube_vem_do_elenco_ja_lido(cliente):
    fonte = rotas.fonte()
    temporada = fonte.temporada("2026")  # elenco falso: De Arrascaeta no Flamengo
    arrascaeta = {"atleta_id": 521990, "nome": "Giorgian Daniel de Arrascaeta Benedetti",
                  "apelido": "De Arrascaeta", "gols": 9, "cbf_id": 20002, "clube": "Palmeiras-SP"}
    assert fonte.corrigir_clubes("2026", temporada, [arrascaeta])[0]["clube"] == "Flamengo-RJ"


def test_sem_certeza_fica_o_clube_da_fonte(cliente):
    fonte = rotas.fonte()
    desconhecido = {"atleta_id": 1, "nome": "Fulano de Tal", "apelido": "Fulano", "gols": 3,
                    "cbf_id": 20002, "clube": "Palmeiras-SP"}
    assert fonte.corrigir_clubes("2026", fonte.temporada("2026"), [desconhecido])[0]["clube"] == "Palmeiras-SP"


def test_proximo_da_tabela_da_cbf_traz_adversario_e_escudo():
    assert cbf._proximo(["nenhum"]) is None  # fim de temporada: a CBF manda uma lista com "nenhum"
    escudo = "https://conteudo.cbf.com.br/clubes/20052/escudo.jpg"
    assert cbf._proximo({"id": "20052", "time": "Athletico Paranaense - RJ", "escudo": escudo}) == {
        "adversario_id": 20052, "adversario": "Athletico Paranaense - RJ", "escudo": escudo}


def test_montar_geral_prefere_o_proximo_da_tabela_da_cbf():
    temporada = temporada_falsa()
    temporada["classificacao"][0]["proximo"] = {"adversario_id": 20002, "adversario": "Palmeiras - SP",
                                                "escudo": "https://conteudo.cbf.com.br/clubes/20002/escudo.jpg"}
    flamengo = classificacao.montar(temporada, "geral", {})["linhas"][0]
    assert flamengo["proximo"]["adversario_id"] == 20002
    assert flamengo["proximo"]["adversario"] == "Palmeiras"  # o nome da tabela oficial, não o da CBF
    assert flamengo["proximo"]["escudo"] == "https://conteudo.cbf.com.br/clubes/20002/escudo.jpg"
