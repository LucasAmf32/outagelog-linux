"""Ícone na bandeja: mostra o estado da conexão e avisa quando a internet cai e volta.

Não faz nenhuma checagem de rede: só acompanha o log que o serviço grava, então não importa
quantos usuários abram a bandeja. A parte de lógica (Observador) não depende da interface e é testada.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone

from . import VERSAO, config, relatorio
from .idioma import plural, t
from .modelo import Amostra, Lado, Status, explicacao, rotulo, rotulo_lado
from .rastreador import Opcoes, Queda, Rastreador
from .registro import Registro, interpretar

PARADO_DEPOIS = timedelta(seconds=20)

_TITULO_QUEDA = {
    Lado.OPERADORA: ("Internet caiu: problema na operadora", "Internet down: provider's side"),
    Lado.SEU_LADO: ("Sem conexão: problema na sua rede", "No connection: your side"),
    Lado.DNS: ("Internet com problema: DNS não responde", "Internet trouble: DNS not answering"),
    Lado.INDEFINIDO: ("Internet caiu", "Internet down"),
}


def titulo_queda(lado: Lado) -> str:
    return t(*_TITULO_QUEDA[lado])  # sem checagem nova por mais que isso = monitoramento parado

CORES_ICONE = {"verde": "#2e9e44", "amarelo": "#e3a008", "vermelho": "#d93a26", "cinza": "#8a8a8a"}


def cor_de(status: Status | None, parado: bool) -> str:
    if parado or status is None:
        return "cinza"
    if status == Status.ONLINE:
        return "verde"
    if status == Status.LENTO:
        return "amarelo"
    return "vermelho"


# ---------------------------------------------------------------- lógica (sem interface)

class LeitorIncremental:
    """Lê só as linhas novas do arquivo do dia, trocando de arquivo na virada do dia."""

    def __init__(self, pasta: str):
        self.pasta = pasta
        self._caminho = None
        self._posicao = 0
        self._resto = ""

    def novas(self, hoje: date | None = None) -> list:
        hoje = hoje or date.today()
        caminho = os.path.join(self.pasta, f"samples-{hoje.isoformat()}.csv")
        if caminho != self._caminho:
            self._caminho, self._posicao, self._resto = caminho, 0, ""
        try:
            tamanho = os.path.getsize(caminho)
        except OSError:
            return []
        if tamanho < self._posicao:  # arquivo recriado (apagaram o log de hoje)
            self._posicao, self._resto = 0, ""
        if tamanho == self._posicao:
            return []
        try:
            with open(caminho, "rb") as f:
                f.seek(self._posicao)
                bloco = f.read()
        except OSError:
            return []
        self._posicao += len(bloco)
        texto = self._resto + bloco.decode("utf-8", errors="replace")
        linhas = texto.split("\n")
        self._resto = linhas.pop()  # pedaço de linha ainda sendo escrito
        return [s for s in (interpretar(l) for l in linhas) if s is not None]


class Observador:
    """Acompanha o log, mantém o rastreador de quedas e decide quando avisar."""

    def __init__(self, pasta: str, opcoes: Opcoes, avisar, agora=None):
        self.pasta = pasta
        self.opcoes = opcoes
        self.avisar = avisar  # função(titulo, texto, cor)
        self._agora = agora or (lambda: datetime.now(timezone.utc))
        self.rastreador = Rastreador(opcoes)
        self.leitor = LeitorIncremental(pasta)
        self.ultima: Amostra | None = None
        self.parado_avisado = False
        self._avisos = deque()
        self.notificar = True

    def carregar_historico(self) -> None:
        """Carrega as últimas 24 h sem avisar (quedas antigas não viram notificação)."""
        agora = self._agora()
        hoje = agora.astimezone().date()
        inicio_hoje = datetime(hoje.year, hoje.month, hoje.day).astimezone().astimezone(timezone.utc)
        for s in Registro(self.pasta).ler(agora - timedelta(days=1), inicio_hoje - timedelta(microseconds=1)):
            self._adicionar(s)
        for s in self.leitor.novas(hoje):
            self._adicionar(s)
        self.rastreador.ao_iniciar = self._queda_comecou
        self.rastreador.ao_terminar = self._queda_terminou

    def _adicionar(self, s: Amostra) -> None:
        self.rastreador.adicionar(s)
        if self.ultima is None or s.tempo > self.ultima.tempo:
            self.ultima = s

    def atualizar(self) -> None:
        agora = self._agora()
        for s in self.leitor.novas(agora.astimezone().date()):
            self._adicionar(s)
        if self.parado:
            if not self.parado_avisado and self.ultima is not None:
                self.parado_avisado = True
                self._aviso(t("Monitoramento parado", "Monitoring stopped"),
                            t("O OutageLog não está gravando checagens novas. Confira com: systemctl status outagelog",
                              "OutageLog isn't logging new checks. Check with: systemctl status outagelog"),
                            "cinza", limitar=False)
        elif self.parado_avisado:
            self.parado_avisado = False

    @property
    def parado(self) -> bool:
        return self.ultima is None or self._agora() - self.ultima.tempo > PARADO_DEPOIS

    @property
    def status(self) -> Status | None:
        return None if self.ultima is None else self.ultima.status

    @property
    def cor(self) -> str:
        return cor_de(self.status, self.parado)

    def quedas_hoje(self) -> int:
        hoje = self._agora().astimezone().date()
        n = sum(1 for q in self.rastreador.quedas if not q.simulada and q.inicio.astimezone().date() == hoje)
        atual = self.rastreador.atual
        if atual is not None and not atual.simulada and atual.inicio.astimezone().date() == hoje:
            n += 1
        return n

    def resumo(self) -> str:
        """Uma linha para a dica do ícone e o menu."""
        if self.ultima is None:
            return t("sem dados ainda", "no data yet")
        if self.parado:
            idade = relatorio.duracao(self._agora() - self.ultima.tempo)
            return t(f"monitoramento parado (última checagem há {idade})", f"monitoring stopped (last check {idade} ago)")
        n = self.quedas_hoje()
        texto = f"{rotulo(self.status)} · {n} " + plural(n, "queda hoje", "quedas hoje", "outage today", "outages today")
        atual = self.rastreador.atual
        if atual is not None and not atual.simulada:
            fora = relatorio.duracao(self._agora() - atual.inicio)
            texto += t(f" · fora há {fora}", f" · down for {fora}")
        return texto

    def _queda_comecou(self, q: Queda) -> None:
        extra = t(" (autoteste)", " (self-test)") if q.simulada else ""
        inicio = f"{q.inicio.astimezone():%H:%M:%S}"
        self._aviso(titulo_queda(q.lado) + extra,
                    explicacao(q.causa) + t(f" Começou às {inicio}. O OutageLog está registrando.",
                                            f" Started at {inicio}. OutageLog is logging it."),
                    "vermelho")

    def _queda_terminou(self, q: Queda) -> None:
        if q.fim_incerto:
            return  # o monitoramento parou no meio (suspensão): não há o que dizer
        extra = t(" (autoteste)", " (self-test)") if q.simulada else ""
        tempo, lado = relatorio.duracao(q.duracao), rotulo_lado(q.lado).lower()
        self._aviso(t("Internet voltou", "Back online") + extra,
                    t(f"Ficou fora {tempo} ({lado}). Já está no log e vai aparecer no próximo relatório.",
                      f"It was down for {tempo} ({lado}). It's in the log and the next report."), "verde")

    def _aviso(self, titulo: str, texto: str, cor: str, limitar: bool = True) -> None:
        if not self.notificar:
            return
        if limitar:
            # Uma conexão que fica caindo e voltando não pode encher a tela: no máximo 4 avisos a cada 10 minutos.
            agora = time.monotonic()
            while self._avisos and agora - self._avisos[0] > 600:
                self._avisos.popleft()
            if len(self._avisos) >= 4:
                return
            self._avisos.append(agora)
        self.avisar(titulo, texto, cor)


# ---------------------------------------------------------------- ícones

def pasta_cache() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    pasta = os.path.join(base, "outagelog")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def criar_icones() -> dict:
    """Um círculo colorido com um traço de "pulso", em SVG, para cada estado."""
    pasta = pasta_cache()
    caminhos = {}
    for nome, cor in CORES_ICONE.items():
        caminho = os.path.join(pasta, f"outagelog-{nome}.svg")
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
               f'<circle cx="32" cy="32" r="28" fill="{cor}" stroke="#ffffff" stroke-opacity=".85" stroke-width="3"/>'
               '<path d="M12 34h10l5-11 8 22 6-15 4 4h7" fill="none" stroke="#ffffff" stroke-width="5" '
               'stroke-linecap="round" stroke-linejoin="round"/></svg>')
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                f.write(svg)
        except OSError:
            pass
        caminhos[nome] = caminho
    return caminhos


# ---------------------------------------------------------------- interface (GTK)

def _carregar_gtk():
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk
        return gi, GLib, Gtk
    except (ImportError, ValueError) as e:
        raise RuntimeError(t(
            "A bandeja precisa do GTK para Python (no Linux Mint já vem instalado). "
            "Se faltar: sudo apt install python3-gi gir1.2-gtk-3.0",
            "The tray icon needs GTK for Python (preinstalled on Linux Mint and Ubuntu desktops). "
            "If it's missing: sudo apt install python3-gi gir1.2-gtk-3.0")) from e


class Notificador:
    def __init__(self, gi, icones: dict):
        self.icones = icones
        self._notify = None
        try:
            gi.require_version("Notify", "0.7")
            from gi.repository import Notify
            if Notify.init("OutageLog"):
                self._notify = Notify
        except (ImportError, ValueError):
            pass
        self._ultima = None

    def __call__(self, titulo: str, texto: str, cor: str) -> None:
        icone = self.icones.get(cor, "")
        if self._notify is not None:
            try:
                n = self._notify.Notification.new(titulo, texto, icone)
                n.set_urgency(2 if cor == "vermelho" else 1)
                n.show()
                self._ultima = n  # mantém a referência viva
                return
            except Exception:
                pass
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "OutageLog", "-i", icone, titulo, texto],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Icone:
    """Escolhe o melhor jeito de pôr um ícone na bandeja: XApp (Cinnamon/Mint), AppIndicator ou Gtk.StatusIcon."""

    def __init__(self, gi, Gtk, menu, ao_clicar, icone_inicial: str):
        self.tipo = None
        self._icone = None
        self._menu = menu
        try:
            gi.require_version("XApp", "1.0")
            from gi.repository import XApp
            ic = XApp.StatusIcon.new()
            ic.set_name("outagelog")
            ic.set_icon_name(icone_inicial)
            ic.set_primary_menu(menu)
            ic.set_secondary_menu(menu)
            ic.set_visible(True)
            self._icone, self.tipo = ic, "xapp"
            return
        except (ImportError, ValueError, AttributeError):
            pass
        for nome in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(nome, "0.1")
                modulo = __import__("gi.repository." + nome, fromlist=[nome])
                ind = modulo.Indicator.new("outagelog", icone_inicial, modulo.IndicatorCategory.APPLICATION_STATUS)
                ind.set_status(modulo.IndicatorStatus.ACTIVE)
                ind.set_title("OutageLog")
                ind.set_menu(menu)
                self._icone, self.tipo = ind, "appindicator"
                return
            except (ImportError, ValueError, AttributeError):
                continue
        ic = Gtk.StatusIcon()
        ic.set_from_file(icone_inicial)
        ic.set_title("OutageLog")
        ic.connect("activate", lambda *_: ao_clicar())
        ic.connect("popup-menu", lambda icone, botao, tempo: menu.popup(None, None, Gtk.StatusIcon.position_menu,
                                                                         icone, botao, tempo))
        ic.set_visible(True)
        self._icone, self.tipo = ic, "statusicon"

    def mudar(self, caminho_icone: str | None, dica: str) -> None:
        """Troca o ícone (só quando a cor muda) e a dica que aparece ao passar o mouse."""
        if self.tipo == "xapp":
            if caminho_icone:
                self._icone.set_icon_name(caminho_icone)
            self._icone.set_tooltip_text(dica)
        elif self.tipo == "appindicator":
            if caminho_icone:  # o AppIndicator não tem dica de mouse; o resumo fica na primeira linha do menu
                self._icone.set_icon_full(caminho_icone, dica)
        else:
            if caminho_icone:
                self._icone.set_from_file(caminho_icone)
            self._icone.set_tooltip_text(dica)


def pasta_relatorios() -> str:
    documentos = None
    if shutil.which("xdg-user-dir"):
        try:
            documentos = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True, text=True,
                                        timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            documentos = None
    if not documentos or documentos == os.path.expanduser("~") or not os.path.isdir(documentos):
        documentos = os.path.expanduser("~")
    pasta = os.path.join(documentos, "OutageLog")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def abrir(caminho: str) -> None:
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", caminho], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


class Bandeja:
    def __init__(self, cfg: config.Config, pasta: str):
        self.gi, self.GLib, self.Gtk = _carregar_gtk()
        self.cfg = cfg
        self.pasta = pasta
        self.icones = criar_icones()
        self.notificador = Notificador(self.gi, self.icones)
        self.opcoes = Opcoes(intervalo=timedelta(seconds=cfg.intervalo_segundos))
        self.obs = Observador(pasta, self.opcoes, self.notificador)
        self._cor_atual = None
        self._montar_menu()
        self.icone = Icone(self.gi, self.Gtk, self.menu, self.mostrar_status, self.icones["cinza"])

    def _item(self, rotulo, acao=None, sensivel=True):
        item = self.Gtk.MenuItem(label=rotulo)
        if acao:
            item.connect("activate", lambda *_: acao())
        item.set_sensitive(sensivel)
        self.menu.append(item)
        return item

    def _montar_menu(self):
        Gtk = self.Gtk
        self.menu = Gtk.Menu()
        self.item_status = self._item(t("OutageLog: carregando…", "OutageLog: loading…"), self.mostrar_status)
        self.menu.append(Gtk.SeparatorMenuItem())
        relatorios = Gtk.MenuItem(label=t("Gerar relatório", "Make a report"))
        sub = Gtk.Menu()
        opcoes = ((t("Últimas 24 horas", "Last 24 hours"), 1), (t("Últimos 7 dias", "Last 7 days"), 7),
                  (t("Últimos 30 dias", "Last 30 days"), 30), (t("Tudo que foi registrado", "Everything logged"), 3650))
        for nome, dias in opcoes:
            item = Gtk.MenuItem(label=nome)
            item.connect("activate", lambda _i, d=dias: self.gerar_relatorio(d))
            sub.append(item)
        relatorios.set_submenu(sub)
        self.menu.append(relatorios)
        self._item(t("Abrir pasta dos relatórios", "Open reports folder"), lambda: abrir(pasta_relatorios()))
        self._item(t("Abrir pasta dos logs", "Open log folder"), lambda: abrir(self.pasta))
        self.menu.append(Gtk.SeparatorMenuItem())
        self.item_avisos = Gtk.CheckMenuItem(label=t("Avisar quando a internet cair", "Notify me about outages"))
        self.item_avisos.set_active(True)
        self.item_avisos.connect("toggled", lambda i: setattr(self.obs, "notificar", i.get_active()))
        self.menu.append(self.item_avisos)
        self.menu.append(Gtk.SeparatorMenuItem())
        self._item(t("Sair da bandeja", "Quit tray icon"), self.Gtk.main_quit)
        self.menu.show_all()

    def mostrar_status(self):
        s = self.obs.ultima
        detalhe = ""
        if s is not None:
            partes = [t("roteador ", "router ") + relatorio.ms_texto(s.gateway_ms)]
            partes += [f"{ip} {relatorio.ms_texto(ms)}" for ip, ms in zip(self.cfg.alvos, s.alvos_ms)]
            if s.dns_ok is not None:
                partes.append("DNS " + (relatorio.ms_texto(s.dns_ms) if s.dns_ok else t("falhou", "failed")))
            detalhe = " · ".join(partes)
        self.notificador(f"OutageLog: {self.obs.resumo()}",
                         detalhe or t("Ainda não há checagens no log.", "There are no checks in the log yet."), self.obs.cor)

    def gerar_relatorio(self, dias: int):
        self.notificador(t("Gerando o relatório…", "Making the report…"),
                         t("Ele abre no navegador assim que ficar pronto.", "It opens in your browser as soon as it's ready."),
                         "cinza")

        def trabalho():
            try:
                fuso = relatorio.Fuso()
                ate = datetime.now(timezone.utc)
                de = ate - timedelta(days=dias)
                dados = relatorio.calcular(Registro(self.pasta).ler(de, ate), de, ate, self.opcoes, fuso)
                html = relatorio.gerar_html(dados, fuso, self.cfg.alvos, VERSAO)
                nome = t("relatorio-quedas", "outage-report")
                caminho = os.path.join(pasta_relatorios(), f"{nome}-{datetime.now():%Y-%m-%d-%H%M}.html")
                with open(caminho, "w", encoding="utf-8") as f:
                    f.write(html)
                self.GLib.idle_add(lambda: abrir(caminho) and False)
            except Exception as e:
                msg = str(e)
                self.GLib.idle_add(lambda: self.notificador(t("Não deu para gerar o relatório", "Couldn't make the report"), msg, "vermelho") and False)

        threading.Thread(target=trabalho, daemon=True).start()

    def atualizar(self):
        try:
            self.obs.atualizar()
            resumo = self.obs.resumo()
            self.item_status.set_label(f"OutageLog: {resumo}")
            cor = self.obs.cor
            self.icone.mudar(self.icones[cor] if cor != self._cor_atual else None, f"OutageLog: {resumo}")
            self._cor_atual = cor
        except Exception as e:  # um erro de leitura não pode derrubar a bandeja
            print(t(f"Erro ao atualizar: {e!r}", f"Update error: {e!r}"), file=sys.stderr)
        return True  # continua chamando

    def rodar(self) -> int:
        self.obs.carregar_historico()
        self.atualizar()
        self.GLib.timeout_add_seconds(2, self.atualizar)
        try:
            self.Gtk.main()
        except KeyboardInterrupt:
            pass
        return 0


def ja_rodando() -> bool:
    """Só uma bandeja por usuário: segura uma trava enquanto roda."""
    import fcntl
    pasta = os.environ.get("XDG_RUNTIME_DIR") or pasta_cache()
    global _trava
    _trava = open(os.path.join(pasta, "outagelog-bandeja.lock"), "w")
    try:
        fcntl.flock(_trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True


_trava = None

def cmd_bandeja(args, cfg) -> int:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print(t("A bandeja precisa de uma sessão gráfica (abra pelo menu ou por um terminal da área de trabalho).",
                "The tray icon needs a desktop session (open it from the menu or from a terminal on the desktop)."),
              file=sys.stderr)
        return 1
    if ja_rodando():
        print(t("A bandeja já está aberta.", "The tray icon is already running."))
        return 0
    try:
        bandeja = Bandeja(cfg, config.pasta_dados(args.dados))
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    return bandeja.rodar()
