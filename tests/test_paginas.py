import pandas as pd
import pytest

from sb_web import painel

NOMES = {1: "Time A", 2: "Time B"}


def linha(temporada, jogo, time, jogador, nome, **metricas):
    base = {
        "temporada": temporada,
        "game_id": jogo,
        "team_id": time,
        "player_id": jogador,
        "player": nome,
        "minutos_estimados": 90.0,
        "acoes_totais": 10,
        "posicao_x": 50.0,
        "posicao_y": 30.0,
        "gols": 0,
        "passes": 0,
        "passes_certos": 0,
        "desarmes": 0,
        "interceptacoes": 0,
        "cortes": 0,
        "faltas": 0,
        "dribles": 0,
        "finalizacoes": 0,
        "acoes_goleiro": 0,
    }
    base.update(metricas)
    return base


@pytest.fixture
def dados(tmp_path):
    metricas = pd.DataFrame(
        [
            linha("2025", 1, 1, 10, "José Atacante", gols=2, passes_certos=5),
            linha("2025", 1, 2, 20, "Ana Meia", gols=0, passes_certos=9, desarmes=4),
            linha("2024", 2, 1, 10, "José Atacante", gols=7),
        ]
    )
    treinadores = pd.DataFrame(
        {
            "team_id": [1, 2],
            "time_base": ["Time A", "Time B"],
            "qid_clube": ["Q1", "Q2"],
            "treinador": ["Tite Silva", "Tite Silva"],
            "inicio": pd.to_datetime(["2020-01-01", "2021-01-01"]),
            "fim": pd.to_datetime(["2020-12-01", None]),
            "atual": [False, True],
        }
    )
    return painel.Dados(metricas, treinadores, NOMES)


def test_normalizar_ignora_acento_e_caixa():
    assert painel.normalizar("José  ÁTACANTE") == "jose atacante"


def test_buscar_jogador_sem_acento(dados):
    resultado = painel.buscar(dados, "jose")
    assert [j["player"] for j in resultado["jogadores"]] == ["José Atacante"]
    jogador = resultado["jogadores"][0]
    assert jogador["foto"] == "/foto/jogador/10?temporada=2025"
    assert jogador["temporada"] == "2025"


def test_buscar_treinador_marca_atual_e_escudo(dados):
    resultado = painel.buscar(dados, "tite")
    times = {t["team_id"]: t for t in resultado["treinadores"]}
    assert times[2]["atual"] is True
    assert times[1]["atual"] is False
    assert times[1]["escudo"] == "/escudo/1"
    assert "foto" not in times[1]


def test_buscar_termo_curto_nao_retorna_nada(dados):
    assert painel.buscar(dados, "a") == {"jogadores": [], "treinadores": []}


def test_pagina_rankings_traz_foto_e_escudo(dados):
    pagina = painel.pagina_rankings(dados, "2025", "gols")
    primeiro = pagina["ranking"][0]
    assert primeiro["player"] == "José Atacante"
    assert primeiro["foto"] == "/foto/jogador/10?temporada=2025"
    assert primeiro["escudo"] == "/escudo/1?temporada=2025"


def test_pagina_rankings_rejeita_metrica_invalida(dados):
    with pytest.raises(ValueError, match="Métrica"):
        painel.pagina_rankings(dados, "2025", "nao_existe")


def test_pagina_jogadores_filtra_por_time_e_nome(dados):
    pagina = painel.pagina_jogadores(dados, "2025", time=2)
    assert [j["player"] for j in pagina["jogadores"]] == ["Ana Meia"]
    pagina = painel.pagina_jogadores(dados, "2025", termo="atac")
    assert [j["player"] for j in pagina["jogadores"]] == ["José Atacante"]


def test_tabela_da_base_tem_escudo(dados):
    tabela = painel.pagina_times(dados, "2025")["tabela"]
    assert {t["team_id"] for t in tabela} == {1, 2}
    assert {t["team_id"]: t["escudo"] for t in tabela} == {1: "/escudo/1?temporada=2025", 2: "/escudo/2?temporada=2025"}


def test_paginas_respondem_200(cliente):
    for rota in ["/rankings", "/jogadores", "/times", "/busca?q=kaio"]:
        resposta = cliente.get(rota)
        assert resposta.status_code == 200, rota


def test_cabecalho_tem_busca_e_links(cliente):
    corpo = cliente.get("/times").get_data(as_text=True)
    assert 'action="/busca"' in corpo
    assert 'href="/rankings"' in corpo
    assert 'href="/jogadores"' in corpo


def test_rankings_com_temporada_invalida_devolve_400(cliente):
    resposta = cliente.get("/rankings?temporada=1999")
    assert resposta.status_code == 400
    assert "Temporada" in resposta.get_data(as_text=True)


def test_api_busca_devolve_treinadores(cliente):
    dados_json = cliente.get("/api/busca?q=tite").get_json()
    assert "treinadores" in dados_json and "jogadores" in dados_json
    assert any(t["treinador"] == "Tite" for t in dados_json["treinadores"])


def test_busca_vazia_nao_quebra(cliente):
    assert cliente.get("/busca").status_code == 200
    assert cliente.get("/api/busca?q=").get_json() == {"jogadores": [], "treinadores": []}


def test_cabecalho_tem_alternador_de_tema(cliente):
    corpo = cliente.get("/times").get_data(as_text=True)
    assert 'id="alternar-tema"' in corpo
    assert 'src="/static/tema.js"' in corpo
    assert '"scoutboard-tema"' in corpo


def test_script_do_tema_e_css_servidos(cliente):
    assert cliente.get("/static/tema.js").status_code == 200
    css = cliente.get("/static/style.css").get_data(as_text=True)
    assert 'data-theme="dark"' in css
    assert "--placar" in css
