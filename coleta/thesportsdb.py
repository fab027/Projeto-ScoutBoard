"""Endereço da foto de um jogador no TheSportsDB (chave pública de teste "123"): reserva da CBF.

A foto não é baixada: o site redireciona o navegador para o endereço do TheSportsDB.
Só vale a foto de quem tem o mesmo nome e joga por um dos clubes que o jogador defendeu
na base; homônimo de outro clube é descartado. Os endereços achados (ou a falta deles)
ficam em `arquivo`, para não repetir buscas: a chave de teste aceita poucas por minuto.
"""
import json
import threading
import time
from pathlib import Path
from urllib.parse import quote

import requests

from config import CACHE_FONTES, USER_AGENT
from coleta.nomes import normalizar

BASE = "https://www.thesportsdb.com/api/v1/json/123"
PAUSA = 2.0

_sessao = requests.Session()
_sessao.headers["User-Agent"] = USER_AGENT
_trava = threading.Lock()
_ultima = [0.0]


PAUSA_APOS_LIMITE = 60
_pausa_ate = [0.0]


def buscar_jogadores(nome: str) -> list[dict]:
    """Jogadores do TheSportsDB com o nome, uma busca a cada PAUSA segundos no processo inteiro.

    Se o TheSportsDB responder 429 (limite da chave de teste), as buscas param por
    PAUSA_APOS_LIMITE segundos e falham na hora, em vez de deixar as fotos esperando.
    """
    restante = _pausa_ate[0] - time.monotonic()
    if restante > 0:
        raise requests.ConnectionError(f"TheSportsDB no limite; nova tentativa em {restante:.0f}s")
    with _trava:
        espera = _ultima[0] + PAUSA - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        _ultima[0] = time.monotonic()
        resposta = _sessao.get(f"{BASE}/searchplayers.php?p={quote(nome)}", timeout=20)
    if resposta.status_code == 429:
        _pausa_ate[0] = time.monotonic() + PAUSA_APOS_LIMITE
    resposta.raise_for_status()
    if not resposta.text.strip():
        return []
    return (resposta.json() or {}).get("player") or []


def _palavras(texto: str) -> set[str]:
    return set(normalizar(texto).replace("-", " ").split()) - {"fc", "ec", "saf", "de", "da", "do"}


def _clube_confere(clube: str | None, clubes: list[str]) -> bool:
    """O clube do TheSportsDB contém o nome de um dos clubes da base, ou o contrário."""
    deles = _palavras(clube or "")
    for nosso in clubes:
        palavras = _palavras(nosso)
        # "Atletico MG": a UF fica de fora, porque o TheSportsDB escreve "Atlético Mineiro".
        if len(palavras) > 1 and len(min(palavras, key=len)) == 2:
            palavras = {p for p in palavras if len(p) > 2}
        if deles and palavras and (palavras <= deles or deles <= palavras):
            return True
    return False


def escolher_foto(jogadores: list[dict], nome: str, clubes: list[str]) -> str | None:
    alvo = normalizar(nome)
    for jogador in jogadores:
        if jogador.get("strSport") != "Soccer" or normalizar(jogador.get("strPlayer") or "") != alvo:
            continue
        if not _clube_confere(jogador.get("strTeam"), clubes):
            continue
        foto = jogador.get("strCutout") or jogador.get("strThumb")
        if foto:
            return foto
    return None


class Fotos:
    """Endereços de fotos já procurados, em memória e em `arquivo` (só texto)."""

    def __init__(self, arquivo: Path = CACHE_FONTES / "thesportsdb-fotos.json", buscar=buscar_jogadores):
        self.arquivo = arquivo
        self.buscar = buscar
        self._trava = threading.Lock()
        self._achados = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}

    def foto(self, nomes: list[str], clubes: list[str]) -> str | None:
        """Primeira foto achada entre os `nomes` do mesmo jogador (nome da base, apelido, nome completo)."""
        clubes_chave = "/".join(sorted(normalizar(c) for c in clubes))
        for nome in dict.fromkeys(n for n in nomes if n):
            chave = f"{normalizar(nome)}|{clubes_chave}"
            if chave not in self._achados:
                endereco = escolher_foto(self.buscar(nome), nome, clubes)  # erro de rede sobe e não é guardado
                with self._trava:
                    self._achados[chave] = endereco
                    self.arquivo.parent.mkdir(parents=True, exist_ok=True)
                    self.arquivo.write_text(json.dumps(self._achados, ensure_ascii=False), encoding="utf-8")
            if self._achados[chave]:
                return self._achados[chave]
        return None
