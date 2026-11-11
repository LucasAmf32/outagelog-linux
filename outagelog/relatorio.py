"""Relatório: os números (DadosRelatorio) e o HTML, num arquivo só, sem scripts nem arquivos externos."""
from __future__ import annotations

import html
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import quote

from .estilo import CSS
from .idioma import atual, plural, t
from .modelo import ORDEM, Amostra, Lado, Status, explicacao, lado_de, rotulo, rotulo_lado
from .rastreador import Opcoes, Queda, Rastreador

ORDEM_LADOS = [Lado.OPERADORA, Lado.SEU_LADO, Lado.DNS, Lado.INDEFINIDO]
DIAS_SEMANA = {"pt": ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"],
               "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
MESES = {"pt": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
         "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}


# ---------------------------------------------------------------- fuso e formatação

class Fuso:
    """Converte UTC para o horário local do sistema (com horário de verão, se houver) ou mantém em UTC."""

    def __init__(self, utc: bool = False):
        self.utc = utc

    def local(self, tempo: datetime) -> datetime:
        return tempo.astimezone(timezone.utc) if self.utc else tempo.astimezone()

    def limites_do_dia(self, dia: date) -> tuple:
        """Início e fim do dia local, em UTC."""
        def meia_noite(d: date) -> datetime:
            if self.utc:
                return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            return datetime(d.year, d.month, d.day).astimezone().astimezone(timezone.utc)
        return meia_noite(dia), meia_noite(dia + timedelta(days=1))

    def nome(self, tempo: datetime) -> str:
        if self.utc:
            return "UTC"
        local = tempo.astimezone()
        off = local.utcoffset() or timedelta(0)
        sinal = "−" if off < timedelta(0) else "+"
        minutos = abs(int(off.total_seconds())) // 60
        nome = _nome_fuso() or local.tzname() or ""
        return f"{nome} (UTC{sinal}{minutos // 60:02d}:{minutos % 60:02d})".strip()


def _nome_fuso() -> str | None:
    if os.environ.get("TZ"):
        return os.environ["TZ"].lstrip(":")
    try:
        alvo = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in alvo:
            return alvo.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return None


def duracao(d: timedelta) -> str:
    """45 s, 7 min 12 s, 2 h 05 min, 3 d 4 h."""
    s = max(0, round(d.total_seconds()))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    m = s // 60
    if m < 24 * 60:
        return f"{m // 60} h {m % 60:02d} min"
    h = m // 60
    return f"{h // 24} d {h % 24} h"


def porcentagem(valor: float | None) -> str:
    """Disponibilidade sem nunca arredondar para 100% quando houve queda."""
    if valor is None:
        return t("n/d", "n/a")
    pct = math.floor(valor * 10000) / 100
    if valor < 1 and pct >= 100:
        pct = 99.99
    texto = f"{pct:.2f}"
    return t(texto.replace(".", ","), texto) + "%"


def data_longa(d) -> str:
    return f"{DIAS_SEMANA[atual()][d.weekday()]} {d.day} {MESES[atual()][d.month - 1]} {d.year}"


def data_curta(d) -> str:
    if atual() == "pt":
        return f"{DIAS_SEMANA['pt'][d.weekday()]} {d.day:02d}/{d.month:02d}"
    return f"{DIAS_SEMANA['en'][d.weekday()]} {d.day} {MESES['en'][d.month - 1]}"


def hora(d: datetime) -> str:
    return d.strftime("%H:%M:%S")


def ms_texto(v) -> str:
    return "—" if v is None else f"{v} ms"


def esc(s) -> str:
    return html.escape("" if s is None else str(s))


# ---------------------------------------------------------------- números

@dataclass
class EstatisticaDia:
    dia: date
    monitorado: timedelta
    quedas: int
    tempo_fora: timedelta
    quedas_rapidas: int
    mediana_ms: int | None
    p95_ms: int | None


@dataclass
class Interno:
    nome: str
    monitorado: timedelta
    quedas: list
    checagens: int

    @property
    def tempo_fora(self) -> timedelta:
        return sum((q.duracao for q in self.quedas), timedelta(0))

    @property
    def disponibilidade(self):
        if self.monitorado <= timedelta(0):
            return None
        return max(0.0, 1 - self.tempo_fora / self.monitorado)


@dataclass
class DadosRelatorio:
    de: datetime
    ate: datetime
    opcoes: Opcoes
    quedas: list = field(default_factory=list)
    autotestes: list = field(default_factory=list)
    periodos: list = field(default_factory=list)
    quedas_rapidas: list = field(default_factory=list)
    dias: list = field(default_factory=list)
    internos: list = field(default_factory=list)
    monitorado: timedelta = timedelta(0)
    tempo_fora: timedelta = timedelta(0)
    tempo_lento: timedelta = timedelta(0)
    mediana_ms: int | None = None
    fora_por_lado: dict = field(default_factory=dict)
    quedas_por_lado: dict = field(default_factory=dict)
    checagens: int = 0

    @property
    def maior(self) -> Queda | None:
        return max(self.quedas, key=lambda q: q.duracao, default=None)

    @property
    def disponibilidade(self):
        if self.monitorado <= timedelta(0):
            return None
        return max(0.0, 1 - self.tempo_fora / self.monitorado)

    @property
    def segundos_queda_rapida(self) -> int:
        return round(self.opcoes.min_falhas * self.opcoes.intervalo.total_seconds())


def percentil(valores: list, p: float):
    if not valores:
        return None
    valores.sort()
    i = math.ceil(p * len(valores)) - 1
    return valores[max(0, min(len(valores) - 1, i))]


def sobreposicao(a0, a1, b0, b1) -> timedelta:
    s, e = max(a0, b0), min(a1, b1)
    return e - s if e > s else timedelta(0)


def calcular(amostras: Iterable[Amostra], de: datetime, ate: datetime, opcoes: Opcoes, fuso: Fuso) -> DadosRelatorio:
    """Calcula tudo numa passada só, para meses de log nunca ficarem inteiros na memória."""
    rastreador = Rastreador(opcoes)
    internos: dict = {}  # nome -> [rastreador, checagens]
    latencia_dia: dict = {}
    latencia: list = []
    primeiro = ultimo = None
    n = 0
    for s in amostras:
        rastreador.adicionar(s)
        n += 1
        primeiro = primeiro or s.tempo
        ultimo = s.tempo
        for nome, ms in s.internos.items():
            if nome not in internos:
                internos[nome] = [Rastreador(opcoes), 0]
            internos[nome][0].adicionar(Amostra(tempo=s.tempo, link=True,
                                                status=Status.ONLINE if ms is not None else Status.INTERNET_FORA))
            internos[nome][1] += 1
        if not s.simulada and s.status in (Status.ONLINE, Status.LENTO) and s.melhor_ms is not None:
            latencia.append(s.melhor_ms)
            latencia_dia.setdefault(fuso.local(s.tempo).date(), []).append(s.melhor_ms)
    rastreador.finalizar()

    d = DadosRelatorio(
        de=max(primeiro, de) if primeiro else de,
        ate=min(ultimo, ate) if ultimo else ate,
        opcoes=opcoes,
        periodos=rastreador.periodos,
        quedas_rapidas=rastreador.quedas_rapidas,
        tempo_lento=rastreador.tempo_lento,
        monitorado=rastreador.tempo_monitorado,
        checagens=n,
        mediana_ms=percentil(latencia, 0.5),
    )
    d.quedas = [q for q in rastreador.quedas if not q.simulada]
    d.autotestes = [q for q in rastreador.quedas if q.simulada]
    d.tempo_fora = sum((q.duracao for q in d.quedas), timedelta(0))
    for lado in Lado:
        do_lado = [q for q in d.quedas if q.lado == lado]
        d.fora_por_lado[lado] = sum((q.duracao for q in do_lado), timedelta(0))
        d.quedas_por_lado[lado] = len(do_lado)

    for nome, (r, checagens) in sorted(internos.items()):
        r.finalizar()
        d.internos.append(Interno(nome, r.tempo_monitorado, r.quedas, checagens))

    if n:
        dia = fuso.local(d.de).date()
        ultimo_dia = fuso.local(d.ate).date()
        while dia <= ultimo_dia:
            ini, fim = fuso.limites_do_dia(dia)
            lat = latencia_dia.get(dia, [])
            d.dias.append(EstatisticaDia(
                dia=dia,
                monitorado=sum((sobreposicao(p.inicio, p.fim, ini, fim) for p in d.periodos), timedelta(0)),
                quedas=sum(1 for q in d.quedas if ini <= q.inicio < fim),
                tempo_fora=sum((sobreposicao(q.inicio, q.fim, ini, fim) for q in d.quedas), timedelta(0)),
                quedas_rapidas=sum(1 for x in d.quedas_rapidas if ini <= x < fim),
                mediana_ms=percentil(lat, 0.5),
                p95_ms=percentil(lat, 0.95),
            ))
            dia += timedelta(days=1)
    return d


# ---------------------------------------------------------------- HTML

CLASSE_LADO = {Lado.OPERADORA: "s-provider", Lado.SEU_LADO: "s-yours", Lado.DNS: "s-dns", Lado.INDEFINIDO: "s-unknown"}


def quedas_texto(n: int) -> str:
    return f"{n} " + plural(n, "queda", "quedas", "outage", "outages")


def titulo(d: DadosRelatorio) -> str:
    if not d.periodos:
        return t("Sem dados neste período", "No data for this period")
    if not d.quedas:
        return t(f"Nenhuma queda em {duracao(d.monitorado)} de monitoramento",
                 f"No outages in {duracao(d.monitorado)} of monitoring")
    return t(f"{quedas_texto(len(d.quedas))}, {duracao(d.tempo_fora)} sem internet em {duracao(d.monitorado)} de monitoramento",
             f"{quedas_texto(len(d.quedas))}, {duracao(d.tempo_fora)} offline in {duracao(d.monitorado)} of monitoring")


def gerar_html(d: DadosRelatorio, fuso: Fuso, alvos: list, versao: str, gerado: datetime | None = None) -> str:
    gerado = gerado or datetime.now(timezone.utc)
    h: list = []
    a = h.append
    if d.periodos:
        de, ate = fuso.local(d.de), fuso.local(d.ate)
        periodo = t(f"{data_longa(de)} {hora(de)} a {data_longa(ate)} {hora(ate)}",
                    f"{data_longa(de)} {hora(de)} to {data_longa(ate)} {hora(ate)}")
    else:
        periodo = t("Nenhuma checagem registrada neste período.", "No checks were logged in this period.")

    a(f'<!doctype html>\n<html lang="{t("pt-BR", "en")}"><head><meta charset="utf-8">')
    a('<meta name="viewport" content="width=device-width, initial-scale=1">')
    a(f"<title>{t('Relatório de quedas de internet', 'Internet outage report')} · {esc(data_longa(fuso.local(d.ate)))}</title>")
    a(f"<style>{CSS}</style></head><body><main>")
    a(f'<header><p class="eyebrow">{t("Relatório da conexão de internet", "Internet connection report")}</p>')
    a(f"<h1>{esc(titulo(d))}</h1>")
    a(f'<p class="sub">{esc(periodo)} · {t("horários em", "times in")} {esc(fuso.nome(d.ate))}</p></header>')

    if not d.periodos:
        a('<p class="empty">' + t(
            "O OutageLog não registrou nenhuma checagem entre essas datas. Confira se o serviço está rodando "
            "(<code>systemctl status outagelog</code>) e gere o relatório de novo mais tarde.",
            "OutageLog didn't record any checks between these dates. Check that the service is running "
            "(<code>systemctl status outagelog</code>) and make the report again later.") + "</p>")
    else:
        _resumo(a, d)
        _linhas_do_tempo(a, d, fuso)
        _tabela_quedas(a, d, fuso)
        if d.internos:
            _internos(a, d, fuso)
        _dias(a, d)
        if d.autotestes:
            _autotestes(a, d, fuso)
        _metodo(a, d, alvos)
    quando = f"{data_longa(fuso.local(gerado))} {hora(fuso.local(gerado))}"
    a("<footer>" + esc(t(f"Gerado em {quando} pelo OutageLog para Linux {versao}",
                          f"Generated {quando} by OutageLog for Linux {versao}"))
      + " · " + esc(t("baseado no OutageLog de BoazCohenJ (licença MIT)",
                      "based on OutageLog by BoazCohenJ (MIT license)")) + "</footer>")
    a("</main></body></html>")
    return "".join(h)


def _bloco(a, nome, valor, nota=None):
    a(f'<div class="tile"><div class="tile-label">{esc(nome)}</div><div class="tile-value">{esc(valor)}</div>')
    if nota:
        a(f'<div class="tile-note">{esc(nota)}</div>')
    a("</div>")


def _resumo(a, d: DadosRelatorio):
    a(f'<section class="summary"><div class="hero"><div class="hero-value">{esc(porcentagem(d.disponibilidade))}</div>'
      f'<div class="hero-label">{t("do tempo monitorado com internet", "of monitored time online")}</div></div><div class="tiles">')
    _bloco(a, t("Quedas", "Outages"), str(len(d.quedas)))
    _bloco(a, t("Tempo sem internet", "Time offline"), duracao(d.tempo_fora))
    _bloco(a, t("Maior queda", "Longest outage"), duracao(d.maior.duracao) if d.maior else t("nenhuma", "none"))
    _bloco(a, t("Lado da operadora", "Provider side"), duracao(d.fora_por_lado[Lado.OPERADORA]))
    _bloco(a, t("Quedas rápidas", "Brief drops"), str(len(d.quedas_rapidas)),
           t(f"menos de {d.segundos_queda_rapida} s, não contam como queda",
             f"under {d.segundos_queda_rapida} s, not counted as outages"))
    _bloco(a, t("Ping típico", "Typical ping"), ms_texto(d.mediana_ms) if d.mediana_ms is not None else t("n/d", "n/a"))
    a("</div></section>")
    if not d.quedas:
        return
    maximo = max(d.fora_por_lado[x] for x in ORDEM_LADOS)
    a(f'<section><h2>{t("Onde foram as quedas", "Where the outages were")}</h2><div class="bars">')
    for lado in ORDEM_LADOS:
        n = d.quedas_por_lado[lado]
        if n == 0:
            continue
        pct = 100 * d.fora_por_lado[lado] / maximo if maximo > timedelta(0) else 0
        a(f'<div class="bar-row"><div class="bar-label"><span class="key {CLASSE_LADO[lado]}"></span>{esc(rotulo_lado(lado))} '
          f'<span class="muted">· {esc(quedas_texto(n))}</span></div>'
          f'<div class="bar-track"><div class="bar {CLASSE_LADO[lado]}" style="width:{max(0.8, pct):.2f}%"></div>'
          f'<span class="bar-value">{esc(duracao(d.fora_por_lado[lado]))}</span></div></div>')
    a("</div></section>")


def _segmento(a, a_utc, b_utc, ini, fim, fuso, classe, dica=None, largura_min=0.0):
    if b_utc <= ini or a_utc >= fim:
        return
    x0, x1 = max(a_utc, ini), min(b_utc, fim)
    meia_noite = fuso.local(ini)
    p1 = max(0.0, (fuso.local(x0) - meia_noite).total_seconds() / 60)
    p2 = 1440.0 if x1 == fim else min(1440.0, (fuso.local(x1) - meia_noite).total_seconds() / 60)
    w = max(largura_min, p2 - p1)
    if p1 + w > 1440:
        p1 = 1440 - w
    a(f'<rect class="{classe}" x="{p1:.2f}" y="0" width="{w:.2f}" height="20">')
    if dica:
        a(f"<title>{esc(dica)}</title>")
    a("</rect>")


def _linhas_do_tempo(a, d: DadosRelatorio, fuso: Fuso):
    a(f'<section><h2>{t("Dia a dia", "Day by day")}</h2><div class="legend"><span><span class="key online"></span>Online</span>')
    for lado in ORDEM_LADOS:
        if d.quedas_por_lado[lado]:
            a(f'<span><span class="key {CLASSE_LADO[lado]}"></span>{esc(rotulo_lado(lado))}</span>')
    a('<span><span class="key nodata"></span>'
      + t("Sem monitorar (PC desligado ou serviço parado)", "Not monitoring (PC off or service stopped)") + "</span></div>")
    a('<div class="timeline"><div class="tl-row tl-axis"><div class="tl-day"></div><div class="tl-ticks">')
    for hr in range(0, 25, 6):
        menor = ' class="minor"' if hr % 12 else ""
        a(f'<span{menor} style="left:{hr / 24 * 100:.2f}%">{hr:02d}:00</span>')
    a("</div></div>")
    for dia in reversed(d.dias):
        ini, fim = fuso.limites_do_dia(dia.dia)
        a(f'<div class="tl-row"><div class="tl-day">{esc(data_curta(dia.dia))}</div>')
        legenda = t(f"{data_longa(dia.dia)}: {quedas_texto(dia.quedas)}, {duracao(dia.tempo_fora)} sem internet",
                    f"{data_longa(dia.dia)}: {quedas_texto(dia.quedas)}, {duracao(dia.tempo_fora)} offline")
        a(f'<svg class="tl" viewBox="0 0 1440 20" preserveAspectRatio="none" role="img" aria-label="{esc(legenda)}">')
        a('<rect class="tl-bg" x="0" y="0" width="1440" height="20" rx="3"/>')
        for p in d.periodos:
            _segmento(a, p.inicio, p.fim, ini, fim, fuso, "online")
        for q in d.quedas:
            dica = f"{hora(fuso.local(q.inicio))}–{hora(fuso.local(q.fim))} ({duracao(q.duracao)}): {rotulo(q.causa)}"
            _segmento(a, q.inicio, q.fim, ini, fim, fuso, CLASSE_LADO[q.lado], dica, largura_min=4)
        resumo = "—" if dia.quedas == 0 else f"{dia.quedas} · {duracao(dia.tempo_fora)}"
        a(f'</svg><div class="tl-sum">{esc(resumo)}</div></div>')
    a('</div><p class="note">' + t(
        "Passe o mouse sobre uma queda para ver os horários. Quedas curtas são desenhadas mais largas para continuarem "
        "visíveis; a tabela abaixo tem os horários exatos.",
        "Hover an outage for its times. Short outages are drawn wider than their real length so they stay visible; "
        "the table below has exact times.") + "</p></section>")


def _fim_texto(q: Queda, fuso: Fuso) -> str:
    ini, fim = fuso.local(q.inicio), fuso.local(q.fim)
    texto = hora(fim) if ini.date() == fim.date() else f"{data_curta(fim)} {hora(fim)}"
    if q.fim_incerto:
        texto = t(f"desconhecido (monitoramento parou às {texto})", f"unknown (monitoring stopped at {texto})")
    if q.em_andamento:
        texto = t(f"ainda fora às {texto}", f"still down at {texto}")
    return texto


def csv_quedas(d: DadosRelatorio, fuso: Fuso) -> str:
    linhas = [t("inicio,fim,duracao_segundos,veredito,lado,fim_incerto", "start,end,length_seconds,verdict,side,end_uncertain")]
    for q in d.quedas:
        linhas.append(",".join([
            fuso.local(q.inicio).strftime("%Y-%m-%d %H:%M:%S"),
            fuso.local(q.fim).strftime("%Y-%m-%d %H:%M:%S"),
            str(int(q.duracao.total_seconds())),
            rotulo(q.causa).replace(",", ""),
            rotulo_lado(q.lado).replace(",", ""),
            t("sim", "yes") if q.fim_incerto or q.em_andamento else t("não", "no"),
        ]))
    return "\r\n".join(linhas) + "\r\n"


def _tabela_quedas(a, d: DadosRelatorio, fuso: Fuso):
    a(f"<section><h2>{t('Todas as quedas', 'Every outage')}</h2>")
    if not d.quedas:
        a("<p>" + t(f"Nenhuma queda: todas as checagens funcionaram ou voltaram em até {d.segundos_queda_rapida} segundos.",
                    f"No outages: every check succeeded or recovered within {d.segundos_queda_rapida} seconds.")
          + "</p></section>")
        return
    a(f'<div class="table-wrap"><table><thead><tr><th class="idx">#</th><th>{t("Início", "Started")}</th>'
      f'<th>{t("Fim", "Ended")}</th><th class="num">{t("Duração", "Length")}</th><th>{t("Veredito", "Verdict")}</th>'
      "</tr></thead><tbody>")
    for i, q in enumerate(d.quedas, 1):
        ini = fuso.local(q.inicio)
        prefixo = t("pelo menos ", "at least ") if q.fim_incerto or q.em_andamento else ""
        a(f'<tr><td class="num idx">{i}</td><td class="when">{esc(data_curta(ini))} <span>{esc(hora(ini))}</span></td>'
          f'<td>{esc(_fim_texto(q, fuso))}</td><td class="num">{esc(prefixo + duracao(q.duracao))}</td>'
          f'<td><span class="key {CLASSE_LADO[q.lado]}"></span>{esc(rotulo(q.causa))}</td></tr>')
    a('</tbody></table></div><dl class="verdicts">')
    for causa in sorted({q.causa for q in d.quedas}, key=ORDEM.index):
        a(f'<dt><span class="key {CLASSE_LADO[lado_de(causa)]}"></span>{esc(rotulo(causa))}</dt><dd>{esc(explicacao(causa))}</dd>')
    a("</dl>")
    arquivo = t("quedas.csv", "outages.csv")
    a(f'<p class="note"><a download="{arquivo}" href="data:text/csv;charset=utf-8,{quote(csv_quedas(d, fuso), safe="")}">'
      + t("Baixar esta tabela em CSV", "Download this table as CSV") + "</a></p></section>")


def _internos(a, d: DadosRelatorio, fuso: Fuso):
    a(f'<section><h2>{t("Rede interna", "Local network")}</h2><p class="note" style="margin:0 0 12px">' + t(
        "Equipamentos da rede local checados junto com a internet. Se um deles cai sozinho, o problema é nele "
        "(ou no cabo dele), não na internet.",
        "Devices on the local network checked alongside the internet. If one goes down on its own, the problem is that "
        "device (or its cable), not the internet.") + "</p>")
    a(f'<div class="table-wrap"><table><thead><tr><th>{t("Equipamento", "Device")}</th>'
      f'<th class="num">{t("Disponível", "Available")}</th><th class="num">{t("Quedas", "Outages")}</th>'
      f'<th class="num">{t("Tempo fora", "Time down")}</th><th>{t("Últimas quedas", "Latest outages")}</th></tr></thead><tbody>')
    for it in d.internos:
        ultimas = ", ".join(f"{data_curta(fuso.local(q.inicio))} {hora(fuso.local(q.inicio))} ({duracao(q.duracao)})"
                            for q in it.quedas[-3:][::-1]) or "—"
        a(f'<tr><td>{esc(it.nome)}</td><td class="num">{esc(porcentagem(it.disponibilidade))}</td>'
          f'<td class="num">{len(it.quedas)}</td><td class="num">{esc(duracao(it.tempo_fora))}</td><td>{esc(ultimas)}</td></tr>')
    a("</tbody></table></div></section>")


def _dias(a, d: DadosRelatorio):
    a(f'<section><h2>{t("Resumo por dia", "Daily summary")}</h2><div class="table-wrap"><table><thead><tr>'
      f'<th>{t("Data", "Date")}</th><th class="num">{t("Monitorado", "Monitored")}</th>'
      f'<th class="num">{t("Quedas", "Outages")}</th><th class="num">{t("Sem internet", "Offline")}</th>'
      f'<th class="num">{t("Quedas rápidas", "Brief drops")}</th><th class="num">{t("Ping típico", "Typical ping")}</th>'
      f'<th class="num">{t("Pior 5% do ping", "Worst 5% ping")}</th></tr></thead><tbody>')
    for dia in reversed(d.dias):
        a(f'<tr><td>{esc(data_longa(dia.dia))}</td><td class="num">{esc(duracao(dia.monitorado))}</td>'
          f'<td class="num">{dia.quedas}</td><td class="num">{esc(duracao(dia.tempo_fora))}</td>'
          f'<td class="num">{dia.quedas_rapidas}</td><td class="num">{esc(ms_texto(dia.mediana_ms))}</td>'
          f'<td class="num">{esc(ms_texto(dia.p95_ms))}</td></tr>')
    a("</tbody></table></div></section>")


def _autotestes(a, d: DadosRelatorio, fuso: Fuso):
    a(f'<section><h2>{t("Autotestes", "Self-tests")}</h2><p class="note">' + t(
        "Estas quedas foram simuladas pelo autoteste do OutageLog e ficam fora de todos os números acima.",
        "These outages were faked by OutageLog's self-test and are left out of every number above.") + "</p><ul>")
    for q in d.autotestes:
        ini = fuso.local(q.inicio)
        a(f"<li>{esc(f'{data_longa(ini)} {hora(ini)}, {duracao(q.duracao)}: {rotulo(q.causa)}')}</li>")
    a("</ul></section>")


def _metodo(a, d: DadosRelatorio, alvos: list):
    o = d.opcoes
    intervalo = int(o.intervalo.total_seconds())
    servidores = esc(", ".join(alvos))
    aquecimento = int(o.aquecimento.total_seconds())
    itens = [
        t(f"A cada {intervalo} segundos (um pouco mais quando os servidores não respondem, porque cada checagem espera até "
          f"1,5 s) este PC checou ao mesmo tempo: o roteador, três servidores independentes da internet ({servidores}, de "
          "empresas diferentes) e a consulta de DNS de dois sites conhecidos, feita direto nos servidores DNS da rede, sem "
          "passar pelo cache local.",
          f"About every {intervalo} seconds (a little less often while servers don't answer, since each check waits up to "
          f"1.5 s) this PC checked at once: its router, three independent internet servers ({servidores}, run by different "
          "companies), and DNS lookups of two well-known websites, sent straight to the network's DNS servers, bypassing "
          "the local cache."),
        t("Os servidores receberam ping; se não respondessem, o OutageLog tentava abrir uma conexão na porta 443, para que "
          "redes que bloqueiam ping não pareçam quedas. Com o roteador, se o ping não responder, ele tenta as portas 80, 443 e 53.",
          "Servers were pinged; if a ping went unanswered, OutageLog also tried a TCP connection on port 443, so networks "
          "that block ping don't look like outages. For the router, it tries ports 80, 443 and 53 if ping gets no answer."),
        t("Só conta como falha de DNS quando os dois sites da rodada falham, para que um site com problema não pareça falha da rede.",
          "DNS only counts as failed when both websites of the round fail, so one website's trouble doesn't look like a "
          "network failure."),
        t(f"Uma <strong>queda</strong> é pelo menos {o.min_falhas} rodadas seguidas com falha e termina na primeira de "
          f"{o.min_recuperacao} rodadas boas. Falhas mais curtas contam como <strong>quedas rápidas</strong>.",
          f"An <strong>outage</strong> is at least {o.min_falhas} failed rounds in a row, and ends at the first of "
          f"{o.min_recuperacao} good rounds. Shorter drops are counted as <strong>brief drops</strong>."),
        t("<strong>Lado da operadora</strong> quer dizer que o roteador continuou respondendo enquanto nenhum servidor da "
          "internet respondia, então a falha foi depois do roteador: na linha, no modem ou na rede da operadora. "
          "<strong>Seu lado</strong> quer dizer que este PC perdeu a conexão ou não alcançava o roteador.",
          "<strong>Provider side</strong> means the router kept answering while none of the internet servers did, so the "
          "break was past the router: the line, the modem or the provider's network. <strong>Your side</strong> means this "
          "PC lost its connection or couldn't reach the router."),
        t(f"As checagens não são julgadas nos primeiros {aquecimento} segundos depois que o monitoramento começa ou o PC "
          "volta da suspensão, então a reconexão não conta como queda. O tempo com o PC desligado ou suspenso não entra na conta.",
          f"Checks aren't judged for {aquecimento} seconds after monitoring starts or the PC wakes from sleep, so "
          "reconnecting isn't counted as an outage. Time when the PC was off or asleep isn't counted at all."),
        t("Esta é a visão de um PC. Se ele estiver no Wi-Fi, um sinal fraco aparece como “seu lado”, nunca como “lado da operadora”.",
          "This is one PC's view. If it's on Wi-Fi, a weak signal shows up as “your side”, never as “provider side”."),
    ]
    a(f'<section class="method"><h2>{t("Como foi medido", "How this was measured")}</h2><ul>')
    for item in itens:
        a(f"<li>{item}</li>")
    a("</ul></section>")
