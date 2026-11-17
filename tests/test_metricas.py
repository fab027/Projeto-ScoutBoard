
import pandas as pd
import pytest
from socceraction.spadl import config as spadl

from config import METRICAS
from processamento import metricas


TIPO = {nome: i for i, nome in enumerate(spadl.actiontypes)}
SUCESSO = spadl.results.index("success")
FALHA = spadl.results.index("fail")
SAIDA = METRICAS


def evento(game_id, player_id, tipo, tempo, resultado=SUCESSO, nome="Jogador", time_team=1):
    return {
        "game_id": game_id,
        "player_id": float(player_id),
        "player": nome,
        "team_id": time_team,
        "type_id": TIPO[tipo],
        "result_id": resultado,
        "time_seconds": float(tempo),
        "start_x": 50.0,
        "start_y": 30.0,
    }


@pytest.fixture
def eventos_sinteticos():
    linhas = [
        # jogo 1, jogador 10: 2 desarmes, 1 interceptação, 1 finalização com gol
        evento(1, 10, "tackle", 100),
        evento(1, 10, "tackle", 500),
        evento(1, 10, "interception", 600),
        evento(1, 10, "shot", 900, resultado=SUCESSO),
        evento(1, 10, "shot", 1000, resultado=FALHA),
        # jogo 1, homônimo com outro id: não pode ser somado ao jogador 10
        evento(1, 11, "tackle", 200, nome="Jogador"),
        # passes: 2 certos, 1 errado
        evento(1, 10, "pass", 1100, resultado=SUCESSO),
        evento(1, 10, "pass", 1200, resultado=SUCESSO),
        evento(1, 10, "pass", 1300, resultado=FALHA),
        # evento com tempo corrompido: deve ser descartado
        evento(1, 10, "foul", 308855),
    ]
    # linha sem player_id: deve ser descartada
    sem_id = evento(1, 10, "tackle", 50)
    sem_id["player_id"] = None
    linhas.append(sem_id)
    return pd.DataFrame(linhas)


def test_contagens_por_tipo(eventos_sinteticos):
    m = metricas.metricas_por_jogador_jogo(eventos_sinteticos, 2019)
    linha = m[m.player_id == 10].iloc[0]
    assert linha.desarmes == 2
    assert linha.interceptacoes == 1
    assert linha.finalizacoes == 2
    assert linha.gols == 1
    assert linha.passes == 3
    assert linha.passes_certos == 2
    assert linha.faltas == 0


def test_homonimos_nao_se_misturam(eventos_sinteticos):
    m = metricas.metricas_por_jogador_jogo(eventos_sinteticos, 2019)
    homonimo = m[m.player_id == 11].iloc[0]
    assert homonimo.desarmes == 1
    assert len(m[m.player == "Jogador"]) == 2


def test_evento_com_tempo_corrompido_e_descartado(eventos_sinteticos):
    m = metricas.metricas_por_jogador_jogo(eventos_sinteticos, 2019)
    linha = m[m.player_id == 10].iloc[0]
    assert linha.faltas == 0
    assert linha.minutos_estimados == pytest.approx((1300 - 100) / 60)


def test_sem_player_id_nao_gera_linha(eventos_sinteticos):
    m = metricas.metricas_por_jogador_jogo(eventos_sinteticos, 2019)
    assert m.player_id.notna().all()


def test_chave_unica_no_resultado_sintetico(eventos_sinteticos):
    m = metricas.metricas_por_jogador_jogo(eventos_sinteticos, 2019)
    metricas.validar_chave_unica(m)


def test_validacao_detecta_duplicata():
    tabela = pd.DataFrame({"temporada": ["2019"] * 2, "game_id": [1, 1], "player_id": [10, 10]})
    with pytest.raises(ValueError):
        metricas.validar_chave_unica(tabela)


@pytest.mark.skipif(not SAIDA.exists(), reason="tabela ainda não gerada")
def test_arquivo_gerado_sem_duplicatas():
    m = pd.read_parquet(SAIDA)
    metricas.validar_chave_unica(m)
    assert m.temporada.nunique() == 7


@pytest.mark.skipif(not SAIDA.exists(), reason="tabela ainda não gerada")
def test_arquivo_gerado_gols_por_jogo_plausiveis():
    m = pd.read_parquet(SAIDA)
    gols_por_jogo = m.groupby("temporada").apply(
        lambda g: g.gols.sum() / g.game_id.nunique(), include_groups=False
    )
    assert gols_por_jogo.between(1.5, 3.5).all()


@pytest.mark.skipif(not SAIDA.exists(), reason="tabela ainda não gerada")
def test_arquivo_gerado_minutos_dentro_do_limite():
    m = pd.read_parquet(SAIDA)
    assert m.minutos_estimados.between(0, metricas.TEMPO_MAXIMO_S / 60).all()


def test_sem_placeholders_remove_id_zero_id_ausente_e_nome_numerico():
    eventos = pd.DataFrame({
        "player_id": [7.0, 0.0, float("nan"), 8.0],
        "player": ["Real", "0.0", "Desconhecido", "0.0"],
    })
    restante = metricas.sem_placeholders(eventos)
    assert list(restante["player"]) == ["Real"]
