"""Escudos e fotos do Wikimedia Commons (coleta/commons.py), sem rede: `consultar` é sempre falso."""
import json

import pandas as pd
import pytest

from coleta import commons, treinadores
from sb_web import painel, rotas

ARQUIVO = "http://commons.wikimedia.org/wiki/Special:FilePath/"


def pagina_arquivo(nome, tipo="image/svg+xml", autor="<a href='//x'>Clube &amp; Cia</a>", licenca="Public domain"):
    """Página de um arquivo na resposta de `prop=imageinfo` do Commons."""
    return {"title": f"File:{nome}", "imageinfo": [{
        "thumburl": f"https://thumb.wikimedia.org/{nome.replace(' ', '_')}/120px.png", "mime": tipo,
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{nome.replace(' ', '_')}",
        "extmetadata": {"Artist": {"value": autor}, "LicenseShortName": {"value": licenca}},
    }]}


def sparql(*linhas):
    return {"results": {"bindings": [{k: {"value": v} for k, v in linha.items() if v is not None} for linha in linhas]}}


class Wikimedia:
    """`consultar` falso: responde por endereço e guarda o que foi pedido."""

    def __init__(self, clubes=(), imagens=None, arquivos=(), jogadores=None, falhar=False):
        self.clubes, self.imagens, self.arquivos = clubes, imagens or {}, {a["title"]: a for a in arquivos}
        self.jogadores = jogadores or {}
        self.falhar = falhar
        self.pedidos = []

    def __call__(self, endereco, parametros):
        self.pedidos.append((endereco, parametros))
        if self.falhar:
            raise commons.requests.ConnectionError("Wikimedia fora do ar")
        if endereco == commons.SPARQL:
            if "P154" in parametros["query"]:
                return sparql(*self.clubes)
            clube = next(qid for qid in self.jogadores if f"wd:{qid} " in parametros["query"])
            return sparql(*self.jogadores[clube])
        titulos = parametros["titles"].split("|")
        if endereco == commons.API_WIKIPEDIA:
            return {"query": {"pages": [{"title": t, **({"pageimage": self.imagens[t]} if t in self.imagens else {})}
                                        for t in titulos]}}
        return {"query": {"pages": [self.arquivos.get(t, {"title": t, "missing": True}) for t in titulos]}}


# ---------- Leitura das respostas ----------

def test_nome_do_arquivo_e_enderecos():
    assert commons.arquivo_do_endereco(ARQUIVO + "Tite%202018%20(cropped).jpg") == "Tite 2018 (cropped).jpg"
    assert commons.arquivo_do_endereco(None) is None
    assert commons.miniatura("Tite 2018.jpg") == "https://commons.wikimedia.org/wiki/Special:FilePath/Tite_2018.jpg?width=120"
    assert commons.pagina_do_arquivo("File:gremio_logo.svg") == "https://commons.wikimedia.org/wiki/File:Gremio_logo.svg"


def test_informacoes_traz_miniatura_autor_sem_html_e_none_para_o_que_nao_esta_no_commons():
    wikimedia = Wikimedia(arquivos=[pagina_arquivo("Gremio logo.svg")])
    dados = commons.informacoes(["Gremio_logo.svg", "File:Corinthians simbolo.png", "Gremio logo.svg"], wikimedia)
    assert dados["Gremio logo.svg"] == {
        "arquivo": "Gremio logo.svg", "miniatura": "https://thumb.wikimedia.org/Gremio_logo.svg/120px.png",
        "tipo": "image/svg+xml", "autor": "Clube & Cia", "licenca": "Public domain",
        "pagina": "https://commons.wikimedia.org/wiki/File:Gremio_logo.svg",
    }
    assert dados["Corinthians simbolo.png"] is None  # só na Wikipédia, como uso restrito
    assert len(wikimedia.pedidos) == 1  # um lote, sem repetir o arquivo pedido duas vezes
    assert wikimedia.pedidos[0][1]["titles"] == "File:Gremio logo.svg|File:Corinthians simbolo.png"


def test_informacoes_divide_em_lotes_de_50():
    wikimedia = Wikimedia()
    commons.informacoes([f"Foto {n}.jpg" for n in range(120)], wikimedia)
    assert [len(p["titles"].split("|")) for _, p in wikimedia.pedidos] == [50, 50, 20]


def test_imagens_das_paginas_segue_redirecionamento_e_continuacao():
    partes = [
        {"continue": {"picontinue": "7", "continue": "||"},
         "query": {"redirects": [{"from": "Clube B", "to": "Clube B (Cidade)"}],
                   "pages": [{"title": "Clube A", "pageimage": "Clube_A_logo.svg"}, {"title": "Clube B (Cidade)"}]}},
        {"query": {"pages": [{"title": "Clube B (Cidade)", "pageimage": "Clube_B.png"}, {"title": "Clube C"}]}},
    ]
    pedidos = []

    def consultar(endereco, parametros):
        pedidos.append(parametros)
        return partes[len(pedidos) - 1]

    imagens = commons.imagens_das_paginas(["Clube A", "Clube B", "Clube C"], consultar)
    assert imagens == {"Clube A": "Clube A logo.svg", "Clube B": "Clube B.png", "Clube C": None}
    assert pedidos[0]["pilicense"] == "any" and pedidos[1]["picontinue"] == "7"


# ---------- Escudos ----------

CLUBES = (
    {"clube": "http://www.wikidata.org/entity/Q1", "titulo": "Clube A", "logo": ARQUIVO + "A%20antigo.svg"},
    # B: o infobox usa um arquivo local da Wikipédia e o P154 é uma fotografia do escudo.
    {"clube": "http://www.wikidata.org/entity/Q2", "titulo": "Clube B", "logo": ARQUIVO + "Foto%20do%20escudo%20B.jpg"},
    # C: sem página na Wikipédia (pt); sobra o P154.
    {"clube": "http://www.wikidata.org/entity/Q3", "titulo": None, "logo": ARQUIVO + "C%20logo.png"},
    {"clube": "http://www.wikidata.org/entity/Q4", "titulo": "Clube D", "logo": None},
)
QIDS = {10: "Q1", 20: "Q2", 30: "Q3", 40: "Q4"}


def wikimedia_dos_escudos(**opcoes):
    return Wikimedia(
        clubes=CLUBES, imagens={"Clube A": "A_logo.svg", "Clube B": "B_local.svg"},
        arquivos=[pagina_arquivo("A logo.svg"), pagina_arquivo("A antigo.svg"),
                  pagina_arquivo("Foto do escudo B.jpg", tipo="image/jpeg", licenca="CC BY 3.0"),
                  pagina_arquivo("C logo.png", tipo="image/png")],
        **opcoes,
    )


def test_buscar_escudos_prefere_o_infobox_e_so_aceita_arquivo_do_commons_que_nao_e_foto():
    wikimedia = wikimedia_dos_escudos()
    escudos = commons.buscar_escudos(QIDS, wikimedia)
    assert escudos[10]["arquivo"] == "A logo.svg"  # o do infobox vem antes do P154
    assert escudos[20] is None  # arquivo local da Wikipédia e fotografia: fica para a CBF
    assert escudos[30]["arquivo"] == "C logo.png" and escudos[30]["licenca"] == "Public domain"
    assert escudos[40] is None
    assert [endereco for endereco, _ in wikimedia.pedidos] == [commons.SPARQL, commons.API_WIKIPEDIA, commons.API_COMMONS]


def test_escudos_sao_lidos_uma_vez_e_guardados_so_como_texto(tmp_path):
    wikimedia = wikimedia_dos_escudos()
    fonte = commons.Commons(QIDS, tmp_path, wikimedia)
    assert fonte.escudo(10) == "https://thumb.wikimedia.org/A_logo.svg/120px.png"
    assert fonte.escudo(20) is None and fonte.escudo(999) is None
    assert len(wikimedia.pedidos) == 3  # todos os clubes de uma vez; os outros pedidos saem da memória
    assert [p.name for p in tmp_path.iterdir()] == ["commons-escudos.json"]
    assert json.loads((tmp_path / "commons-escudos.json").read_text(encoding="utf-8"))["escudos"]["30"]["arquivo"] == "C logo.png"

    depois_de_reiniciar = commons.Commons(QIDS, tmp_path, Wikimedia(falhar=True))
    assert depois_de_reiniciar.escudo(30) == "https://thumb.wikimedia.org/C_logo.png/120px.png"
    assert depois_de_reiniciar.consultar.pedidos == []  # veio do disco


def test_escudos_vencidos_sao_conferidos_de_novo_e_a_falha_mantem_os_anteriores(tmp_path):
    relogio = [1000.0]
    wikimedia = wikimedia_dos_escudos()
    fonte = commons.Commons(QIDS, tmp_path, wikimedia, validade=60, agora=lambda: relogio[0])
    fonte.escudo(10)
    relogio[0] += 30
    fonte.escudo(10)
    assert len(wikimedia.pedidos) == 3
    relogio[0] += 60
    wikimedia.falhar = True
    assert fonte.escudo(10) == "https://thumb.wikimedia.org/A_logo.svg/120px.png"  # o anterior continua valendo
    assert len(wikimedia.pedidos) == 4 and "fora do ar" in fonte.ultimo_erro
    fonte.escudo(10)
    assert len(wikimedia.pedidos) == 4  # durante a pausa, nem tenta


def test_sem_wikimedia_e_sem_cache_o_escudo_fica_para_a_reserva(tmp_path):
    fonte = commons.Commons(QIDS, tmp_path, Wikimedia(falhar=True))
    assert fonte.escudo(10) is None
    assert not list(tmp_path.iterdir())


# ---------- Fotos de jogadores ----------

def jogador(qid, nome, imagem, nascimento="1994-06-01T00:00:00Z"):
    return {"jogador": f"http://www.wikidata.org/entity/{qid}", "nome": nome, "nascimento": nascimento,
            "imagem": ARQUIVO + imagem}


ELENCOS = {
    "Q1": [
        jogador("Q100", "Giorgian De Arrascaeta", "Arrascaeta.jpg"),
        jogador("Q100", "Arrascaeta", "Arrascaeta.jpg"),
        jogador("Q100", "Arrascaeta", "Arrascaeta%20outra.jpg"),  # segunda imagem: vale a primeira
        jogador("Q101", "Bruno Henrique", "Bruno%20Henrique%20Pinto.jpg", "1990-12-30T00:00:00Z"),
        jogador("Q101", "Bruno Henrique Pinto", "Bruno%20Henrique%20Pinto.jpg", "1990-12-30T00:00:00Z"),
        jogador("Q102", "Bruno Henrique", "Bruno%20Henrique%20Corsini.jpg", "1989-10-21T00:00:00Z"),
        jogador("Q103", "Zico", "Zico.jpg", "1953-03-03T00:00:00Z"),
    ],
    "Q2": [jogador("Q104", "Felipe", "Felipe.jpg")],
}


def test_buscar_jogadores_junta_nomes_e_fica_com_a_primeira_imagem():
    jogadores = commons.buscar_jogadores("Q1", Wikimedia(jogadores=ELENCOS))
    arrascaeta = next(j for j in jogadores if j["id"] == "Q100")
    assert arrascaeta == {"id": "Q100", "arquivo": "Arrascaeta.jpg", "nascimento": 1994,
                          "nomes": ["giorgian de arrascaeta", "arrascaeta"]}
    assert len(jogadores) == 4


@pytest.mark.parametrize("nomes, temporadas, esperado", [
    (["Giorgian de Arrascaeta"], ["2019", "2025"], "Q100"),
    (["Bruno Henrique"], ["2025"], None),  # dois com o mesmo nome: na dúvida, nenhum
    (["Bruno Henrique", "Bruno Henrique Pinto"], ["2025"], "Q101"),  # o nome completo da CBF desempata
    (["Felipe Anderson"], ["2025"], None),  # só nome igual: não vira "Felipe"
    (["Zico"], ["2025"], None),  # homônimo de outra época: em 2025 teria 72 anos
    (["Zico"], [], "Q103"),
])
def test_escolher_jogador_exige_nome_igual_unico_e_idade_possivel(nomes, temporadas, esperado):
    jogadores = commons.buscar_jogadores("Q1", Wikimedia(jogadores=ELENCOS)) + \
        commons.buscar_jogadores("Q2", Wikimedia(jogadores=ELENCOS))
    achado = commons.escolher_jogador(nomes, jogadores, temporadas)
    assert (achado["id"] if achado else None) == esperado


def test_foto_do_jogador_le_cada_clube_uma_vez_e_consulta_so_o_arquivo_achado(tmp_path):
    wikimedia = Wikimedia(jogadores=ELENCOS, arquivos=[pagina_arquivo("Arrascaeta.jpg", "image/jpeg", "Fulano", "CC BY-SA 4.0")])
    fonte = commons.Commons(QIDS, tmp_path, wikimedia)
    redirecionado = "https://commons.wikimedia.org/wiki/Special:FilePath/Arrascaeta.jpg?width=120"
    assert fonte.foto_jogador(["Giorgian de Arrascaeta"], [10, 20, 999], ["2025"]) == redirecionado
    assert [endereco for endereco, _ in wikimedia.pedidos] == [commons.SPARQL, commons.SPARQL]  # a foto não custa requisição
    assert fonte.foto_jogador(["Felipe Anderson"], [10, 20], ["2025"]) is None
    assert fonte.foto_jogador(["Giorgian de Arrascaeta"], [10], ["2025"]) is not None
    assert len(wikimedia.pedidos) == 2  # os clubes já estavam guardados
    assert {p.name for p in tmp_path.iterdir()} == {"commons-jogadores.json", "commons-fotos.json"}
    # A foto mostrada entra nos créditos, que buscam autor e licença; depois vale a miniatura direta.
    assert [(l["arquivo"], l["autor"], l["licenca"]) for l in fonte.creditos()] == [("Arrascaeta.jpg", "Fulano", "CC BY-SA 4.0")]
    assert fonte.foto("Arrascaeta.jpg") == "https://thumb.wikimedia.org/Arrascaeta.jpg/120px.png"


def test_em_segundo_plano_o_pedido_volta_na_hora_e_a_leitura_fica_para_uma_thread(tmp_path):
    import threading

    liberar, terminou = threading.Event(), threading.Event()
    wikimedia = wikimedia_dos_escudos()

    def consultar_devagar(endereco, parametros):
        liberar.wait(5)
        resposta = wikimedia(endereco, parametros)
        if endereco == commons.API_COMMONS:
            terminou.set()
        return resposta

    fonte = commons.Commons(QIDS, tmp_path, consultar_devagar, em_segundo_plano=True)
    assert fonte.escudo(10) is None and fonte.escudo(30) is None  # nada guardado ainda: responde na hora
    liberar.set()
    assert terminou.wait(5)
    for _ in range(100):
        if fonte.escudo(10):
            break
        threading.Event().wait(0.02)
    assert fonte.escudo(10) == "https://thumb.wikimedia.org/A_logo.svg/120px.png"
    assert len(wikimedia.pedidos) == 3  # uma leitura só, mesmo com vários pedidos enquanto ela corria


def test_aquecer_le_escudos_e_todos_os_clubes_de_uma_vez(tmp_path):
    fonte = commons.Commons({10: "Q1", 20: "Q2"}, tmp_path, Wikimedia(clubes=CLUBES[:2], jogadores=ELENCOS,
                            imagens={"Clube A": "A_logo.svg"}, arquivos=[pagina_arquivo("A logo.svg")]), em_segundo_plano=True)
    assert fonte.aquecer() == {"escudos": 1, "jogadores_com_foto": 5, "erro": None}
    assert fonte.em_segundo_plano is True


def test_foto_sem_resposta_da_api_usa_o_redirecionamento_do_commons(tmp_path):
    fonte = commons.Commons(QIDS, tmp_path, Wikimedia(falhar=True))
    assert fonte.foto("Tite 2018.jpg") == "https://commons.wikimedia.org/wiki/Special:FilePath/Tite_2018.jpg?width=120"


def test_creditos_reunem_escudos_e_fotos_com_autor_e_licenca(tmp_path):
    wikimedia = wikimedia_dos_escudos()
    wikimedia.arquivos["File:Tite 2018.jpg"] = pagina_arquivo("Tite 2018.jpg", "image/jpeg", "Fulano", "CC BY-SA 4.0")
    fonte = commons.Commons(QIDS, tmp_path, wikimedia)
    linhas = fonte.creditos(["Tite 2018.jpg"])
    assert [(l["uso"], l["arquivo"], l["licenca"]) for l in linhas] == [
        ("Escudo", "A logo.svg", "Public domain"), ("Escudo", "C logo.png", "Public domain"),
        ("Foto", "Tite 2018.jpg", "CC BY-SA 4.0"),
    ]
    assert linhas[-1]["autor"] == "Fulano" and linhas[-1]["pagina"].endswith("File:Tite_2018.jpg")

    sem_rede = commons.Commons(QIDS, tmp_path / "vazio", Wikimedia(falhar=True))
    assert sem_rede.creditos(["Tite 2018.jpg"]) == [{  # sem a API, sobra o endereço da página do arquivo
        "arquivo": "Tite 2018.jpg", "pagina": "https://commons.wikimedia.org/wiki/File:Tite_2018.jpg",
        "autor": None, "licenca": None, "uso": "Foto",
    }]


# ---------- Acesso à API ----------

class Resposta:
    def __init__(self, status, corpo=None, cabecalhos=None):
        self.status_code, self._corpo, self.headers = status, corpo or {}, cabecalhos or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise commons.requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._corpo


def test_consultar_espera_o_retry_after_e_tenta_mais_uma_vez(monkeypatch):
    respostas = [Resposta(429, cabecalhos={"Retry-After": "1"}), Resposta(200, {"query": {}})]
    esperas = []
    monkeypatch.setattr(commons._sessao, "get", lambda *a, **k: respostas.pop(0))
    monkeypatch.setattr(commons.time, "sleep", esperas.append)
    monkeypatch.setattr(commons, "INTERVALO", 0)
    assert commons.consultar(commons.API_COMMONS, {"action": "query"}) == {"query": {}}
    assert esperas == [1.0]


def test_consultar_nao_insiste_quando_o_limite_continua_nem_espera_demais(monkeypatch):
    monkeypatch.setattr(commons.time, "sleep", lambda _s: None)
    monkeypatch.setattr(commons, "INTERVALO", 0)
    respostas = [Resposta(429, cabecalhos={"Retry-After": "1"}), Resposta(429, cabecalhos={"Retry-After": "1"})]
    monkeypatch.setattr(commons._sessao, "get", lambda *a, **k: respostas.pop(0))
    with pytest.raises(commons.requests.HTTPError):
        commons.consultar(commons.API_COMMONS, {})
    assert respostas == []

    respostas = [Resposta(429, cabecalhos={"Retry-After": "600"}), Resposta(200)]
    with pytest.raises(commons.requests.HTTPError):
        commons.consultar(commons.API_COMMONS, {})
    assert len(respostas) == 1  # dez minutos de espera: falha na hora


def test_consultar_erro_da_api_levanta(monkeypatch):
    monkeypatch.setattr(commons._sessao, "get", lambda *a, **k: Resposta(200, {"error": {"info": "título inválido"}}))
    monkeypatch.setattr(commons, "INTERVALO", 0)
    with pytest.raises(ValueError, match="título inválido"):
        commons.consultar(commons.API_COMMONS, {})


def test_user_agent_leva_o_contato_quando_informado(monkeypatch):
    import importlib

    import config

    monkeypatch.setenv("SCOUTBOARD_CONTATO", "https://exemplo.org/scoutboard")
    try:
        assert importlib.reload(config).USER_AGENT == "ScoutBoard/0.2 (projeto academico; https://exemplo.org/scoutboard)"
    finally:
        monkeypatch.delenv("SCOUTBOARD_CONTATO")
        assert importlib.reload(config).USER_AGENT == "ScoutBoard/0.2 (projeto academico)"


# ---------- Técnicos ----------

def test_coleta_de_tecnicos_guarda_o_arquivo_da_foto_sem_duplicar_linhas():
    def linha(tecnico, imagem=None):
        return {"club": "http://www.wikidata.org/entity/Q1", "coachLabel": tecnico, "start": "2024-01-01T00:00:00Z",
                "img": ARQUIVO + imagem if imagem else None}

    df = treinadores.interpretar(sparql(linha("Tite", "Tite%202018.jpg"), linha("Tite", "Tite%202022.jpg"), linha("Sem Foto")))
    assert df[["treinador", "foto"]].values.tolist() == [["Tite", "Tite 2018.jpg"], ["Sem Foto", None]]
    assert "wdt:P18" in treinadores.montar_consulta(["Q1"]) and "foto" in treinadores.COLUNAS


def tabela_de_tecnicos(**colunas):
    return pd.DataFrame({
        "team_id": [1, 2], "time_base": ["Time A", "Time B"], "qid_clube": ["Q1", "Q2"], "treinador": ["Tite", "Sem Foto"],
        "inicio": pd.to_datetime(["2024-01-01", "2024-01-01"]), "fim": pd.to_datetime([None, None]), "atual": [True, True],
        **colunas,
    })


def test_painel_poe_a_foto_so_no_tecnico_que_tem_arquivo_no_commons():
    metricas = pd.DataFrame({"temporada": ["2025"], "team_id": [1], "player_id": [1], "player": ["X"]})
    dados = painel.Dados(metricas, tabela_de_tecnicos(foto=["Tite 2018.jpg", None]), {1: "Time A", 2: "Time B"})
    assert dados.fotos_treinadores == {"tite": "Tite 2018.jpg"}
    assert painel.treinador(dados.treinadores, dados.nomes, 1, fotos=dados.fotos_treinadores)["foto"] == "/foto/treinador?nome=Tite"
    assert painel.treinador(dados.treinadores, dados.nomes, 2, fotos=dados.fotos_treinadores)["foto"] is None
    achados = {t["treinador"]: t for t in painel.buscar(dados, "tite")["treinadores"] + painel.buscar(dados, "sem foto")["treinadores"]}
    assert achados["Tite"]["foto"] == "/foto/treinador?nome=Tite" and "foto" not in achados["Sem Foto"]

    antigo = painel.Dados(metricas, tabela_de_tecnicos(), {1: "Time A"})  # parquet de antes das fotos
    assert antigo.fotos_treinadores == {}
    assert painel.treinador(antigo.treinadores, antigo.nomes, 1, fotos=antigo.fotos_treinadores)["foto"] is None


# ---------- Rotas ----------

def _time(nome):
    return next(t for t, n in rotas.dados().nomes.items() if n == nome)


def _player_id(nome):
    m = rotas.dados().metricas
    return int(m[(m["player"] == nome) & (m["temporada"] == "2025")]["player_id"].iloc[0])


def test_escudo_vem_do_commons_sem_consultar_a_cbf(cliente, cache_cbf, monkeypatch, commons_falso):
    def proibido(ano):
        raise AssertionError("o escudo do Commons não depende da tabela da CBF")

    monkeypatch.setattr(cache_cbf, "temporada", proibido)
    resposta = cliente.get(f"/escudo/{_time('Palmeiras')}?temporada=2022")
    assert resposta.status_code == 302
    assert resposta.headers["Location"] == commons_falso.ESCUDO
    assert "max-age" in resposta.headers["Cache-Control"]


def test_clube_sem_escudo_no_commons_usa_a_cbf(cliente):
    resposta = cliente.get(f"/escudo/{_time('Flamengo')}?temporada=2025")
    assert resposta.headers["Location"] == "https://conteudo.cbf.com.br/clubes/20016/escudo.jpg"


def test_tabela_da_pagina_times_pede_o_escudo_pela_rota_que_tenta_o_commons(cliente, cache_cbf):
    html = cliente.get("/times?temporada=2025").get_data(as_text=True)
    for nome in ("Palmeiras", "Flamengo", "Ceara"):
        assert f'src="/escudo/{_time(nome)}?temporada=2025"' in html
    assert "conteudo.cbf.com.br" not in html
    assert cache_cbf.temporada("2025")["classificacao"][0]["escudo"].startswith("https://conteudo.cbf.com.br/")  # a fonte fica intacta


def test_jogador_sem_foto_na_cbf_usa_o_commons_antes_do_thesportsdb(cliente, commons_falso, fotos_reserva):
    veiga = _player_id("Raphael Veiga")
    resposta = cliente.get(f"/foto/jogador/{veiga}")
    assert resposta.status_code == 302 and resposta.headers["Location"] == commons_falso.FOTO
    nomes, times, temporadas = commons_falso.buscas[-1]
    assert nomes == ("Raphael Veiga",) and _time("Palmeiras") in times and "2025" in temporadas
    assert fotos_reserva.buscas == []  # achou no Commons: nenhuma busca no TheSportsDB


def test_foto_do_tecnico_redireciona_para_o_commons(cliente, monkeypatch):
    monkeypatch.setattr(rotas.dados(), "fotos_treinadores", {"tite": "Tite 2018.jpg"})
    resposta = cliente.get("/foto/treinador?nome=Tite")
    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "https://commons.wikimedia.org/wiki/Special:FilePath/Tite_2018.jpg?width=120"
    assert cliente.get("/foto/treinador?nome=Desconhecido").status_code == 404
    assert cliente.get("/foto/treinador").status_code == 404


def test_pagina_de_creditos_lista_arquivo_autor_e_licenca(cliente, monkeypatch):
    monkeypatch.setattr(rotas.dados(), "fotos_treinadores", {"tite": "Tite 2018.jpg"})
    resposta = cliente.get("/creditos")
    html = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert "Palmeiras logo.svg" in html and "Public domain" in html and "Tite 2018.jpg" in html
    assert "créditos das imagens" in cliente.get("/").get_data(as_text=True)  # link no rodapé


# ---------- FotMob: foto pelo id, sem consultar nada ----------

def test_ids_do_fotmob_sao_lidos_juntados_e_gravados_como_texto(tmp_path):
    from coleta import fotmob

    arquivo = tmp_path / "fotmob_ids.json"
    origem = {"players": [{"id": 16886, "fm": 20276, "name": "Hulk"}, {"id": 5, "name": "Sem id"}],
              "teams": [{"id": 1239, "fm": 9770}]}
    assert fotmob.atualizar(arquivo, lambda: origem) == {"jogadores": 1, "times": 1}
    origem["players"] = [{"id": 27490, "fm": 30441}]  # o Hulk saiu do campeonato: o id dele continua guardado
    assert fotmob.atualizar(arquivo, lambda: origem) == {"jogadores": 2, "times": 1}
    imagens = fotmob.Imagens(fotmob.carregar(arquivo))
    assert imagens.foto(16886) == "https://images.fotmob.com/image_resources/playerimages/20276.png"
    assert imagens.escudo(1239) == "https://images.fotmob.com/image_resources/logo/teamlogo/9770.png"
    assert imagens.foto(999) is None and imagens.escudo(999) is None
    with pytest.raises(ValueError):
        fotmob.atualizar(arquivo, lambda: {"players": [], "teams": []})


def test_foto_com_id_do_fotmob_nao_consulta_cbf_nem_reservas(cliente, cache_cbf, commons_falso, fotos_reserva, fotmob_falso):
    arrascaeta = _player_id("Giorgian de Arrascaeta")
    fotmob_falso.jogadores[arrascaeta] = 123
    resposta = cliente.get(f"/foto/jogador/{arrascaeta}?temporada=2025")
    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "https://images.fotmob.com/image_resources/playerimages/123.png"
    assert cache_cbf.fotos == [] and commons_falso.buscas == [] and fotos_reserva.buscas == []


def test_escudo_fora_do_commons_usa_o_fotmob_antes_da_cbf(cliente, fotmob_falso):
    fotmob_falso.times[_time("Flamengo")] = 9770
    resposta = cliente.get(f"/escudo/{_time('Flamengo')}?temporada=2025")
    assert resposta.headers["Location"] == "https://images.fotmob.com/image_resources/logo/teamlogo/9770.png"


def test_arquivo_de_ids_do_projeto_cobre_os_times_e_jogadores_atuais():
    from coleta import fotmob

    ids = fotmob.carregar()
    assert len(ids["times"]) >= 20 and len(ids["jogadores"]) >= 700


# ---------- Percentis do jogador ----------

def test_percentis_comparam_por_90_minutos_so_quem_jogou_o_minimo():
    agg = pd.DataFrame({
        "player_id": [1, 2, 3, 4], "minutos": [900.0, 900.0, 1800.0, 90.0],
        **{m: [0, 0, 0, 0] for m in painel.METRICAS_RANKING},
    })
    agg["gols"] = [10, 5, 10, 9]  # o 4 faz 9 gols em 90 minutos, mas fica fora da comparação
    gols = {p["metrica"]: p for p in painel.percentis(agg, 1)}["gols"]
    assert gols == {"metrica": "gols", "rotulo": "Gols", "total": 10, "por_90": 1.0, "percentil": 100}
    assert {p["metrica"]: p for p in painel.percentis(agg, 3)}["gols"]["percentil"] == 67  # 0,5 por 90: empata com o 2
    assert painel.percentis(agg, 4) == []


def test_por_padrao_nenhuma_foto_custa_requisicao_por_jogador(cache_cbf, reserva_espn, fotos_reserva, commons_falso, fotmob_falso):
    """Sem fotos_lentas: FotMob (memória) e Commons (cache por clube); CBF e TheSportsDB ficam de fora."""
    from sb_web.fonte_cbf import FonteCBF

    fonte = FonteCBF(rotas.dados(), cache_cbf, reserva_espn, fotos_reserva, commons_falso, fotmob_falso, fotos_lentas=False)
    assert fonte.foto_jogador(_player_id("Giorgian de Arrascaeta"), "2025") is None  # só a CBF teria
    assert fonte.foto_jogador(_player_id("Raphael Veiga"), "2025") == commons_falso.FOTO
    # Foto da artilharia (atleta da CBF, até 20 por temporada) é liberada; a reserva por nome não.
    assert fonte.foto_atleta("2025", 521990) == (b"\xff\xd8jpeg", "image/jpeg")
    assert fonte.foto_por_nome("Bruno Henrique", "Flamengo") is None
    assert cache_cbf.fotos == [("2025", 521990)] and fotos_reserva.buscas == []
