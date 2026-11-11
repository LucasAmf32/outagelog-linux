"""Comandos de terminal. Cada um tem nome em português e em inglês:
rodar/run, status, ao-vivo/live, relatorio/report, autoteste/self-test, demo, bandeja/tray, config-exemplo/example-config.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone

from . import VERSAO, config, demo, idioma, relatorio
from .classificador import Classificador
from .idioma import t
from .modelo import Amostra, Status, esta_fora, rotulo, rotulo_lado
from .rastreador import Opcoes, Rastreador
from .registro import Registro
from .relatorio import Fuso, duracao, porcentagem
from .sondas import Sondador

CORES = {"verde": "32", "amarelo": "33", "vermelho": "31", "cinza": "90", "negrito": "1"}
COR_STATUS = {Status.ONLINE: "verde", Status.LENTO: "amarelo"}


def cor(texto: str, nome: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return texto
    return f"\033[{CORES[nome]}m{texto}\033[0m"


def caber(texto: str, ocupado: int) -> str:
    """Corta o texto para a linha caber na largura do terminal (só quando é um terminal)."""
    if not sys.stdout.isatty():
        return texto
    livre = shutil.get_terminal_size((120, 24)).columns - ocupado - 1
    if livre < 10 or len(texto) <= livre:
        return texto
    return texto[:livre - 1] + "…"


def descrever(s: Amostra, alvos: list) -> str:
    """Uma linha com o que cada checagem respondeu."""
    def ms(v):
        return "—" if v is None else f"{v} ms"
    if s.gateway_ip or s.gateway_ms is not None:
        partes = [t(f"roteador {ms(s.gateway_ms)}", f"router {ms(s.gateway_ms)}")]
    else:
        partes = [t("sem roteador", "no router")]
    partes += [f"{ip} {ms(v)}" for ip, v in zip(alvos, s.alvos_ms)]
    if s.dns_ok is not None:
        partes.append(f"DNS {ms(s.dns_ms) if s.dns_ok else t('falhou', 'failed')}")
    partes += [f"{nome} {ms(v)}" for nome, v in s.internos.items()]
    return " · ".join(partes)


def opcoes_de(cfg: config.Config) -> Opcoes:
    return Opcoes(intervalo=timedelta(seconds=cfg.intervalo_segundos))


def criar_sondador(cfg: config.Config) -> Sondador:
    return Sondador(cfg.alvos, cfg.dns_nomes, cfg.dns_servidores, cfg.internos)


def descricao_ping(sondador: Sondador) -> str:
    return {"dgram": t("socket ICMP sem privilégio", "unprivileged ICMP socket"),
            "raw": t("socket ICMP bruto", "raw ICMP socket"),
            "comando": t("comando ping", "ping command"),
            None: t("indisponível", "unavailable")}[sondador.pinger.tipo]


# ---------------------------------------------------------------- rodar (o serviço)

def cmd_rodar(args, cfg):
    pasta = config.pasta_dados(args.dados)
    registro = Registro(pasta)
    sondador = criar_sondador(cfg)
    classificador = Classificador(cfg.lento_ms)
    rastreador = Rastreador(opcoes_de(cfg))
    parar = threading.Event()
    for sinal in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sinal, lambda *_: parar.set())

    def inicio(q):
        quando = f"{q.inicio.astimezone():%d/%m %H:%M:%S}"
        print(t(f"QUEDA começou {quando}: {rotulo(q.causa)}", f"OUTAGE started {quando}: {rotulo(q.causa)}"), flush=True)

    def fim(q):
        extra = t(" (fim incerto: o monitoramento parou)", " (end uncertain: monitoring stopped)") if q.fim_incerto else ""
        print(t(f"VOLTOU depois de {duracao(q.duracao)} — {rotulo(q.causa)} · {rotulo_lado(q.lado)}{extra}",
                f"BACK after {duracao(q.duracao)} — {rotulo(q.causa)} · {rotulo_lado(q.lado)}{extra}"), flush=True)

    rastreador.ao_iniciar, rastreador.ao_terminar = inicio, fim
    origem = cfg.caminho or t("padrão", "defaults")
    print(t(f"OutageLog {VERSAO} monitorando a cada {cfg.intervalo_segundos} s. Logs em {pasta}. "
            f"Ping: {descricao_ping(sondador)}. Configuração: {origem}.",
            f"OutageLog {VERSAO} checking every {cfg.intervalo_segundos} s. Logs in {pasta}. "
            f"Ping: {descricao_ping(sondador)}. Settings: {origem}."), flush=True)
    if sondador.pinger.tipo is None:
        print(t("AVISO: não foi possível fazer ping (sem socket ICMP e sem o comando ping). Só as conexões TCP serão usadas.",
                "WARNING: can't ping (no ICMP socket and no ping command). Only TCP connections will be used."), flush=True)

    ultima_poda = None
    while not parar.is_set():
        comeco = time.monotonic()
        if ultima_poda != date.today():
            registro.podar(cfg.manter_dias)
            ultima_poda = date.today()
        try:
            s = sondador.rodada()
            s.status = classificador.classificar(s)
            registro.anexar(s)
            rastreador.adicionar(s)
        except Exception as e:  # uma rodada ruim não pode parar o monitoramento
            print(t(f"Erro numa rodada: {e!r}", f"Error in a round: {e!r}"), file=sys.stderr, flush=True)
        parar.wait(max(0.2, cfg.intervalo_segundos - (time.monotonic() - comeco)))
    registro.fechar()
    sondador.fechar()
    print(t("OutageLog parado.", "OutageLog stopped."), flush=True)
    return 0


# ---------------------------------------------------------------- ao-vivo

def cmd_ao_vivo(args, cfg):
    sondador = criar_sondador(cfg)
    classificador = Classificador(cfg.lento_ms)
    print(t(f"Checando a cada {cfg.intervalo_segundos} s (Ctrl+C para parar). Nada é gravado. Ping: {descricao_ping(sondador)}.",
            f"Checking every {cfg.intervalo_segundos} s (Ctrl+C to stop). Nothing is logged. Ping: {descricao_ping(sondador)}."))
    dns = ", ".join(sondador.servidores_dns) or t("nenhum encontrado", "none found")
    print(t(f"Roteador: {sondador.gateway_ip or '—'} · DNS: {dns}", f"Router: {sondador.gateway_ip or '—'} · DNS: {dns}"))
    try:
        while True:
            comeco = time.monotonic()
            s = sondador.rodada()
            s.status = classificador.classificar(s)
            nome = cor(f"{rotulo(s.status):<27}", COR_STATUS.get(s.status, "vermelho"))
            print(f"{s.tempo.astimezone():%H:%M:%S}  {nome} {cor(caber(descrever(s, cfg.alvos), 38), 'cinza')}", flush=True)
            time.sleep(max(0.2, cfg.intervalo_segundos - (time.monotonic() - comeco)))
    except KeyboardInterrupt:
        print()
    finally:
        sondador.fechar()
    return 0


# ---------------------------------------------------------------- status

def servico_ativo() -> str | None:
    if not shutil.which("systemctl"):
        return None
    try:
        r = subprocess.run(["systemctl", "is-active", "outagelog"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def cmd_status(args, cfg):
    pasta = config.pasta_dados(args.dados)
    agora = datetime.now(timezone.utc)
    amostras = list(Registro(pasta).ler(agora - timedelta(days=7), agora))
    estado = servico_ativo()
    if estado:
        print(t("Serviço: ", "Service: ") + cor(estado, "verde" if estado == "active" else "vermelho"))
    if not amostras:
        print(t(f"Nenhuma checagem nos últimos 7 dias em {pasta}.", f"No checks in the last 7 days in {pasta}."))
        print(t("Instale e inicie o serviço (sudo ./instalar.sh) ou rode 'outagelog rodar'.",
                "Install and start the service (sudo ./install.sh) or run 'outagelog run'."))
        return 1
    ultima = amostras[-1]
    idade = agora - ultima.tempo
    bolinha = cor("●", COR_STATUS.get(ultima.status, "vermelho"))
    print(f"{bolinha} {cor(rotulo(ultima.status), 'negrito')}   "
          + t(f"(última checagem há {duracao(idade)})", f"(last check {duracao(idade)} ago)"))
    print(f"  {caber(descrever(ultima, cfg.alvos), 2)}")
    if idade > timedelta(seconds=20):
        print(cor(t("  O monitoramento parece parado: confira 'systemctl status outagelog'.",
                    "  Monitoring seems stopped: check 'systemctl status outagelog'."), "amarelo"))

    fuso = Fuso()
    opc = opcoes_de(cfg)
    d24 = relatorio.calcular((s for s in amostras if s.tempo >= agora - timedelta(days=1)),
                             agora - timedelta(days=1), agora, opc, fuso)
    print("\n" + t(f"Últimas 24 h: {porcentagem(d24.disponibilidade)} online · {relatorio.quedas_texto(len(d24.quedas))} · "
                   f"{duracao(d24.tempo_fora)} sem internet · {duracao(d24.monitorado)} monitorado",
                   f"Last 24 hours: {porcentagem(d24.disponibilidade)} online · {relatorio.quedas_texto(len(d24.quedas))} · "
                   f"{duracao(d24.tempo_fora)} offline · {duracao(d24.monitorado)} monitored"))

    d7 = relatorio.calcular(amostras, agora - timedelta(days=7), agora, opc, fuso)
    print("\n" + t(f"Quedas nos últimos 7 dias: {len(d7.quedas)}", f"Outages in the last 7 days: {len(d7.quedas)}"))
    if d7.quedas:
        print(f"  {t('Início', 'Started'):<20} {t('Duração', 'Length'):<13} {t('O que as checagens viram', 'What the checks saw')}")
        for q in reversed(d7.quedas[-15:]):
            ini = q.inicio.astimezone()
            dur = ("≥ " if q.fim_incerto or q.em_andamento else "") + duracao(q.duracao)
            print(f"  {relatorio.data_curta(ini) + ' ' + relatorio.hora(ini):<20} {dur:<13} {rotulo(q.causa)}")
        if len(d7.quedas) > 15:
            print(t(f"  ... e mais {len(d7.quedas) - 15}. Veja tudo com 'outagelog relatorio'.",
                    f"  ... and {len(d7.quedas) - 15} more. See them all with 'outagelog report'."))
    for it in d7.internos:
        print(t(f"  Rede interna — {it.nome}: {porcentagem(it.disponibilidade)} disponível, {relatorio.quedas_texto(len(it.quedas))}",
                f"  Local network — {it.nome}: {porcentagem(it.disponibilidade)} available, {relatorio.quedas_texto(len(it.quedas))}"))
    return 0


# ---------------------------------------------------------------- relatório

def abrir(caminho: str) -> None:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) or not shutil.which("xdg-open"):
        return
    try:
        subprocess.Popen(["xdg-open", caminho], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def salvar_relatorio(html: str, saida: str | None, prefixo: str, nao_abrir: bool) -> str:
    caminho = os.path.abspath(saida or f"{prefixo}-{datetime.now():%Y-%m-%d-%H%M}.html")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(html)
    if not nao_abrir:
        abrir(caminho)
    return caminho


def cmd_relatorio(args, cfg):
    fuso = Fuso(utc=args.utc)
    ate = datetime.now(timezone.utc)
    de = ate - timedelta(days=args.dias)
    pasta = config.pasta_dados(args.dados)
    dados = relatorio.calcular(Registro(pasta).ler(de, ate), de, ate, opcoes_de(cfg), fuso)
    html = relatorio.gerar_html(dados, fuso, cfg.alvos, VERSAO)
    caminho = salvar_relatorio(html, args.saida, t("relatorio-quedas", "outage-report"), args.nao_abrir)
    n = f"{dados.checagens:,}"
    print(t(f"Li {n.replace(',', '.')} checagens de {pasta}. Relatório salvo em {caminho}",
            f"Read {n} checks from {pasta}. Report written to {caminho}"))
    return 0


def cmd_demo(args, cfg):
    fuso = Fuso(utc=args.utc)
    amostras = demo.gerar(date.today(), 7, cfg.intervalo_segundos)
    dados = relatorio.calcular(amostras, amostras[0].tempo, amostras[-1].tempo, opcoes_de(cfg), fuso)
    html = relatorio.gerar_html(dados, fuso, cfg.alvos, VERSAO)
    caminho = salvar_relatorio(html, args.saida, t("relatorio-demo", "demo-report"), args.nao_abrir)
    print(t(f"Relatório de demonstração (dados inventados) salvo em {caminho}",
            f"Demo report (made-up data) written to {caminho}"))
    return 0


# ---------------------------------------------------------------- autoteste

def cmd_autoteste(args, cfg):
    segundos = args.segundos
    sondador = criar_sondador(cfg)
    classificador = Classificador(cfg.lento_ms)
    with tempfile.TemporaryDirectory(prefix="outagelog-autoteste-") as tmp:
        registro = Registro(tmp)
        rastreador = Rastreador(Opcoes(intervalo=timedelta(seconds=cfg.intervalo_segundos), aquecimento=timedelta(0)))
        amostras = []

        def rodada(fase):
            comeco = time.monotonic()
            s = sondador.rodada()
            s.status = classificador.classificar(s)
            registro.anexar(s)
            rastreador.adicionar(s)
            amostras.append(s)
            marca = cor(t("[simulado]", "[faked]   "), "amarelo") if s.simulada else "          "
            nome = cor(f"{rotulo(s.status):<27}", COR_STATUS.get(s.status, "vermelho"))
            print(f"  {fase:<8} {marca} {nome} {cor(caber(descrever(s, cfg.alvos), 50), 'cinza')}", flush=True)
            time.sleep(max(0.2, cfg.intervalo_segundos - (time.monotonic() - comeco)))
            return s

        print(t(f"Autoteste: checagens reais, depois {segundos} s de queda simulada "
                "(as checagens vão para endereços que nunca respondem; sua conexão real não é tocada).",
                f"Self-test: real checks, then a {segundos} s faked outage "
                "(checks go to addresses that never answer; your real connection isn't touched)."))
        print(t(f"Ping: {descricao_ping(sondador)} · roteador: {sondador.gateway_ip or '—'}\n",
                f"Ping: {descricao_ping(sondador)} · router: {sondador.gateway_ip or '—'}\n"))
        antes, queda, depois_ = t("antes", "before"), t("queda", "outage"), t("depois", "after")
        try:
            reais = [rodada(antes) for _ in range(4)]
            sondador.simular_queda(segundos)
            while time.monotonic() < sondador.simular_ate:
                rodada(queda)
            depois = []
            for _ in range(8):
                depois.append(rodada(depois_))
                if len(depois) >= 2 and not esta_fora(depois[-1].status) and not esta_fora(depois[-2].status):
                    break
        except KeyboardInterrupt:
            print("\n" + t("Interrompido.", "Interrupted."))
            return 1
        finally:
            sondador.fechar()
        rastreador.finalizar()
        registro.fechar()

    simuladas = [q for q in rastreador.quedas if q.simulada]
    print()
    ok = len(simuladas) == 1 and not simuladas[0].em_andamento
    if ok:
        q = simuladas[0]
        print(cor(t("PASSOU", "PASSED"), "verde")
              + t(f": a queda simulada foi detectada ({duracao(q.duracao)}, “{rotulo(q.causa)}”).",
                  f": the faked outage was detected ({duracao(q.duracao)}, “{rotulo(q.causa)}”)."))
    else:
        print(cor(t("FALHOU", "FAILED"), "vermelho")
              + t(f": esperava 1 queda simulada e encontrei {len(simuladas)}.",
                  f": expected 1 faked outage and found {len(simuladas)}."))
        if any(s.simulada and not esta_fora(s.status) for s in amostras):
            print(t("  Os endereços de teste responderam: esta rede devolve resposta para qualquer IP (proxy/firewall?).",
                    "  The test addresses answered: this network replies for any IP (proxy/firewall?)."))

    aviso = cor(t("Aviso", "Warning"), "amarelo")
    if not any(s.gateway_ms is not None for s in reais):
        print(aviso + t(": o roteador não respondeu a ping nem às portas 80/443/53. "
                        "As quedas vão aparecer como “Internet caiu”, sem dizer de quem foi a culpa.",
                        ": the router didn't answer ping or ports 80/443/53. "
                        "Outages will show as “Internet down”, without saying whose side they were on."))
    if all(s.dns_ok is None for s in reais):
        print(aviso + t(": nenhum servidor DNS encontrado; defina dns_servidores na configuração.",
                        ": no DNS server found; set dns_servers in the settings."))
    elif not any(s.dns_ok for s in reais):
        servidores = ", ".join(sondador.servidores_dns)
        print(aviso + t(f": o DNS não respondeu ({servidores}). Se a rede bloqueia DNS externo, defina dns_servidores na configuração.",
                        f": DNS didn't answer ({servidores}). If the network blocks outside DNS, set dns_servers in the settings."))
    if not any(any(ms is not None for ms in s.alvos_ms) for s in reais):
        print(aviso + t(": nenhum servidor da internet respondeu nas checagens reais.",
                        ": no internet server answered during the real checks."))
    return 0 if ok else 1


def cmd_bandeja(args, cfg):
    from .bandeja import cmd_bandeja as rodar_bandeja  # só carrega o GTK quando precisa
    return rodar_bandeja(args, cfg)


# ---------------------------------------------------------------- main

def opcao(pt: str, en: str) -> tuple:
    """Os dois nomes de uma opção, com o do idioma atual primeiro (é o que aparece na ajuda)."""
    return (pt, en) if idioma.atual() == "pt" else (en, pt)


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="outagelog", description=t(
        "Registra as quedas de internet e mostra de quem foi a culpa: sua rede ou a operadora.",
        "Logs internet outages and shows whose side they were on: your network or your provider."))
    p.add_argument(*opcao("--versao", "--version"), action="version", version=f"OutageLog {t('para', 'for')} Linux {VERSAO}")
    p.add_argument("--config", metavar=t("ARQUIVO", "FILE"), help=t("arquivo de configuração (padrão: /etc/outagelog.ini ou ~/.config/outagelog.ini)",
                                      "settings file (default: /etc/outagelog.ini or ~/.config/outagelog.ini)"))
    p.add_argument(*opcao("--dados", "--data-dir"), dest="dados", metavar=t("PASTA", "FOLDER"), help=t(
        f"pasta dos logs (padrão: {config.PASTA_SERVICO} se existir, senão ~/.local/share/outagelog)",
        f"log folder (default: {config.PASTA_SERVICO} if it exists, otherwise ~/.local/share/outagelog)"))
    p.add_argument(*opcao("--idioma", "--language"), dest="idioma", choices=["pt", "en"],
                   help=t("idioma das mensagens e relatórios", "language of messages and reports"))
    sub = p.add_subparsers(dest="comando", metavar=t("comando", "command"))

    def comando(nome_pt, nome_en, ajuda_pt, ajuda_en):
        if nome_pt == nome_en:
            return sub.add_parser(nome_pt, help=t(ajuda_pt, ajuda_en))
        principal, outro = opcao(nome_pt, nome_en)
        return sub.add_parser(principal, aliases=[outro], help=t(ajuda_pt, ajuda_en))

    comando("rodar", "run", "monitora e grava o log (é o que o serviço executa)",
            "check and log continuously (this is what the service runs)")
    comando("status", "status", "estado atual e quedas dos últimos 7 dias", "current state and outages of the last 7 days")
    comando("ao-vivo", "live", "mostra cada rodada na tela, sem gravar nada", "print every round live, log nothing")
    r = comando("relatorio", "report", "gera o relatório HTML dos últimos N dias", "write an HTML report of the last N days")
    r.add_argument("dias", nargs="?", type=int, default=7, metavar=t("dias", "days"), help=t("quantos dias (padrão 7)", "how many days (default 7)"))
    d = comando("demo", "demo", "relatório de demonstração com dados inventados", "a report made from made-up data")
    for x in (r, d):
        x.add_argument(*opcao("--saida", "--out"), "-o", dest="saida", metavar=t("ARQUIVO", "FILE"),
                       help=t("onde salvar o HTML (padrão: pasta atual)", "where to write the HTML (default: current folder)"))
        x.add_argument(*opcao("--nao-abrir", "--no-open"), dest="nao_abrir", action="store_true",
                       help=t("não abre o relatório no navegador", "don't open the report in the browser"))
        x.add_argument("--utc", action="store_true",
                       help=t("horários em UTC em vez do horário local", "show times in UTC instead of local time"))
    a = comando("autoteste", "self-test", "checagens reais + uma queda simulada, para ver a detecção funcionando",
                "real checks + a faked outage, to see detection working")
    a.add_argument("segundos", nargs="?", type=int, default=20, metavar=t("segundos", "seconds"),
                   help=t("duração da queda simulada (padrão 20)", "length of the faked outage (default 20)"))
    comando("bandeja", "tray", "ícone na bandeja que avisa quando a internet cai (precisa de sessão gráfica)",
            "tray icon that notifies you when the internet drops (needs a desktop session)")
    comando("config-exemplo", "example-config", "mostra um arquivo de configuração comentado",
            "print a commented settings file")
    return p


COMANDOS = {
    "rodar": cmd_rodar, "run": cmd_rodar,
    "status": cmd_status,
    "ao-vivo": cmd_ao_vivo, "live": cmd_ao_vivo,
    "relatorio": cmd_relatorio, "report": cmd_relatorio,
    "demo": cmd_demo,
    "autoteste": cmd_autoteste, "self-test": cmd_autoteste,
    "bandeja": cmd_bandeja, "tray": cmd_bandeja,
}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # O idioma precisa estar certo antes de montar a ajuda: --idioma na linha de comando, senão a configuração, senão o sistema.
    previa = argparse.ArgumentParser(add_help=False)
    previa.add_argument("--config")
    previa.add_argument("--idioma", "--language", dest="idioma")
    conhecidos, _ = previa.parse_known_args(argv)
    cfg = config.carregar(conhecidos.config)
    idioma.definir(conhecidos.idioma or cfg.idioma)

    p = montar_parser()
    args = p.parse_args(argv)
    if not args.comando:
        p.print_help()
        return 0
    if args.comando in ("config-exemplo", "example-config"):
        print(config.exemplo(), end="")
        return 0
    try:
        return COMANDOS[args.comando](args, cfg)
    except BrokenPipeError:
        return 0
    except OSError as e:
        print(t(f"Erro: {e}", f"Error: {e}"), file=sys.stderr)
        return 1
