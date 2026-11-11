"""Tipos básicos: o veredito de cada rodada (Status), de que lado foi o problema (Lado) e a Amostra registrada."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime

from .idioma import t


class Status(enum.Enum):
    # Os valores são os mesmos do OutageLog original (Windows), então os logs dos dois são compatíveis.
    ONLINE = "Up"                       # servidores respondem rápido e o DNS funciona
    LENTO = "Degraded"                  # online, mas lento ou a maioria dos servidores não respondeu
    FALHA_DNS = "DnsFailure"            # servidores respondem pelo IP, mas os nomes não resolvem
    QUEDA_OPERADORA = "ProviderOutage"  # roteador responde, internet não: problema depois do roteador
    QUEDA_LOCAL = "LocalOutage"         # roteador já respondeu antes, mas agora não, e a internet também não
    SEM_CONEXAO = "NoConnection"        # o PC não tem rede (cabo/Wi-Fi desconectado)
    INTERNET_FORA = "InternetDown"      # internet não responde e o roteador nunca responde a ping


# Ordem usada para desempatar (igual à do enum original).
ORDEM = list(Status)


class Lado(enum.Enum):
    OPERADORA = "Provider"
    SEU_LADO = "Yours"
    INDEFINIDO = "Undetermined"
    DNS = "Dns"


_ROTULO = {
    Status.ONLINE: ("Online", "Online"),
    Status.LENTO: ("Lenta ou instável", "Slow or unstable"),
    Status.FALHA_DNS: ("DNS não responde", "DNS not answering"),
    Status.QUEDA_OPERADORA: ("Internet caiu, roteador OK", "Internet down, router OK"),
    Status.QUEDA_LOCAL: ("Roteador não responde", "Router not reachable"),
    Status.SEM_CONEXAO: ("PC sem conexão", "PC not connected"),
    Status.INTERNET_FORA: ("Internet caiu", "Internet down"),
}

_EXPLICACAO = {
    Status.ONLINE: ("Os servidores da internet responderam e os nomes foram resolvidos.",
                    "Internet servers answered and names resolved."),
    Status.LENTO: ("Online, mas as respostas estavam lentas ou a maioria dos servidores não respondeu.",
                   "Online, but responses were slow or most internet servers didn't answer."),
    Status.FALHA_DNS: ("Os servidores da internet responderam pelo endereço IP, mas a consulta de nomes (DNS) falhou, "
                       "então os sites não abririam.",
                       "Internet servers answered by IP address, but name lookups (DNS) failed, so websites wouldn't load."),
    Status.QUEDA_OPERADORA: ("O roteador respondeu, mas nenhum dos servidores independentes da internet respondeu. "
                             "A falha foi depois do roteador: na linha, no modem ou na operadora.",
                             "The router answered, but none of the independent internet servers did. "
                             "The break was past the router: the line, modem or provider."),
    Status.QUEDA_LOCAL: ("O roteador parou de responder, e a internet também. "
                         "A falha foi entre este PC e o roteador (Wi-Fi, cabo ou o próprio roteador).",
                         "The router stopped answering, and so did the internet. "
                         "The break was between this PC and the router (Wi-Fi, cable or the router itself)."),
    Status.SEM_CONEXAO: ("Este PC estava sem conexão de rede ativa (Wi-Fi ou cabo desconectado).",
                         "This PC had no active network connection (Wi-Fi or cable disconnected)."),
    Status.INTERNET_FORA: ("Nenhum servidor da internet respondeu. O roteador não responde a ping nem a conexões, "
                           "então não dá para saber se a falha foi antes ou depois dele.",
                           "No internet server answered. This router doesn't answer pings or connections, "
                           "so this log can't tell whether the break was before or after it."),
}

_ROTULO_LADO = {
    Lado.OPERADORA: ("Lado da operadora (depois do roteador)", "Provider side (past your router)"),
    Lado.SEU_LADO: ("Seu lado (PC, Wi-Fi ou roteador)", "Your side (PC, Wi-Fi or router)"),
    Lado.DNS: ("Só DNS", "DNS only"),
    Lado.INDEFINIDO: ("Indeterminado", "Undetermined"),
}


def rotulo(status: Status) -> str:
    """Nome curto do veredito, para tabelas e para o ícone."""
    return t(*_ROTULO[status])


def explicacao(status: Status) -> str:
    """Uma frase explicando o que foi observado, para o relatório."""
    return t(*_EXPLICACAO[status])


def rotulo_lado(lado: Lado) -> str:
    return t(*_ROTULO_LADO[lado])


def esta_fora(status: Status) -> bool:
    return status not in (Status.ONLINE, Status.LENTO)


def lado_de(status: Status) -> Lado:
    if status == Status.QUEDA_OPERADORA:
        return Lado.OPERADORA
    if status in (Status.QUEDA_LOCAL, Status.SEM_CONEXAO):
        return Lado.SEU_LADO
    if status == Status.FALHA_DNS:
        return Lado.DNS
    return Lado.INDEFINIDO


@dataclass
class Amostra:
    """Uma rodada de checagens. Tempos em ms; None = não respondeu."""
    tempo: datetime                      # UTC, com fuso
    status: Status | None = None         # preenchido pelo classificador
    link: bool = False                   # o PC tem rota padrão (ou algum servidor respondeu)
    gateway_ip: str | None = None        # não vai para o log
    gateway_ms: int | None = None
    alvos_ms: list = field(default_factory=list)
    dns_ok: bool | None = None           # None = DNS não foi checado
    dns_ms: int | None = None
    simulada: bool = False               # gravada durante o autoteste
    internos: dict = field(default_factory=dict)  # nome -> ms ou None (alvos da rede interna)

    @property
    def melhor_ms(self) -> int | None:
        respostas = [ms for ms in self.alvos_ms if ms is not None]
        return min(respostas) if respostas else None
