import json

import pytest

from coleta import nomes, whoscored


def test_normalizar_ignora_acento_caixa_e_espacos():
    assert nomes.normalizar("  Atlético   Mineiro ") == "atletico mineiro"


def test_melhor_correspondencia_aceita_nome_igual_ou_muito_parecido():
    candidatos = {1: "Gabriel Barbosa", 2: "Pedro"}
    assert nomes.melhor_correspondencia("gabriel barbosa", candidatos) == 1
    assert nomes.melhor_correspondencia("Gabriel Barbosaa", candidatos) == 1
    assert nomes.melhor_correspondencia("Pedro Henrique", candidatos, limiar=0.9) is None


def test_configurar_ligas_preserva_o_que_ja_existia(tmp_path):
    arquivo = tmp_path / "league_dict.json"
    arquivo.write_text(json.dumps({"Outra": {"X": "y"}, "WhoScored": {"BRA-Brasileirao": "antigo"}}), encoding="utf-8")
    whoscored.configurar_ligas(tmp_path)
    gravado = json.loads(arquivo.read_text(encoding="utf-8"))
    assert gravado["Outra"] == {"X": "y"}
    assert gravado["WhoScored"]["BRA-Brasileirao"] == "Brazil-Brasileirão"
    assert "SA-Libertadores" in gravado["WhoScored"]


def test_tolerante_supre_so_as_chaves_conhecidas():
    chamadas = []

    def original(dicionario, chave):
        chamadas.append(chave)
        return dicionario[chave]

    assertget = whoscored._tolerante(original)
    assert assertget({}, "period") == {"value": 1, "displayName": "FirstHalf"}
    assert assertget({"minute": 7}, "expandedMinute") == 7
    assert assertget({"playerId": 99}, "playerId") == 99
    assert assertget({}, "playerId") == 0
    assert chamadas == ["playerId"]


def test_parser_tolerante_restaura_o_original_ao_sair():
    from socceraction.data.opta.parsers import whoscored as opta_ws

    original = opta_ws.assertget
    with whoscored.parser_tolerante():
        assert opta_ws.assertget is not original
    assert opta_ws.assertget is original


def test_ler_ids_aceita_uma_linha_por_jogo(tmp_path):
    arquivo = tmp_path / "ids.txt"
    arquivo.write_text("1457711\n\n1457712\nnao-e-numero\n", encoding="utf-8")
    assert whoscored._ler_ids(str(arquivo)) == [1457711, 1457712]


@pytest.mark.parametrize("ano", ["2019", "2025"])
def test_temporadas_da_coleta_seguem_o_nome_dos_arquivos(ano, tmp_path):
    from config import DADOS_BRUTOS

    assert (DADOS_BRUTOS / f"BRA-Brasileirao_{ano}.parquet").exists()
