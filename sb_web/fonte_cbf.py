"""Escudos, fotos e classificação ligados aos ids da base (team_id e player_id do WhoScored).

Fotos de jogadores vêm primeiro do CDN do FotMob, pelo id guardado em dados/fotmob_ids.json: é só
uma consulta à memória, sem acessar nada. Quem não tem id lá usa o Wikimedia Commons (uma leitura
por clube a cada 30 dias). As fontes que custam uma requisição por jogador na hora da página (CBF
e TheSportsDB) só entram com `fotos_lentas` (config.FOTOS_LENTAS), desligado por padrão.

Classificação e jogos vêm da CBF, com a ESPN de reserva (a CBF bloqueia o IP depois de rajadas).

Escudos e fotos de técnicos vêm do Wikimedia Commons (coleta.commons): uma leitura vale para todos
os clubes e temporadas e não depende da CBF. O clube sem escudo no Commons usa o do FotMob e, sem
ele, o da CBF ou da ESPN.

Tudo sob demanda: cada foto consulta só a temporada da página que a pediu, e a foto de um jogador
lê só a página do time dele (coleta.cbf.Cache explica os níveis).

Os ids da CBF mudam quando o clube vira SAF (Cruzeiro, Botafogo, Vasco...), então o casamento
de times é feito por temporada e por fonte. O de jogadores usa o elenco do time na CBF.
"""
from coleta import cbf, commons, espn, fotmob, thesportsdb
from coleta.cbf import ERROS_FONTE as ERROS_CBF
from coleta.nomes import normalizar
from config import FOTOS_LENTAS
from sb_web.classificacao import nome_exibicao as classificacao_nome
from sb_web.painel import Dados

CANDIDATOS_PARA_DESEMPATE = 4  # homônimos no elenco cujas páginas valem ser lidas para desempatar


class FonteCBF:
    def __init__(self, dados: Dados, cache: cbf.Cache | None = None, reserva: cbf.Cache | None = None,
                 fotos_reserva: thesportsdb.Fotos | None = None, commons_: commons.Commons | None = None,
                 fotmob_: fotmob.Imagens | None = None, fotos_lentas: bool = FOTOS_LENTAS):
        self.dados = dados
        self.fotos_lentas = fotos_lentas
        self.fotmob = fotmob_ or fotmob.Imagens()
        self.commons = commons_ or commons.Commons(em_segundo_plano=True)  # pedido de imagem nunca espera a rede
        self.cache = cache or cbf.Cache()
        self.reserva = reserva or cbf.Cache(
            ler_tabela=espn.tabela, ler_time=espn.time_da_temporada, prefixo="espn-", paralelo=4,
        )
        self.fotos_reserva = fotos_reserva or thesportsdb.Fotos()
        self._times: dict[tuple[str, str], dict[int, int]] = {}
        self._atletas: dict[tuple[int, str], dict | None] = {}
        self._marcadores: dict[str, list] = {}
        # Temporada, time e nome de cada passagem do jogador, da mais recente para a mais antiga.
        passagens = dados.metricas[["player_id", "temporada", "team_id", "player"]].drop_duplicates()
        self._passagens = passagens.sort_values("temporada", ascending=False).set_index("player_id").sort_index(
            kind="stable"
        )
        temporadas = dados.metricas[["team_id", "temporada"]].drop_duplicates().sort_values("temporada", ascending=False)
        # team_id -> temporadas do time na base, da mais recente para a mais antiga
        self._temporadas_do_time = temporadas.groupby("team_id")["temporada"].apply(list).to_dict()

    def _passagens_de(self, player_id: int) -> list[tuple[str, int, str]]:
        if player_id not in self._passagens.index:
            return []
        linhas = self._passagens.loc[[player_id]]
        return list(linhas[["temporada", "team_id", "player"]].itertuples(index=False, name=None))

    def _passagem(self, player_id: int, ano: str | None) -> tuple[str, int, str] | None:
        """A passagem do jogador na temporada `ano` ou, sem ela, a mais recente."""
        passagens = self._passagens_de(player_id)
        return next((p for p in passagens if p[0] == ano), passagens[0] if passagens else None)

    def temporada(self, ano: str, completa: bool = False) -> dict:
        """Tabela pela CBF ou, se ela falhar, pela ESPN (o campo "fonte" diz qual veio).

        Com `completa`, também os jogos de todos os times (recortes de mandante e visitante).
        """
        try:
            return self.cache.completa(ano) if completa else self.cache.temporada(ano)
        except ERROS_CBF as erro_cbf:
            try:
                return self.reserva.completa(ano) if completa else self.reserva.temporada(ano)
            except ERROS_CBF:
                raise erro_cbf from None

    def _casar(self, ano: str, temporada: dict) -> dict[int, int]:
        chave = (temporada.get("fonte", "CBF"), ano)
        if chave not in self._times:
            if ano in self.dados.temporadas:
                ids = self.dados.temporada(ano)["team_id"].unique()
            else:  # temporada só nas fontes externas (ex.: a atual): tenta todos os times conhecidos
                ids = list(self.dados.nomes)
            nossos = {int(t): self.dados.nomes.get(int(t), "") for t in ids}
            self._times[chave] = cbf.casar_times(nossos, temporada["classificacao"])
        return self._times[chave]

    def times(self, ano: str) -> dict[int, int]:
        """team_id da base -> id do time na fonte que respondeu para a temporada `ano`."""
        return self._casar(ano, self.temporada(ano))

    def links(self, ano: str) -> dict[int, int]:
        """id do time na fonte -> team_id da base, só para temporadas que existem na base."""
        if ano not in self.dados.temporadas:
            return {}
        return {fonte_id: team_id for team_id, fonte_id in self.times(ano).items()}

    def escudo(self, team_id: int, ano: str | None = None) -> str | None:
        """Endereço do escudo no Commons ou, se o clube não está lá, no FotMob, na CBF ou na ESPN.

        Só a reserva consulta uma temporada: `ano` ou, sem ela, a última do time na base.
        """
        sem_cbf = self.commons.escudo(team_id) or self.fotmob.escudo(team_id)
        if sem_cbf:
            return sem_cbf
        temporadas = self._temporadas_do_time.get(team_id, [])
        if ano not in temporadas:
            ano = temporadas[0] if temporadas else None
        if ano is None:
            return None
        temporada = self.temporada(ano)
        fonte_id = self._casar(ano, temporada).get(team_id)
        linha = next((l for l in temporada["classificacao"] if l["cbf_id"] == fonte_id), None)
        return linha["escudo"] if linha else None

    def com_escudos(self, ano: str, temporada: dict) -> dict:
        """Cópia da temporada em que o escudo dos times da base passa pela rota /escudo.

        Assim a tabela mostra o escudo do Commons (com o da fonte de reserva), igual ao resto do
        site. O time que a base não conhece (recém-promovido) fica com o escudo que a fonte informou.
        """
        da_base = {fonte_id: team_id for team_id, fonte_id in self._casar(ano, temporada).items()}
        linhas = [
            {**linha, "escudo": f"/escudo/{da_base[linha['cbf_id']]}?temporada={ano}"} if linha["cbf_id"] in da_base else linha
            for linha in temporada["classificacao"]
        ]
        return {**temporada, "classificacao": linhas}

    def _jogos_na_base(self, player_id: int, ano: str) -> int:
        base = self.dados.temporada(ano)
        return int(base.loc[base["player_id"] == player_id, "game_id"].nunique())

    def atleta(self, player_id: int, ano: str | None = None) -> dict | None:
        """Atleta da CBF (atleta_id, apelido, nome, temporada) do jogador, ou None sem casamento seguro.

        Lê só a página do time do jogador naquela temporada. Entre homônimos (dois "Pedro"), vence
        quem teve, na CBF, um número de partidas parecido com o de jogos dele na base.
        """
        passagem = self._passagem(player_id, ano)
        if passagem is None:
            return None
        ano, team_id, nome = passagem
        chave = (player_id, ano)
        if chave in self._atletas:
            return self._atletas[chave]
        temporada = self.cache.temporada(ano)  # elencos só existem na CBF
        cbf_id = self._casar(ano, temporada).get(int(team_id))
        elenco = self.cache.time(ano, cbf_id)["atletas"] if cbf_id else []
        candidatos = cbf.candidatos_atleta(nome, elenco)
        escolhido = candidatos[0] if len(candidatos) == 1 else None
        if 1 < len(candidatos) <= CANDIDATOS_PARA_DESEMPATE:
            partidas = {c["atleta_id"]: self.cache.atleta(ano, c["atleta_id"])["partidas"] for c in candidatos}
            vencedor = cbf.desempatar_por_jogos(self._jogos_na_base(player_id, ano), partidas)
            escolhido = next((c for c in candidatos if c["atleta_id"] == vencedor), None)
        self._atletas[chave] = {**escolhido, "temporada": ano} if escolhido else None
        return self._atletas[chave]

    def foto_jogador(self, player_id: int, ano: str | None = None) -> tuple[bytes, str] | str | None:
        """Endereço da foto no FotMob (pelo id, sem consultar nada) ou, sem id, no Commons.

        Com `fotos_lentas`, a CBF (conteúdo e tipo da foto) entra antes do Commons e o TheSportsDB
        depois dele: cobrem mais jogadores, mas custam uma requisição por foto.

        Nas reservas a busca usa o nome da base e, quando o atleta da CBF é conhecido, também o
        apelido e o nome completo dele, conferindo o clube. O Commons vem antes: não custa uma
        busca por jogador, e o TheSportsDB aceita poucas por minuto.
        """
        do_fotmob = self.fotmob.foto(player_id)
        if do_fotmob:
            return do_fotmob
        passagem = self._passagem(player_id, ano)
        if passagem is None:
            return None
        nomes = [passagem[2]]
        try:
            achado = self.atleta(player_id, ano) if self.fotos_lentas else None
            if achado:
                foto = self.cache.foto(achado["temporada"], achado["atleta_id"])
                if foto:
                    return foto
                nomes += [achado["apelido"], achado["nome"]]
        except ERROS_CBF:
            pass
        passagens = self._passagens_de(player_id)
        do_commons = self.commons.foto_jogador(nomes, [int(t) for _, t, _ in passagens], [a for a, _, _ in passagens])
        if do_commons:
            return do_commons
        if not self.fotos_lentas:
            return None
        clubes = list(dict.fromkeys(self.dados.nomes.get(int(t), "") for _, t, _ in passagens))
        return self.fotos_reserva.foto(nomes, [c for c in clubes if c])

    def foto_treinador(self, nome: str) -> str | None:
        """Endereço da foto do técnico no Commons (o arquivo vem do Wikidata, na coleta de técnicos)."""
        fotos = self.dados.fotos_treinadores
        arquivo = fotos.get(normalizar(nome))
        return self.commons.foto(arquivo) if arquivo else None

    def creditos(self) -> list[dict]:
        """Autor e licença das imagens do Commons que o site mostra (escudos e fotos)."""
        return self.commons.creditos(list(self.dados.fotos_treinadores.values()))

    def _artilheiros_da_base(self, ano: str) -> list[tuple[int, str, int, int]]:
        """(player_id, nome, team_id, gols) de quem marcou na temporada, na base."""
        if ano not in self._marcadores:
            base = self.dados.temporada(ano)
            gols = base.groupby(["player_id", "player", "team_id"], as_index=False)["gols"].sum()
            self._marcadores[ano] = list(gols[gols["gols"] > 0].itertuples(index=False, name=None))
        return self._marcadores[ano]

    def _time_na_temporada(self, ano: str, atleta: dict, temporada: dict,
                           comparar_gols: bool) -> tuple[str, int] | None:
        """("base", team_id) ou, fora da base, ("fonte", id do time) em que o atleta jogou em `ano`."""
        if ano in self.dados.temporadas:
            por_jogador: dict[int, dict[int, int]] = {}
            for player_id, nome, team_id, gols in self._artilheiros_da_base(ano):
                if cbf.casar_atleta(nome, [atleta]):
                    por_jogador.setdefault(player_id, {})[team_id] = gols
            if comparar_gols and len(por_jogador) > 1:
                # Homônimos (dois "Bruno Henrique"): vence quem tem gols mais perto do número da fonte.
                alvo = atleta.get("gols") or 0
                distancias = sorted((abs(sum(t.values()) - alvo), pid) for pid, t in por_jogador.items())
                if distancias[1][0] - distancias[0][0] >= 3:
                    por_jogador = {distancias[0][1]: por_jogador[distancias[0][1]]}
            if len(por_jogador) == 1:
                times = next(iter(por_jogador.values()))
                return ("base", max(times, key=times.get))  # trocou de clube no ano: vale onde mais marcou
        # Sem resposta na base ("Everton" na base, "Everton Cebolinha" na CBF): elencos já lidos.
        elencos = [int(i) for i, t in temporada.get("times", {}).items()
                   if any(a["atleta_id"] == atleta["atleta_id"] for a in t.get("atletas", []))]
        return ("fonte", elencos[0]) if len(elencos) == 1 else None

    def corrigir_clubes(self, ano: str, temporada: dict, lista: list[dict], comparar_gols: bool = True) -> list[dict]:
        """Põe em cada artilheiro o clube daquela temporada.

        A CBF mostra o clube atual do atleta, não o da temporada: em 2020, Gabriel Barbosa aparece
        no "Santos FC-SP", mas fez os 14 gols pelo Flamengo. O clube certo sai da base (o time em que
        ele marcou) ou, fora dela, dos elencos já lidos. Sem certeza, fica o que a fonte informou.
        `comparar_gols` desempata homônimos pelos gols (não vale para a lista de assistências).
        """
        mapa = self._casar(ano, temporada)
        linhas = {l["cbf_id"]: l for l in temporada["classificacao"]}
        saida = []
        for atleta in lista:
            achado = self._time_na_temporada(ano, atleta, temporada, comparar_gols)
            fonte_id = (mapa.get(achado[1]) if achado[0] == "base" else achado[1]) if achado else None
            linha = linhas.get(fonte_id)
            if linha:
                nome = classificacao_nome(linha["time"])
                atleta = {**atleta, "cbf_id": fonte_id, "escudo": linha["escudo"],
                          "clube": f"{nome}-{linha['uf']}" if linha.get("uf") and "-" not in nome else nome}
            saida.append(atleta)
        return saida

    def foto_atleta(self, ano: str, atleta_id: int) -> tuple[bytes, str] | None:
        """Foto do atleta da CBF (artilharia e assistências, até 20 por temporada): sempre, pois é um
        conjunto pequeno, cacheado e já coletado pela CBF. A reserva por nome (TheSportsDB) segue
        com `fotos_lentas`."""
        return self.cache.foto(ano, atleta_id)

    def foto_por_nome(self, nome: str, clube: str) -> str | None:
        """Endereço da foto no TheSportsDB (artilharia vinda da ESPN, que não traz foto)."""
        return self.fotos_reserva.foto([nome], [clube]) if self.fotos_lentas else None
