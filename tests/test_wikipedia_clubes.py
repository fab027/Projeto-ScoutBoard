import pandas as pd
import pytest

from coleta import treinadores
from coleta import wikipedia as wikipedia_clubes

INFOBOX = """{{Info/Clube
| nome = Clube de Regatas do Flamengo
| imagem = Clube de Regatas do Flamengo logo.svg
| treinador = [[Leonardo Jardim]]<ref name=":1">{{Citar web|url=https://exemplo.com|titulo=Anúncio}}</ref>
}}"""


def test_tecnico_le_link_e_remove_nota_de_rodape():
    assert wikipedia_clubes.tecnico(INFOBOX) == "Leonardo Jardim"


def test_tecnico_usa_texto_do_link_com_alias():
    texto = "| treinador = [[Tite (treinador de futebol)|Tite]]"
    assert wikipedia_clubes.tecnico(texto) == "Tite"


def test_tecnico_sem_campo_devolve_none():
    assert wikipedia_clubes.tecnico("| nome = Algum Clube") is None


@pytest.fixture
def mapeamento():
    return pd.DataFrame(
        {
            "team_id": ["1", "2", "3"],
            "time_base": ["Time A", "Time B", "Time C"],
            "qid_wikidata": ["Q1", "Q2", "Q3"],
            "nome_wikidata": ["Pagina A", "Pagina B", "Pagina C"],
        }
    )


@pytest.fixture
def tabela_wikidata():
    # Time 1 tem técnico atual no Wikidata; time 2 não tem; time 3 não aparece.
    return pd.DataFrame(
        {
            "team_id": [1, 1, 2],
            "time_base": ["Time A", "Time A", "Time B"],
            "qid_clube": ["Q1", "Q1", "Q2"],
            "treinador": ["Antigo", "Atual Wikidata", "Ex-tecnico"],
            "inicio": pd.to_datetime(["2020-01-01", "2024-01-01", "2019-01-01"]),
            "fim": pd.to_datetime(["2023-12-01", None, "2021-01-01"]),
            "atual": [False, True, False],
            "fonte": ["Wikidata"] * 3,
        }
    )


def test_complementar_wikipedia_vence_quando_diverge_do_wikidata(monkeypatch, mapeamento, tabela_wikidata):
    textos = {
        "Pagina A": "| treinador = [[Outro Nome]]",
        "Pagina B": "| treinador = [[Novo Tecnico]]",
        "Pagina C": "| treinador = [[Qualquer]]",
    }
    monkeypatch.setattr(treinadores, "wikitexto", lambda titulo: textos[titulo])
    monkeypatch.setattr(treinadores, "PAUSA_WIKIPEDIA", 0)

    combinada, complementos = treinadores.complementar_com_wikipedia(tabela_wikidata, mapeamento)

    atuais = combinada[combinada["atual"]].set_index("team_id")["treinador"].to_dict()
    assert atuais["1"] == "Outro Nome"  # a Wikipédia é a fonte do técnico atual
    assert atuais["2"] == "Novo Tecnico"
    assert "3" in atuais

    fontes = combinada.set_index("team_id")["fonte"].to_dict()
    assert fontes["1"] == treinadores.FONTE_WIKIPEDIA
    assert fontes["2"] == treinadores.FONTE_WIKIPEDIA
    assert complementos["conflitos"] == [
        {"time": "Time A", "wikidata": "Atual Wikidata", "wikipedia": "Outro Nome"}
    ]
    antigo = combinada[(combinada["team_id"] == "1") & (combinada["treinador"] == "Atual Wikidata")]
    assert not antigo["atual"].iloc[0]  # o que era atual vira histórico, sem sumir
    assert complementos["erros_wikipedia"] == []


def test_complementar_guarda_erro_sem_derrubar_a_coleta(monkeypatch, mapeamento, tabela_wikidata):
    def falha(titulo):
        raise RuntimeError("Wikipédia indisponível")

    monkeypatch.setattr(treinadores, "wikitexto", falha)
    monkeypatch.setattr(treinadores, "PAUSA_WIKIPEDIA", 0)

    combinada, complementos = treinadores.complementar_com_wikipedia(tabela_wikidata, mapeamento)

    assert len(combinada) == len(tabela_wikidata)  # nada foi adicionado
    assert len(complementos["erros_wikipedia"]) == 3
    assert complementos["conflitos"] == []
