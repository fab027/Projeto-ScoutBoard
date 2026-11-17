"""Comparação de nomes de jogadores e times, ignorando caixa, acento e espaços extras."""
import re
import unicodedata


def normalizar(texto) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()
