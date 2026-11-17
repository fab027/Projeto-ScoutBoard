import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from coleta import treinadores

FIXTURE = Path(__file__).parent / "fixtures" / "wikidata_treinadores_amostra.json"
MAPEAMENTO = pd.DataFrame(
    {"team_id": ["1", "2"], "time_base": ["Time A", "Time B"], "qid_wikidata": ["Q1", "Q2"]}
)


class RespostaFalsa:
    def __init__(self, status, corpo=None):
        self.status_code = status
        self._corpo = corpo or {}

    def json(self):
        return self._corpo


class SessaoFalsa:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = 0

    def get(self, *args, **kwargs):
        self.chamadas += 1
        return self.respostas.pop(0)


def corpo_sparql(*linhas):
    return {
        "results": {
            "bindings": [
                {
                    "club": {"value": f"http://www.wikidata.org/entity/{qid}"},
                    "coachLabel": {"value": nome},
                    **({"start": {"value": inicio}} if inicio else {}),
                    **({"end": {"value": fim}} if fim else {}),
                }
                for qid, nome, inicio, fim in linhas
            ]
        }
    }


@pytest.fixture
def dados_sinteticos():
    return treinadores.interpretar(
        corpo_sparql(
            ("Q1", "Antigo", "2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z"),
            ("Q1", "Atual", "2021-02-01T00:00:00Z", None),
            ("Q2", "Unico", "2022-03-01T00:00:00Z", None),
        )
    )


def test_interpretar_converte_datas_e_ids():
    df = treinadores.interpretar(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert {"qid_clube", "treinador", "inicio", "fim"} <= set(df.columns)
    assert len(df) > 0
    assert df["inicio"].dropna().map(lambda d: isinstance(d, pd.Timestamp)).all()
    assert df["qid_clube"].str.match(r"^Q\d+$").all()


def test_interpretar_rejeita_formato_inesperado():
    with pytest.raises(ValueError):
        treinadores.interpretar({"outra_coisa": 1})


def test_montar_tabela_marca_um_tecnico_atual_por_time(dados_sinteticos):
    tabela = treinadores.montar_tabela(dados_sinteticos, MAPEAMENTO)
    atuais = tabela[tabela["atual"]]
    assert sorted(atuais["treinador"]) == ["Atual", "Unico"]
    assert atuais["team_id"].is_unique


def test_montar_tabela_descarta_clubes_fora_do_mapeamento(dados_sinteticos):
    extra = treinadores.interpretar(corpo_sparql(("Q99", "Fora", "2020-01-01T00:00:00Z", None)))
    tabela = treinadores.montar_tabela(pd.concat([dados_sinteticos, extra]), MAPEAMENTO)
    assert "Fora" not in set(tabela["treinador"])


def test_validar_aceita_coleta_normal(dados_sinteticos):
    tabela = treinadores.montar_tabela(dados_sinteticos, MAPEAMENTO)
    metricas = treinadores.validar(tabela, MAPEAMENTO, anterior=None)
    assert metricas["times_com_dados"] == 2
    assert metricas["times_com_tecnico_atual"] == 2


def test_validar_falha_com_tabela_vazia():
    with pytest.raises(ValueError, match="vazia"):
        treinadores.validar(pd.DataFrame(columns=treinadores.COLUNAS), MAPEAMENTO, None)


def test_validar_falha_se_faltar_muitos_times(dados_sinteticos):
    mapeamento_grande = pd.DataFrame(
        {
            "team_id": [str(i) for i in range(10)],
            "time_base": [f"Time {i}" for i in range(10)],
            "qid_wikidata": [f"Q{i}" for i in range(10)],
        }
    )
    tabela = treinadores.montar_tabela(dados_sinteticos, mapeamento_grande)
    with pytest.raises(ValueError, match="sem dados"):
        treinadores.validar(tabela, mapeamento_grande, None)


def test_validar_detecta_queda_de_volume(dados_sinteticos):
    tabela = treinadores.montar_tabela(dados_sinteticos, MAPEAMENTO)
    anterior = {"registros": 100}
    with pytest.raises(ValueError, match="Queda de volume"):
        treinadores.validar(tabela, MAPEAMENTO, anterior)


def test_requisitar_tenta_de_novo_em_erro_temporario(monkeypatch):
    monkeypatch.setattr(treinadores.time, "sleep", lambda s: None)
    sessao = SessaoFalsa([RespostaFalsa(503), RespostaFalsa(429), RespostaFalsa(200, {"ok": True})])
    assert treinadores.requisitar("consulta", sessao) == {"ok": True}
    assert sessao.chamadas == 3


def test_requisitar_desiste_em_erro_permanente(monkeypatch):
    monkeypatch.setattr(treinadores.time, "sleep", lambda s: None)
    sessao = SessaoFalsa([RespostaFalsa(400)])
    with pytest.raises(RuntimeError, match="HTTP 400"):
        treinadores.requisitar("consulta", sessao)
    assert sessao.chamadas == 1


def test_coletar_em_falha_mantem_arquivo_anterior(tmp_path, monkeypatch, dados_sinteticos):
    saida = tmp_path / "treinadores.parquet"
    status = tmp_path / "status.json"
    tabela_antiga = treinadores.montar_tabela(dados_sinteticos, MAPEAMENTO)
    tabela_antiga.to_parquet(saida, index=False)
    status.write_text(json.dumps({"registros": 3, "coletado_em": "2026-01-01T00:00:00+00:00"}))

    monkeypatch.setattr(treinadores, "SAIDA", saida)
    monkeypatch.setattr(treinadores, "STATUS", status)
    monkeypatch.setattr(treinadores, "MAPEAMENTO", tmp_path / "mapa.csv")
    MAPEAMENTO.to_csv(tmp_path / "mapa.csv", index=False)
    monkeypatch.setattr(treinadores.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError):
        treinadores.coletar(sessao=SessaoFalsa([RespostaFalsa(500)] * treinadores.TENTATIVAS))

    assert len(pd.read_parquet(saida)) == len(tabela_antiga)
    gravado = json.loads(status.read_text(encoding="utf-8"))
    assert gravado["ultimo_erro"]
    assert gravado["coletado_em"] == "2026-01-01T00:00:00+00:00"


@pytest.mark.skipif(not treinadores.STATUS.exists(), reason="coleta ainda não executada")
def test_coleta_nao_esta_defasada():
    """Falha se a última coleta boa tiver mais de 14 dias: o sinal de que os dados pararam."""
    status = treinadores.ler_status()
    coletado = dt.datetime.fromisoformat(status["coletado_em"])
    idade = dt.datetime.now(dt.UTC) - coletado
    assert idade < dt.timedelta(days=14), f"Última coleta há {idade.days} dias"


@pytest.mark.skipif(not treinadores.STATUS.exists(), reason="coleta ainda não executada")
def test_status_sem_erro_pendente():
    status = treinadores.ler_status()
    assert status.get("ultimo_erro") in (None, ""), status.get("ultimo_erro")


@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="teste ao vivo: defina RUN_LIVE=1")
def test_contrato_ao_vivo_do_wikidata():
    """Consulta real: detecta mudança de esquema ou queda do serviço antes da coleta de produção."""
    mapeamento = treinadores.carregar_mapeamento()
    resposta = treinadores.requisitar(treinadores.montar_consulta(mapeamento["qid_wikidata"].tolist()))
    tabela = treinadores.montar_tabela(treinadores.interpretar(resposta), mapeamento)
    metricas = treinadores.validar(tabela, mapeamento, anterior=None)
    assert metricas["times_com_tecnico_atual"] >= 20
