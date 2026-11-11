"""Uma semana inventada (sempre igual), para o relatório de demonstração e para os testes."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from .idioma import t as traduzir
from .modelo import Amostra, Status

# (dia, hora de início, minutos, status)
EVENTOS = [
    (0, 19.70, 6.3, Status.QUEDA_OPERADORA),
    (1, 20.25, 3.1, Status.QUEDA_OPERADORA),
    (1, 20.52, 11.4, Status.QUEDA_OPERADORA),
    (1, 16.10, 1.5, Status.FALHA_DNS),
    (2, 13.20, 0.9, Status.SEM_CONEXAO),
    (3, 2.17, 24.6, Status.QUEDA_OPERADORA),
    (3, 21.08, 2.2, Status.QUEDA_OPERADORA),
    (4, 18.84, 0.8, Status.QUEDA_OPERADORA),
    (4, 20.60, 8.7, Status.QUEDA_OPERADORA),
]
# (dia, hora, minutos) em que a impressora da demonstração ficou fora
IMPRESSORA_FORA = [(1, 10.5, 14.0), (4, 15.2, 3.5)]


def gerar(ultimo_dia: date, dias: int = 7, intervalo: float = 2.0, semente: int = 42) -> list:
    rng = random.Random(semente)
    amostras = []
    servidor, impressora = traduzir("servidor", "fileserver"), traduzir("impressora", "printer")
    primeiro = ultimo_dia - timedelta(days=dias - 1)
    for d in range(dias):
        dia = primeiro + timedelta(days=d)
        meia_noite = datetime(dia.year, dia.month, dia.day)
        ligado = 0 if d == 3 else 7.5 + rng.random() * 0.5  # um dia o PC ficou ligado a noite toda
        desligado = 24 if d == 2 else 23.3 + rng.random() * 0.4
        t = ligado * 3600
        while t < desligado * 3600:
            hr = t / 3600
            utc = (meia_noite + timedelta(seconds=t)).astimezone().astimezone(timezone.utc)
            t += intervalo
            status = Status.ONLINE
            for dia_ev, inicio, minutos, st in EVENTOS:
                if dia_ev == d and inicio <= hr < inicio + minutos / 60:
                    status = st
            if status == Status.ONLINE and rng.random() < 0.00008:
                status = Status.QUEDA_OPERADORA  # queda rápida
            noite = 1 if 19 <= hr < 23 else 0
            melhor = 11 + int(rng.random() * 6 + noite * rng.random() * rng.random() * 180)
            if status == Status.ONLINE and melhor > 300:
                status = Status.LENTO
            impressora_fora = any(dia_ev == d and inicio <= hr < inicio + m / 60 for dia_ev, inicio, m in IMPRESSORA_FORA)
            s = Amostra(tempo=utc, status=status, link=status != Status.SEM_CONEXAO,
                        internos={servidor: 1 + rng.randrange(2), impressora: None if impressora_fora else 2 + rng.randrange(3)})
            if status in (Status.ONLINE, Status.LENTO):
                s.gateway_ms = 1 + rng.randrange(3)
                s.alvos_ms = [melhor, melhor + rng.randrange(8), melhor + rng.randrange(12)]
                s.dns_ok, s.dns_ms = True, melhor + 5 + rng.randrange(20)
            elif status == Status.FALHA_DNS:
                s.gateway_ms = 1 + rng.randrange(3)
                s.alvos_ms = [melhor, melhor + 3, melhor + 6]
                s.dns_ok = False
            elif status == Status.QUEDA_OPERADORA:
                s.gateway_ms = 1 + rng.randrange(3)
                s.alvos_ms = [None, None, None]
            else:
                s.alvos_ms = [None, None, None]
                s.internos = {servidor: None, impressora: None}
            amostras.append(s)
    return amostras
