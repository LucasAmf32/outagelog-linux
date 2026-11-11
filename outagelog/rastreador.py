"""Junta a sequência de amostras em quedas, quedas rápidas e tempo monitorado.

Lógica pura: o mesmo código roda ao vivo no serviço e sobre os logs salvos no relatório.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from .modelo import ORDEM, Amostra, Status, esta_fora, lado_de


@dataclass
class Queda:
    inicio: datetime          # UTC, primeira checagem que falhou
    fim: datetime             # UTC, primeira checagem boa depois
    contagens: dict = field(default_factory=dict)
    fim_incerto: bool = False  # o monitoramento parou (PC desligado/dormindo) antes da volta
    em_andamento: bool = False  # ainda fora quando os dados acabam
    simulada: bool = False      # gerada pelo autoteste

    @property
    def duracao(self) -> timedelta:
        return self.fim - self.inicio if self.fim > self.inicio else timedelta(0)

    @property
    def causa(self) -> Status:
        """O veredito que a maioria das rodadas da queda deu."""
        if not self.contagens:
            return Status.INTERNET_FORA
        return min(self.contagens.items(), key=lambda kv: (-kv[1], ORDEM.index(kv[0])))[0]

    @property
    def lado(self):
        return lado_de(self.causa)


@dataclass
class Periodo:
    """Trecho em que as checagens rodaram sem interrupção."""
    inicio: datetime
    fim: datetime

    @property
    def duracao(self) -> timedelta:
        return self.fim - self.inicio


@dataclass
class Opcoes:
    intervalo: timedelta = timedelta(seconds=2)
    min_falhas: int = 2            # rodadas seguidas com falha para virar queda (menos que isso = queda rápida)
    min_recuperacao: int = 2       # rodadas boas seguidas para a queda acabar
    limite_lacuna: timedelta = timedelta(seconds=20)  # pausa maior = monitoramento parou
    aquecimento: timedelta = timedelta(seconds=30)    # depois de ligar/acordar não julga (reconexão não é queda)


class Rastreador:
    def __init__(self, opcoes: Opcoes | None = None):
        self.o = opcoes or Opcoes()
        self.quedas: list[Queda] = []
        self.periodos: list[Periodo] = []
        self.quedas_rapidas: list[datetime] = []
        self.tempo_lento = timedelta(0)
        self.ao_iniciar: Callable[[Queda], None] | None = None
        self.ao_terminar: Callable[[Queda], None] | None = None
        self._pendentes: list[Amostra] = []
        self._anterior: Amostra | None = None
        self._ultima_julgada: Amostra | None = None
        self._inicio_execucao: datetime | None = None
        self._periodo: Periodo | None = None
        self._aberta: Queda | None = None
        self._recuperando = 0
        self._inicio_recuperacao: datetime | None = None

    @property
    def atual(self) -> Queda | None:
        return self._aberta

    @property
    def tempo_monitorado(self) -> timedelta:
        return sum((p.duracao for p in self.periodos), timedelta(0))

    def adicionar(self, s: Amostra) -> None:
        if self._anterior is not None:
            if s.tempo <= self._anterior.tempo:
                return  # repetida ou fora de ordem
            if s.tempo - self._anterior.tempo > self.o.limite_lacuna:
                self._fechar_por_lacuna()
                self._inicio_execucao = s.tempo
        else:
            self._inicio_execucao = s.tempo
        self._anterior = s

        if s.tempo - self._inicio_execucao < self.o.aquecimento:
            return

        if self._ultima_julgada is not None and self._periodo is not None \
                and self._ultima_julgada.tempo >= self._inicio_execucao:
            if self._ultima_julgada.status == Status.LENTO:
                self.tempo_lento += s.tempo - self._ultima_julgada.tempo
            self._periodo.fim = s.tempo
        else:
            self._periodo = Periodo(s.tempo, s.tempo)
            self.periodos.append(self._periodo)
        self._ultima_julgada = s

        fora = esta_fora(s.status)
        if self._aberta is None:
            if fora:
                self._pendentes.append(s)
                if len(self._pendentes) >= self.o.min_falhas:
                    self._abrir()
            elif self._pendentes:
                if not any(p.simulada for p in self._pendentes):
                    self.quedas_rapidas.append(self._pendentes[0].tempo)
                self._pendentes.clear()
        elif fora:
            self._recuperando = 0
            self._contar(self._aberta, s)
        else:
            if self._recuperando == 0:
                self._inicio_recuperacao = s.tempo
            self._recuperando += 1
            if self._recuperando >= self.o.min_recuperacao:
                self._fechar(self._inicio_recuperacao, incerto=False, em_andamento=False)

    def finalizar(self) -> None:
        """Fecha uma queda ainda aberta no fim dos dados, marcando como em andamento."""
        self._pendentes.clear()
        if self._aberta is None:
            return
        if self._recuperando > 0:
            self._fechar(self._inicio_recuperacao, incerto=False, em_andamento=False)
        else:
            self._fechar(self._ultima_julgada.tempo, incerto=False, em_andamento=True)

    def _abrir(self) -> None:
        self._aberta = Queda(inicio=self._pendentes[0].tempo, fim=self._pendentes[-1].tempo)
        for p in self._pendentes:
            self._contar(self._aberta, p)
        self._pendentes.clear()
        self._recuperando = 0
        if self.ao_iniciar:
            self.ao_iniciar(self._aberta)

    @staticmethod
    def _contar(q: Queda, s: Amostra) -> None:
        q.contagens[s.status] = q.contagens.get(s.status, 0) + 1
        q.fim = s.tempo
        if s.simulada:
            q.simulada = True

    def _fechar_por_lacuna(self) -> None:
        self._pendentes.clear()
        if self._aberta is not None:
            if self._recuperando > 0:
                self._fechar(self._inicio_recuperacao, incerto=False, em_andamento=False)
            else:
                self._fechar(self._ultima_julgada.tempo, incerto=True, em_andamento=False)
        self._periodo = None

    def _fechar(self, fim: datetime, incerto: bool, em_andamento: bool) -> None:
        q = self._aberta
        self._aberta = None
        self._recuperando = 0
        q.fim = fim
        q.fim_incerto = incerto
        q.em_andamento = em_andamento
        self.quedas.append(q)
        if self.ao_terminar:
            self.ao_terminar(q)
