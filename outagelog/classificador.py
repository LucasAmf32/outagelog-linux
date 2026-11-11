"""Transforma uma rodada de checagens em um Status."""
from __future__ import annotations

from .modelo import Amostra, Status


class Classificador:
    def __init__(self, lento_ms: int = 300):
        # O servidor mais rápido demorando mais que isso conta como "lento".
        self.lento_ms = lento_ms
        # Muitos roteadores nunca respondem. Só dá para culpar o roteador se ele já respondeu antes.
        self._roteadores_que_respondem: set[str] = set()

    def classificar(self, r: Amostra) -> Status:
        total = len(r.alvos_ms)
        responderam = sum(1 for ms in r.alvos_ms if ms is not None)

        if r.gateway_ms is not None and r.gateway_ip:
            self._roteadores_que_respondem.add(r.gateway_ip)

        if responderam == 0:
            if not r.link:
                return Status.SEM_CONEXAO
            if r.gateway_ms is not None:
                return Status.QUEDA_OPERADORA
            if r.gateway_ip and r.gateway_ip in self._roteadores_que_respondem:
                return Status.QUEDA_LOCAL
            return Status.INTERNET_FORA

        if r.dns_ok is False:
            return Status.FALHA_DNS

        melhor = r.melhor_ms
        maioria_falhou = total >= 3 and responderam * 2 < total
        if melhor > self.lento_ms or maioria_falhou:
            return Status.LENTO
        return Status.ONLINE
