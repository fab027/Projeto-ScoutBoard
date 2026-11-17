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
def metricas():
    return pd.DataFrame(
        [
            # Jogo 1: Time A 2 x 1 Time B
            linha("2025", 1, 1, 10, "Atacante A", gols=2, finalizacoes=4, passes_certos=20, posicao_x=80.0),
            linha("2025", 1, 1, 11, "Meia A", gols=0, passes_certos=35, desarmes=3, posicao_x=40.0, acoes_totais=30),
            linha("2025", 1, 2, 20, "Atacante B", gols=1, finalizacoes=2, passes_certos=10, posicao_x=70.0),
            # Jogo 2: Time B 1 x 1 Time A
            linha("2025", 2, 1, 10, "Atacante A", gols=1, finalizacoes=1, passes_certos=5, posicao_x=60.0),
            linha("2025", 2, 2, 20, "Atacante B", gols=1, finalizacoes=3, passes_certos=8, posicao_x=75.0),
            # Outra temporada, não deve entrar em 2025
            linha("2024", 3, 1, 10, "Atacante A", gols=9),
        ]
    )


@pytest.fixture
def dados(metricas):
    treinadores = pd.DataFrame(
        {
            "team_id": [1, 1],
            "time_base": ["Time A", "Time A"],
            "qid_clube": ["Q1", "Q1"],
            "treinador": ["Antigo", "Atual"],
            "inicio": pd.to_datetime(["2020-01-01", "2024-06-01"]),
            "fim": pd.to_datetime(["2024-05-01", None]),
            "atual": [False, True],
        }
    )
    return painel.Dados(metricas, treinadores, NOMES)


def test_agregar_soma_metricas_e_pondera_posicao(metricas):
    f = metricas[metricas["temporada"] == "2025"]
    agg = painel.agregar_jogadores(f, NOMES).set_index("player_id")
    assert agg.loc[10, "gols"] == 3  # 2 no jogo 1 + 1 no jogo 2
    assert agg.loc[10, "jogos"] == 2
    # Posição média ponderada por ações: (80*10 + 60*10) / 20 = 70
    assert agg.loc[10, "posicao_x"] == pytest.approx(70.0)
    assert agg.loc[11, "time"] == "Time A"


def test_ranking_jogadores_ordena_pela_metrica(metricas):
    agg = painel.agregar_jogadores(metricas[metricas["temporada"] == "2025"], NOMES)
    ranking = painel.ranking_jogadores(agg, "gols", limite=2)
    assert [r["player"] for r in ranking] == ["Atacante A", "Atacante B"]
    assert ranking[0]["gols"] == 3


def test_ranking_times_pontos_e_saldo(metricas):
    f = metricas[metricas["temporada"] == "2025"]
    tabela = {t["time"]: t for t in painel.ranking_times(f, NOMES)}
    # Time A: vitória 2x1 (3 pts) e empate 1x1 (1 pt) = 4 pts, gols 3 x 2
    assert tabela["Time A"]["pontos"] == 4
    assert tabela["Time A"]["gols_pro"] == 3
    assert tabela["Time A"]["gols_contra"] == 2
    assert tabela["Time A"]["saldo"] == 1
    assert tabela["Time B"]["pontos"] == 1


def test_ranking_times_ignora_jogo_com_um_time_so(metricas):
    f = metricas[(metricas["temporada"] == "2025") & (metricas["game_id"] == 2)]
    f = f[f["team_id"] == 1]
    assert painel.ranking_times(f, NOMES) == []


def test_premios_escolhe_o_maior_de_cada_categoria(metricas):
    agg = painel.agregar_jogadores(metricas[metricas["temporada"] == "2025"], NOMES)
    premios = {p["titulo"]: p for p in painel.premios(agg)}
    assert premios["Artilheiro"]["player"] == "Atacante A"
    assert premios["Mais desarmes"]["player"] == "Meia A"


def test_dispersao_normaliza_por_90_minutos(metricas):
    agg = painel.agregar_jogadores(metricas[metricas["temporada"] == "2025"], NOMES)
    pontos = {p["player_id"]: p for p in painel.dispersao(agg, "finalizacoes", "passes_certos", 0)}
    # Atacante A: 5 finalizações em 180 min estimados = 2.5 por 90 min
    assert pontos[10]["x"] == pytest.approx(2.5)


def test_dispersao_respeita_minimo_de_minutos(metricas):
    agg = painel.agregar_jogadores(metricas[metricas["temporada"] == "2025"], NOMES)
    assert painel.dispersao(agg, "gols", "passes_certos", 1000) == []


def test_painel_rejeita_entradas_invalidas(dados):
    with pytest.raises(ValueError, match="Temporada"):
        painel.painel(dados, "1999")
    with pytest.raises(ValueError, match="Métrica"):
        painel.painel(dados, "2025", x="nao_existe")
    with pytest.raises(ValueError, match="Jogo"):
        painel.painel(dados, "2025", jogo=999)


def test_painel_jogador_fora_do_recorte(dados):
    with pytest.raises(ValueError, match="recorte"):
        painel.painel(dados, "2025", time=2, jogador=10)


def test_painel_com_jogador_traz_detalhe_e_treinador(dados):
    r = painel.painel(dados, "2025", jogador=10)
    assert r["jogador"]["player"] == "Atacante A"
    assert r["treinador"]["atual"] == "Atual"
    assert [h["treinador"] for h in r["treinador"]["historico"]] == ["Antigo", "Atual"]


def test_painel_sem_filtros_nao_traz_treinador(dados):
    r = painel.painel(dados, "2025")
    assert r["treinador"] is None
    assert r["jogador"] is None
    assert len(r["opcoes"]["jogos"]) == 2
