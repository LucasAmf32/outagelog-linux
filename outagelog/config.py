"""Configuração em arquivo .ini (texto simples, dá para editar à mão) e pastas padrão.

As chaves aceitam o nome em português ou em inglês (intervalo_segundos ou interval_seconds).
"""
from __future__ import annotations

import configparser
import ipaddress
import os
import re
from dataclasses import dataclass, field

from .idioma import t

PASTA_SERVICO = "/var/lib/outagelog"
CONFIG_SISTEMA = "/etc/outagelog.ini"

ALVOS_PADRAO = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]  # Cloudflare, Google e Quad9: empresas diferentes
NOMES_DNS_PADRAO = ["www.google.com", "www.cloudflare.com", "www.microsoft.com", "www.wikipedia.org", "www.amazon.com"]

# chave em português -> chave em inglês
CHAVES = {
    "idioma": "language",
    "intervalo_segundos": "interval_seconds",
    "lento_ms": "slow_ms",
    "manter_dias": "keep_days",
    "alvos": "targets",
    "dns_nomes": "dns_names",
    "dns_servidores": "dns_servers",
}

EXEMPLO_PT = """\
# Configuração do OutageLog. Depois de editar: sudo systemctl restart outagelog

[outagelog]
# Idioma dos relatórios e mensagens: auto (segue o sistema), pt ou en.
idioma = auto
# Segundos entre as rodadas de checagens.
intervalo_segundos = 2
# Se o servidor mais rápido demorar mais que isso (ms), a conexão conta como lenta.
lento_ms = 300
# Apaga logs diários mais velhos que isso (0 = guarda tudo).
manter_dias = 60
# Servidores da internet a checar (IPv4). Use servidores de empresas diferentes.
alvos = 1.1.1.1 8.8.8.8 9.9.9.9
# Sites usados no teste de DNS (dois por rodada, em rodízio).
dns_nomes = www.google.com www.cloudflare.com www.microsoft.com www.wikipedia.org www.amazon.com
# Servidores DNS a consultar. Vazio = os mesmos que o sistema usa (sem passar pelo cache local).
dns_servidores =

[internos]
# Equipamentos da rede interna para vigiar junto (aparecem numa seção própria do relatório).
# nome = IP            -> testa com ping
# nome = IP:porta      -> testa abrindo uma conexão nessa porta (ex.: 445 = compartilhamento de arquivos)
# servidor = 192.168.0.10:445
# impressora = 192.168.0.50
"""

EXEMPLO_EN = """\
# OutageLog settings. After editing: sudo systemctl restart outagelog

[outagelog]
# Language of reports and messages: auto (follows the system), en or pt.
language = auto
# Seconds between rounds of checks.
interval_seconds = 2
# The fastest internet server answering slower than this (ms) counts as slow.
slow_ms = 300
# Delete daily logs older than this many days (0 keeps everything).
keep_days = 60
# Internet servers to check (IPv4). Use servers run by different companies.
targets = 1.1.1.1 8.8.8.8 9.9.9.9
# Websites used for the DNS check (two per round, in rotation).
dns_names = www.google.com www.cloudflare.com www.microsoft.com www.wikipedia.org www.amazon.com
# DNS servers to ask. Empty = the ones the system uses (bypassing the local cache).
dns_servers =

[internal]
# Devices on your local network to watch as well (they get their own section in the report).
# name = IP            -> checked with ping
# name = IP:port       -> checked by opening a connection to that port (e.g. 445 = file sharing)
# fileserver = 192.168.0.10:445
# printer = 192.168.0.50
"""


def exemplo() -> str:
    return t(EXEMPLO_PT, EXEMPLO_EN)


@dataclass
class Config:
    idioma: str = "auto"
    intervalo_segundos: int = 2
    lento_ms: int = 300
    manter_dias: int = 60
    alvos: list = field(default_factory=lambda: list(ALVOS_PADRAO))
    dns_nomes: list = field(default_factory=lambda: list(NOMES_DNS_PADRAO))
    dns_servidores: list = field(default_factory=list)
    internos: dict = field(default_factory=dict)  # nome -> (ip, porta ou None)
    caminho: str | None = None


def _ipv4(texto: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(texto), ipaddress.IPv4Address)
    except ValueError:
        return False


def _inteiro(texto, padrao, minimo, maximo):
    try:
        v = int(texto)
        return v if minimo <= v <= maximo else padrao
    except (TypeError, ValueError):
        return padrao


def caminho_config(explicito: str | None = None) -> str | None:
    if explicito:
        return explicito
    usuario = os.path.join(os.path.expanduser("~"), ".config", "outagelog.ini")
    for caminho in (CONFIG_SISTEMA, usuario):
        if os.path.isfile(caminho):
            return caminho
    return None


def carregar(explicito: str | None = None) -> Config:
    c = Config()
    caminho = caminho_config(explicito)
    if not caminho:
        return c
    c.caminho = caminho
    p = configparser.ConfigParser()
    try:
        p.read(caminho, encoding="utf-8")
    except (OSError, configparser.Error):
        return c
    if p.has_section("outagelog"):
        s = p["outagelog"]

        def ler(chave, padrao=None):
            return s.get(chave, s.get(CHAVES[chave], padrao))

        c.idioma = (ler("idioma", "auto") or "auto").strip()
        c.intervalo_segundos = _inteiro(ler("intervalo_segundos"), c.intervalo_segundos, 1, 60)
        c.lento_ms = _inteiro(ler("lento_ms"), c.lento_ms, 20, 10000)
        c.manter_dias = _inteiro(ler("manter_dias"), c.manter_dias, 0, 3650)
        alvos = [a for a in re.split(r"[\s,]+", ler("alvos", "")) if _ipv4(a)]
        if alvos:
            c.alvos = alvos
        nomes = [n for n in re.split(r"[\s,]+", ler("dns_nomes", "")) if re.fullmatch(r"[A-Za-z0-9.-]+", n)]
        if nomes:
            c.dns_nomes = nomes
        c.dns_servidores = [a for a in re.split(r"[\s,]+", ler("dns_servidores", "")) if _ipv4(a)]
    for secao in ("internos", "internal"):
        if not p.has_section(secao):
            continue
        for nome, valor in p[secao].items():
            nome = re.sub(r"[^A-Za-z0-9_.-]", "_", nome)[:40]  # o nome vai para o CSV
            ip, _, porta = valor.split("#")[0].strip().partition(":")
            if not _ipv4(ip):
                continue
            c.internos[nome] = (ip, _inteiro(porta, None, 1, 65535) if porta else None)
    return c


def pasta_dados(explicita: str | None = None) -> str:
    """Pasta dos logs: a do serviço, se existir; senão uma na pasta do usuário."""
    if explicita:
        return explicita
    if os.path.isdir(PASTA_SERVICO):
        return PASTA_SERVICO
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "outagelog")
