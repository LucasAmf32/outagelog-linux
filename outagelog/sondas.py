"""Uma rodada de checagens: o roteador, três servidores independentes da internet, o DNS e os alvos internos.

Tudo com a biblioteca padrão do Python. O ping usa o socket ICMP sem privilégio do Linux
(liberado no Linux Mint/Ubuntu); se não der, usa socket bruto (root/CAP_NET_RAW) ou o comando `ping`.
"""
from __future__ import annotations

import ipaddress
import itertools
import math
import os
import random
import re
import select
import shutil
import socket
import struct
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .modelo import Amostra

# Endereços só de documentação (RFC 5737), que nunca são roteados: o autoteste usa para simular uma queda.
ALVOS_BURACO_NEGRO = ["192.0.2.1", "198.51.100.1", "203.0.113.1"]

# Interfaces de VPN/virtuais: se houver outra rota padrão, o "roteador" checado é o da placa física.
PREFIXOS_VIRTUAIS = ("tun", "tap", "wg", "ppp", "tailscale", "zt", "docker", "br-", "veth", "virbr", "vmnet", "vboxnet")

_sequencia = itertools.count(random.randint(1, 30000))
_trava = threading.Lock()


def _ms(inicio: float) -> int:
    return max(1, round((time.monotonic() - inicio) * 1000))


# ---------------------------------------------------------------- ping (ICMP)

def _checksum(dados: bytes) -> int:
    if len(dados) % 2:
        dados += b"\0"
    soma = sum(struct.unpack(f"!{len(dados) // 2}H", dados))
    soma = (soma >> 16) + (soma & 0xFFFF)
    soma += soma >> 16
    return ~soma & 0xFFFF


class Pinger:
    def __init__(self):
        self.modo = self._detectar()

    @staticmethod
    def _detectar():
        for tipo in (socket.SOCK_DGRAM, socket.SOCK_RAW):
            try:
                socket.socket(socket.AF_INET, tipo, socket.IPPROTO_ICMP).close()
                return tipo
            except OSError:
                pass
        return "comando" if shutil.which("ping") else None

    @property
    def tipo(self) -> str | None:
        """Como o ping é feito: "dgram" (sem privilégio), "raw" (root/CAP_NET_RAW), "comando" ou None."""
        return {socket.SOCK_DGRAM: "dgram", socket.SOCK_RAW: "raw"}.get(self.modo, self.modo)

    def ping(self, ip: str, timeout: float) -> int | None:
        if self.modo is None:
            return None
        if self.modo == "comando":
            return self._ping_comando(ip, timeout)
        return self._ping_socket(ip, timeout)

    def _ping_socket(self, ip: str, timeout: float) -> int | None:
        with _trava:
            seq = next(_sequencia) & 0xFFFF
        ident = os.getpid() & 0xFFFF
        carga = b"outagelog" + struct.pack("!d", time.time())
        pacote = struct.pack("!BBHHH", 8, 0, 0, ident, seq) + carga
        pacote = struct.pack("!BBHHH", 8, 0, _checksum(pacote), ident, seq) + carga
        bruto = self.modo == socket.SOCK_RAW
        try:
            s = socket.socket(socket.AF_INET, self.modo, socket.IPPROTO_ICMP)
        except OSError:
            return None
        try:
            inicio = time.monotonic()
            s.sendto(pacote, (ip, 0))
            limite = inicio + timeout
            while True:
                resta = limite - time.monotonic()
                if resta <= 0:
                    return None
                prontos, _, _ = select.select([s], [], [], resta)
                if not prontos:
                    return None
                dados, origem = s.recvfrom(2048)
                if bruto:
                    dados = dados[(dados[0] & 0x0F) * 4:]  # tira o cabeçalho IP
                if len(dados) < 8 or origem[0] != ip:
                    continue
                tipo, _, _, rid, rseq = struct.unpack("!BBHHH", dados[:8])
                # No socket sem privilégio o kernel troca o identificador, então só a sequência é comparada.
                if tipo == 0 and rseq == seq and (not bruto or rid == ident):
                    return _ms(inicio)
        except OSError:
            return None
        finally:
            s.close()

    @staticmethod
    def _ping_comando(ip: str, timeout: float) -> int | None:
        try:
            r = subprocess.run(["ping", "-n", "-c", "1", "-W", str(max(1, math.ceil(timeout))), ip],
                               capture_output=True, text=True, timeout=timeout + 2)
        except (OSError, subprocess.SubprocessError):
            return None
        m = re.search(r"time[=<]([\d.]+)", r.stdout)
        return max(1, round(float(m.group(1)))) if r.returncode == 0 and m else None


# ---------------------------------------------------------------- TCP

def conectar_tcp(ip: str, porta: int, timeout: float, recusa_conta: bool = False) -> int | None:
    """Tempo para abrir uma conexão TCP. Com recusa_conta, um "conexão recusada" também prova que o aparelho está lá."""
    inicio = time.monotonic()
    try:
        with socket.create_connection((ip, porta), timeout=timeout):
            pass
    except ConnectionRefusedError:
        if not recusa_conta:
            return None
    except OSError:
        return None
    return _ms(inicio)


# ---------------------------------------------------------------- DNS

def montar_consulta(nome: str, ident: int) -> bytes:
    cabecalho = struct.pack("!HHHHHH", ident, 0x0100, 1, 0, 0, 0)  # pede recursão, 1 pergunta
    pergunta = b"".join(bytes([len(p)]) + p.encode("ascii") for p in nome.strip(".").split(".")) + b"\0"
    return cabecalho + pergunta + struct.pack("!HH", 1, 1)  # tipo A, classe IN


def codigo_resposta(dados: bytes, ident: int) -> int | None:
    """O rcode da resposta (0 = sucesso), ou None se não for a resposta desta consulta."""
    if len(dados) < 12:
        return None
    rid, flags = struct.unpack("!HH", dados[:4])
    if rid != ident or not flags & 0x8000:
        return None
    return flags & 0x000F


def servidores_dns_do_sistema(arquivos=("/run/systemd/resolve/resolv.conf", "/etc/resolv.conf")) -> list:
    """Os servidores DNS de verdade. O 127.0.0.53 do systemd-resolved é um cache local, então é evitado."""
    locais = []
    for caminho in arquivos:
        try:
            with open(caminho, encoding="utf-8", errors="replace") as f:
                linhas = f.read().splitlines()
        except OSError:
            continue
        lista = []
        for linha in linhas:
            partes = linha.split()
            if len(partes) >= 2 and partes[0] == "nameserver":
                try:
                    ip = ipaddress.ip_address(partes[1])
                except ValueError:
                    continue
                if ip.version == 4:
                    (locais if ip.is_loopback else lista).append(str(ip))
        if lista:
            return lista[:3]
    return locais[:1]


def consultar_dns(nome: str, servidores: list, timeout: float, porta: int = 53) -> tuple[bool, int]:
    """Pergunta o nome a todos os servidores ao mesmo tempo; vale a primeira resposta com sucesso."""
    if not servidores:
        return False, 0
    ident = random.randint(0, 0xFFFF)
    consulta = montar_consulta(nome, ident)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return False, 0
    try:
        inicio = time.monotonic()
        enviados = 0
        for srv in servidores:
            try:
                s.sendto(consulta, (srv, porta))
                enviados += 1
            except OSError:
                pass
        falhas = 0
        limite = inicio + timeout
        while enviados and falhas < enviados:
            resta = limite - time.monotonic()
            if resta <= 0:
                break
            prontos, _, _ = select.select([s], [], [], resta)
            if not prontos:
                break
            try:
                dados, origem = s.recvfrom(4096)
            except OSError:
                falhas += 1
                continue
            if origem[0] not in servidores:
                continue
            rcode = codigo_resposta(dados, ident)
            if rcode == 0:
                return True, _ms(inicio)
            if rcode is not None:
                falhas += 1
        return False, 0
    finally:
        s.close()


# ---------------------------------------------------------------- roteador

def rota_padrao(texto: str | None = None) -> tuple[str | None, bool]:
    """(IP do roteador, tem rede) a partir de /proc/net/route. Prefere placas físicas a VPNs."""
    if texto is None:
        try:
            with open("/proc/net/route", encoding="ascii") as f:
                texto = f.read()
        except OSError:
            return None, False
    candidatos = []
    for linha in texto.splitlines()[1:]:
        c = linha.split()
        if len(c) < 8:
            continue
        try:
            iface, destino, gw, flags, metrica = c[0], c[1], c[2], int(c[3], 16), int(c[6])
        except ValueError:
            continue
        if destino == "00000000" and flags & 0x1:  # rota padrão, ativa
            candidatos.append((metrica, iface, gw))
    if not candidatos:
        return None, False
    candidatos.sort()

    def ip(hexa):
        return socket.inet_ntoa(struct.pack("<I", int(hexa, 16)))

    for _, iface, gw in candidatos:
        if gw != "00000000" and not iface.startswith(PREFIXOS_VIRTUAIS):
            return ip(gw), True
    for _, _, gw in candidatos:
        if gw != "00000000":
            return ip(gw), True
    return None, True


# ---------------------------------------------------------------- a rodada

class Sondador:
    def __init__(self, alvos, nomes_dns, servidores_dns=None, internos=None, timeout: float = 1.5):
        self.alvos = list(alvos)
        self.nomes_dns = list(nomes_dns)
        self._servidores_fixos = list(servidores_dns or [])
        self.internos = dict(internos or {})
        self.timeout = timeout
        self.pinger = Pinger()
        self.simular_ate = 0.0  # time.monotonic() até quando simular uma queda
        self.gateway_ip: str | None = rota_padrao()[0]
        self._indice_dns = 0
        self._servidores: list = []
        self._servidores_lidos_em = -1e9
        self._pool = ThreadPoolExecutor(max_workers=16 + len(self.internos), thread_name_prefix="sonda")

    @property
    def servidores_dns(self) -> list:
        if self._servidores_fixos:
            return self._servidores_fixos
        if time.monotonic() - self._servidores_lidos_em > 30:  # a rede pode mudar (Wi-Fi diferente, DHCP)
            self._servidores = servidores_dns_do_sistema()
            self._servidores_lidos_em = time.monotonic()
        return self._servidores

    def simular_queda(self, segundos: float) -> None:
        self.simular_ate = time.monotonic() + segundos

    def _alvo(self, ip: str) -> int | None:
        ms = self.pinger.ping(ip, self.timeout)
        # Algumas redes bloqueiam ping: abrir uma conexão na porta 443 também prova que o servidor responde.
        return ms if ms is not None else conectar_tcp(ip, 443, self.timeout)

    def _roteador(self, ip: str) -> int | None:
        ms = self.pinger.ping(ip, self.timeout)
        if ms is not None:
            return ms
        # Roteador que bloqueia ping: tenta a página de configuração. "Recusado" também prova que ele respondeu.
        for porta in (80, 443, 53):
            ms = conectar_tcp(ip, porta, self.timeout / 3, recusa_conta=True)
            if ms is not None:
                return ms
        return None

    def _dns(self, servidores) -> tuple[bool, int]:
        # Dois nomes por rodada: só é falha de DNS se os dois falharem (um site com problema não conta).
        nomes = [self.nomes_dns[(self._indice_dns + i) % len(self.nomes_dns)] for i in range(2)]
        self._indice_dns += 2
        resultados = list(self._pool.map(lambda n: consultar_dns(n, servidores, max(self.timeout, 2.5)), nomes))
        bons = [ms for ok, ms in resultados if ok]
        return (True, min(bons)) if bons else (False, 0)

    def _interno(self, ip: str, porta: int | None) -> int | None:
        if porta:
            return conectar_tcp(ip, porta, self.timeout)
        ms = self.pinger.ping(ip, self.timeout)
        return ms

    def rodada(self) -> Amostra:
        agora = datetime.now(timezone.utc)
        simular = time.monotonic() < self.simular_ate
        self.gateway_ip, link = rota_padrao()
        alvos = ALVOS_BURACO_NEGRO if simular else self.alvos

        f_gw = self._pool.submit(self._roteador, self.gateway_ip) if self.gateway_ip else None
        f_alvos = [self._pool.submit(self._alvo, ip) for ip in alvos]
        servidores = self.servidores_dns
        f_dns = None if simular or not servidores else self._pool.submit(self._dns, servidores)
        f_int = {nome: self._pool.submit(self._interno, ip, porta) for nome, (ip, porta) in self.internos.items()}

        alvos_ms = [f.result() for f in f_alvos]
        dns = f_dns.result() if f_dns else None
        return Amostra(
            tempo=agora,
            link=link or any(ms is not None for ms in alvos_ms),
            gateway_ip=self.gateway_ip,
            gateway_ms=f_gw.result() if f_gw else None,
            alvos_ms=alvos_ms,
            dns_ok=None if dns is None else dns[0],
            dns_ms=dns[1] if dns and dns[0] else None,
            simulada=simular,
            internos={nome: f.result() for nome, f in f_int.items()},
        )

    def fechar(self) -> None:
        self._pool.shutdown(wait=False)
