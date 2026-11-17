"""Comparação de nomes de jogadores e times, ignorando caixa, acento e espaços extras."""
import difflib
import re
import unicodedata


def normalizar(texto) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def melhor_correspondencia(nome: str, candidatos: dict, limiar: float = 0.85):
    """Chave do candidato mais parecido com o nome, se a semelhança for pelo menos `limiar`.

    `candidatos` mapeia chave -> nome. Nomes iguais depois de normalizados valem sempre.
    """
    alvo = normalizar(nome)
    nomes = {chave: normalizar(valor) for chave, valor in candidatos.items()}
    for chave, valor in nomes.items():
        if valor == alvo:
            return chave
    proximo = difflib.get_close_matches(alvo, list(nomes.values()), n=1, cutoff=limiar)
    if not proximo:
        return None
    return next(chave for chave, valor in nomes.items() if valor == proximo[0])
