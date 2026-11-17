import iniciar
import sb_web


class AppFalso:
    debug = False  # como no create_app sem FLASK_DEBUG

    def __init__(self):
        self.chamadas = []

    def run(self, **opcoes):
        self.chamadas.append(opcoes)


def preparar(monkeypatch):
    app_falso = AppFalso()
    monkeypatch.setattr(sb_web, "create_app", lambda: app_falso)
    return app_falso


def test_por_padrao_sobe_o_site_sem_atualizar_os_dados(monkeypatch):
    def nao_deveria_rodar():
        raise AssertionError("a atualização só roda com --atualizar-tecnicos")

    monkeypatch.setattr(iniciar, "atualizar_dados", nao_deveria_rodar)
    app_falso = preparar(monkeypatch)
    assert iniciar.main([]) == 0
    assert iniciar.main(["--sem-coleta", "--porta", "5123"]) == 0  # opção antiga: continua aceita
    app_falso.chamadas.pop(0)
    assert app_falso.chamadas == [{"host": "127.0.0.1", "port": 5123, "debug": False, "use_reloader": False}]


def test_atualizacao_roda_antes_do_site(monkeypatch):
    ordem = []
    monkeypatch.setattr(iniciar, "atualizar_dados", lambda: ordem.append("dados"))
    app_falso = preparar(monkeypatch)
    monkeypatch.setattr(app_falso, "run", lambda **_: ordem.append("site"))
    assert iniciar.main(["--atualizar-tecnicos"]) == 0
    assert ordem == ["dados", "site"]


def test_falha_na_atualizacao_nao_impede_o_site(monkeypatch, capsys):
    from coleta import treinadores

    def falha():
        raise OSError("sem internet")

    monkeypatch.setattr(treinadores, "coletar", falha)
    app_falso = preparar(monkeypatch)
    assert iniciar.main(["--atualizar-tecnicos"]) == 0
    assert len(app_falso.chamadas) == 1
    assert "sem internet" in capsys.readouterr().out


def test_iniciar_nao_consulta_fontes_externas(monkeypatch):
    """Nada da CBF, ESPN ou TheSportsDB é buscado ao subir: só quando uma página pede."""
    from coleta import cbf, espn, thesportsdb

    def proibido(*_, **__):
        raise AssertionError("fonte externa consultada ao iniciar")

    for modulo in (cbf, espn, thesportsdb):
        monkeypatch.setattr(modulo._sessao, "get", proibido)
    monkeypatch.setattr(iniciar, "atualizar_dados", lambda: None)
    app_falso = preparar(monkeypatch)
    assert iniciar.main([]) == 0
    assert len(app_falso.chamadas) == 1
