"""Grava cada rodada como uma linha CSV, um arquivo por dia (horário local): samples-2026-11-11.csv.

O formato é o mesmo do OutageLog para Windows, com uma coluna opcional a mais (internal_ms),
então dá para gerar relatório aqui a partir de logs copiados de uma máquina Windows.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

from .modelo import Amostra, Status

CABECALHO = "time_utc,status,link,gateway_ms,dns_ok,dns_ms,simulated,targets_ms,internal_ms"


class Registro:
    def __init__(self, pasta: str):
        self.pasta = pasta
        self._arquivo = None
        self._dia: date | None = None

    def _caminho(self, dia: date) -> str:
        return os.path.join(self.pasta, f"samples-{dia.isoformat()}.csv")

    def anexar(self, s: Amostra) -> None:
        try:
            dia = s.tempo.astimezone().date()
            if self._arquivo is None or dia != self._dia:
                self.fechar()
                os.makedirs(self.pasta, exist_ok=True)
                caminho = self._caminho(dia)
                novo = not os.path.exists(caminho) or os.path.getsize(caminho) == 0
                self._arquivo = open(caminho, "a", encoding="utf-8", newline="\n")
                self._dia = dia
                if novo:
                    self._arquivo.write(CABECALHO + "\n")
            self._arquivo.write(formatar(s) + "\n")
            self._arquivo.flush()
        except OSError:
            # Disco cheio ou sem permissão: continua monitorando, perde só esta linha.
            self.fechar()

    def ler(self, de: datetime, ate: datetime) -> Iterator[Amostra]:
        """Lê as amostras entre dois instantes UTC, um arquivo por vez, sem carregar tudo na memória."""
        dia = de.astimezone().date() - timedelta(days=1)
        ultimo = ate.astimezone().date() + timedelta(days=1)
        while dia <= ultimo:
            caminho = self._caminho(dia)
            dia += timedelta(days=1)
            try:
                arq = open(caminho, encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            with arq:
                for linha in arq:
                    s = interpretar(linha)
                    if s is not None and de <= s.tempo <= ate:
                        yield s

    def podar(self, manter_dias: int) -> None:
        """Apaga os arquivos diários mais velhos que manter_dias (0 = guarda tudo)."""
        if manter_dias <= 0 or not os.path.isdir(self.pasta):
            return
        limite = date.today() - timedelta(days=manter_dias)
        for nome in os.listdir(self.pasta):
            if not (nome.startswith("samples-") and nome.endswith(".csv")):
                continue
            try:
                dia = date.fromisoformat(nome[len("samples-"):-len(".csv")])
            except ValueError:
                continue
            if dia < limite:
                try:
                    os.remove(os.path.join(self.pasta, nome))
                except OSError:
                    pass

    def fechar(self) -> None:
        if self._arquivo is not None:
            try:
                self._arquivo.close()
            except OSError:
                pass
        self._arquivo = None


def _num(v) -> str:
    return "" if v is None else str(v)


def formatar(s: Amostra) -> str:
    t = s.tempo.astimezone(timezone.utc)
    campos = [
        t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z",
        s.status.value,
        "1" if s.link else "0",
        _num(s.gateway_ms),
        "" if s.dns_ok is None else ("1" if s.dns_ok else "0"),
        _num(s.dns_ms),
        "1" if s.simulada else "0",
        "|".join(_num(ms) for ms in s.alvos_ms),
        "|".join(f"{nome}:{_num(ms)}" for nome, ms in s.internos.items()),
    ]
    return ",".join(campos)


def _ler_num(texto: str):
    return None if texto == "" else int(texto)


def interpretar(linha: str) -> Amostra | None:
    """Lê uma linha do CSV; devolve None para cabeçalho, comentários e linhas danificadas."""
    linha = linha.strip()
    if not linha or linha.startswith("time_utc") or linha.startswith("#"):
        return None
    f = linha.split(",")
    if len(f) < 8:
        return None
    try:
        texto = f[0][:-1] if f[0].endswith("Z") else f[0]
        tempo = datetime.fromisoformat(texto).replace(tzinfo=timezone.utc)
        internos = {}
        if len(f) >= 9 and f[8]:
            for par in f[8].split("|"):
                nome, _, ms = par.rpartition(":")
                if nome:
                    internos[nome] = _ler_num(ms)
        return Amostra(
            tempo=tempo,
            status=Status(f[1]),
            link=f[2] == "1",
            gateway_ms=_ler_num(f[3]),
            dns_ok=True if f[4] == "1" else False if f[4] == "0" else None,
            dns_ms=_ler_num(f[5]),
            simulada=f[6] == "1",
            alvos_ms=[] if f[7] == "" else [_ler_num(x) for x in f[7].split("|")],
            internos=internos,
        )
    except ValueError:
        return None
