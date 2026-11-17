"""Comando importar-brutos: orientação dos times no campo (funções puras, sem banco)."""
import pandas as pd

from sb_web.ext.cli import MAX_X, normalizar_orientacao_spadl


def test_time_que_ataca_para_a_esquerda_tem_o_campo_espelhado():
    """O time 10 chuta da própria direita (x=20, ataca para x=0): as ações dele são espelhadas em X."""
    eventos = pd.DataFrame({
        "game_id": [1, 1, 1, 1], "team_id": [10, 10, 20, 20], "period_id": [1, 1, 1, 1],
        "type_id": [11, 0, 11, 0],  # 11 = finalização, 0 = passe
        "start_x": [20.0, 30.0, 90.0, 60.0], "start_y": [10.0, 20.0, 30.0, 40.0],
        "end_x": [25.0, 25.0, 95.0, 70.0], "end_y": [11.0, 21.0, 31.0, 41.0],
    })

    saida = normalizar_orientacao_spadl(eventos)

    assert saida.loc[eventos["team_id"] == 10, "start_x"].tolist() == [MAX_X - 20.0, MAX_X - 30.0]
    assert saida.loc[eventos["team_id"] == 20, "start_x"].tolist() == [90.0, 60.0]  # já ataca para a direita
    assert "_dx" not in saida.columns  # coluna auxiliar não vaza para o banco
