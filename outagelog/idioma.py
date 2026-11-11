"""Idioma da interface: português ou inglês.

Cada texto é escrito nos dois idiomas no próprio lugar onde é usado: t("Quedas", "Outages").
O padrão segue o idioma do sistema (LANG); a configuração pode forçar um deles.
"""
from __future__ import annotations

import os

PORTUGUES = "pt"
INGLES = "en"


def detectar(preferido: str | None = None) -> str:
    valor = (preferido or "auto").strip().lower()
    if valor in ("pt", "pt-br", "pt_br", "portugues", "português", "portuguese"):
        return PORTUGUES
    if valor in ("en", "en-us", "en_us", "english", "ingles", "inglês"):
        return INGLES
    for variavel in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = os.environ.get(variavel)
        if v:
            return PORTUGUES if v.lower().startswith("pt") else INGLES
    return INGLES


_atual = detectar()


def definir(idioma: str) -> None:
    global _atual
    _atual = detectar(idioma)


def atual() -> str:
    return _atual


def t(pt: str, en: str) -> str:
    """Devolve o texto no idioma atual."""
    return pt if _atual == PORTUGUES else en


def plural(n: int, pt_um: str, pt_varios: str, en_um: str, en_varios: str) -> str:
    return t(pt_um if n == 1 else pt_varios, en_um if n == 1 else en_varios)
