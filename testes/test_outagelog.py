"""Testes. Rode com: python3 -m unittest discover -s testes"""
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from outagelog import config, demo, idioma, relatorio, sondas  # noqa: E402
from outagelog.classificador import Classificador  # noqa: E402
from outagelog.modelo import Amostra, Lado, Status  # noqa: E402
from outagelog.rastreador import Opcoes, Rastreador  # noqa: E402
from outagelog.registro import Registro, formatar, interpretar  # noqa: E402

idioma.definir("pt")  # os testes conferem textos em português; TesteIngles troca e volta

T0 = datetime(2026, 9, 26, 10, 0, 0, tzinfo=timezone.utc)
SEM_AQUECIMENTO = Opcoes(aquecimento=timedelta(0))
LETRAS = {"P": Status.QUEDA_OPERADORA, "L": Status.QUEDA_LOCAL, "N": Status.SEM_CONEXAO,
          "D": Status.FALHA_DNS, "s": Status.LENTO}


def padrao(texto, inicio=T0, simulada=False):
    """Amostras a cada 2 s: '.' online, P operadora, L local, N sem conexão, D DNS, s lento, '|' pausa de 10 min."""
    lista, t = [], inicio
    for c in texto:
        if c == "|":
            t += timedelta(minutes=10)
            continue
        lista.append(Amostra(tempo=t, status=LETRAS.get(c, Status.ONLINE), simulada=simulada, alvos_ms=[10, 12, 14]))
        t += timedelta(seconds=2)
    return lista


def rodar(texto, opcoes=None):
    r = Rastreador(opcoes or SEM_AQUECIMENTO)
    for s in padrao(texto):
        r.adicionar(s)
    r.finalizar()
    return r


class TesteRastreador(unittest.TestCase):
    def test_uma_falha_e_queda_rapida(self):
        r = rodar("....P....")
        self.assertEqual(r.quedas, [])
        self.assertEqual(len(r.quedas_rapidas), 1)

    def test_duas_falhas_viram_queda(self):
        r = rodar("....PPPP....")
        self.assertEqual(len(r.quedas), 1)
        q = r.quedas[0]
        self.assertEqual(q.inicio, T0 + timedelta(seconds=8))
        self.assertEqual(q.fim, T0 + timedelta(seconds=16))
        self.assertEqual(q.duracao, timedelta(seconds=8))
        self.assertEqual(q.causa, Status.QUEDA_OPERADORA)
        self.assertEqual(q.lado, Lado.OPERADORA)

    def test_uma_rodada_boa_nao_termina_a_queda(self):
        r = rodar("..PPP.PPP....")
        self.assertEqual(len(r.quedas), 1)
        self.assertEqual(r.quedas[0].fim, T0 + timedelta(seconds=18))

    def test_causa_e_a_da_maioria(self):
        self.assertEqual(rodar("..NNPPPPP....").quedas[0].causa, Status.QUEDA_OPERADORA)

    def test_pausa_fecha_queda_como_incerta(self):
        q = rodar("..PPPP|......").quedas[0]
        self.assertTrue(q.fim_incerto)
        self.assertEqual(q.fim, T0 + timedelta(seconds=10))

    def test_pausa_nao_conta_como_monitorado(self):
        r = rodar("......|......")
        self.assertEqual(len(r.periodos), 2)
        self.assertEqual(r.tempo_monitorado, timedelta(seconds=20))

    def test_aquecimento_depois_de_acordar(self):
        r = rodar("." * 20 + "|" + "NNN" + "." * 20, Opcoes(aquecimento=timedelta(seconds=30)))
        self.assertEqual(r.quedas, [])
        self.assertEqual(r.quedas_rapidas, [])

    def test_queda_depois_do_aquecimento_conta(self):
        self.assertEqual(len(rodar("........PPPP....", Opcoes(aquecimento=timedelta(seconds=10))).quedas), 1)

    def test_queda_aberta_no_fim_esta_em_andamento(self):
        q = rodar("....PPPP").quedas[0]
        self.assertTrue(q.em_andamento)
        self.assertFalse(q.fim_incerto)

    def test_lento_nao_e_queda_mas_e_contado(self):
        r = rodar("..ssss..")
        self.assertEqual(r.quedas, [])
        self.assertEqual(r.tempo_lento, timedelta(seconds=8))

    def test_simuladas_sao_marcadas_e_nao_viram_queda_rapida(self):
        r = Rastreador(SEM_AQUECIMENTO)
        for s in padrao("...."):
            r.adicionar(s)
        for s in padrao("PPP", T0 + timedelta(seconds=8), simulada=True):
            r.adicionar(s)
        for s in padrao("P", T0 + timedelta(seconds=30), simulada=True):
            r.adicionar(s)
        for s in padrao("....", T0 + timedelta(seconds=14)):
            r.adicionar(s)
        r.finalizar()
        self.assertEqual(len(r.quedas), 1)
        self.assertTrue(r.quedas[0].simulada)
        self.assertEqual(r.quedas_rapidas, [])

    def test_eventos_de_inicio_e_fim(self):
        r = Rastreador(SEM_AQUECIMENTO)
        eventos = []
        r.ao_iniciar = lambda q: eventos.append("inicio")
        r.ao_terminar = lambda q: eventos.append("fim")
        for s in padrao("..PPP..."):
            r.adicionar(s)
        self.assertEqual(eventos, ["inicio", "fim"])


def resultado(gw, alvos, dns=True, link=True, gateway_ip="192.168.1.1"):
    return Amostra(tempo=T0, link=link, gateway_ip=gateway_ip, gateway_ms=gw, alvos_ms=alvos, dns_ok=dns)


TODOS = [10, 12, 14]
NENHUM = [None, None, None]


class TesteClassificador(unittest.TestCase):
    def test_online(self):
        self.assertEqual(Classificador().classificar(resultado(2, TODOS)), Status.ONLINE)

    def test_roteador_ok_internet_fora_e_operadora(self):
        self.assertEqual(Classificador().classificar(resultado(2, NENHUM)), Status.QUEDA_OPERADORA)

    def test_roteador_que_respondia_e_parou_e_local(self):
        c = Classificador()
        c.classificar(resultado(2, TODOS))
        self.assertEqual(c.classificar(resultado(None, NENHUM)), Status.QUEDA_LOCAL)

    def test_roteador_que_nunca_responde_e_indeterminado(self):
        self.assertEqual(Classificador().classificar(resultado(None, NENHUM)), Status.INTERNET_FORA)

    def test_sem_link_e_sem_conexao(self):
        self.assertEqual(Classificador().classificar(resultado(None, NENHUM, link=False, gateway_ip=None)), Status.SEM_CONEXAO)

    def test_dns(self):
        self.assertEqual(Classificador().classificar(resultado(2, TODOS, dns=False)), Status.FALHA_DNS)
        self.assertEqual(Classificador().classificar(resultado(2, TODOS, dns=None)), Status.ONLINE)

    def test_um_de_tres_e_lento(self):
        self.assertEqual(Classificador().classificar(resultado(2, [20, None, None])), Status.LENTO)
        self.assertEqual(Classificador().classificar(resultado(2, [20, 25, None])), Status.ONLINE)

    def test_servidor_mais_rapido_lento(self):
        self.assertEqual(Classificador(300).classificar(resultado(2, [450, 500, 600])), Status.LENTO)


class TesteRegistro(unittest.TestCase):
    def test_ida_e_volta(self):
        s = Amostra(tempo=T0 + timedelta(milliseconds=123), status=Status.QUEDA_OPERADORA, link=True, gateway_ms=3,
                    alvos_ms=[None, 15, None], dns_ok=False, simulada=True, internos={"impressora": None, "srv": 2})
        v = interpretar(formatar(s))
        self.assertEqual((v.tempo, v.status, v.gateway_ms, v.alvos_ms, v.dns_ok, v.simulada, v.internos),
                         (s.tempo, s.status, 3, [None, 15, None], False, True, {"impressora": None, "srv": 2}))

    def test_le_log_do_outagelog_do_windows(self):
        v = interpretar("2026-09-26T10:00:02.000Z,ProviderOutage,1,2,,,0,||")
        self.assertEqual(v.status, Status.QUEDA_OPERADORA)
        self.assertEqual(v.alvos_ms, [None, None, None])
        self.assertIsNone(v.dns_ok)

    def test_linhas_estragadas_sao_ignoradas(self):
        for linha in ["", "# comentário", "time_utc,status", "lixo", "2026-09-26T10:00:00.000Z,Inventado,1,,,,0,1|2|3",
                      "2026-09-26T10:00:00.000Z,Up,1,x,,,0,1|2|3"]:
            self.assertIsNone(interpretar(linha))

    def test_grava_le_e_poda(self):
        with tempfile.TemporaryDirectory() as pasta:
            reg = Registro(pasta)
            agora = datetime.now(timezone.utc)
            for s in padrao("..PP..", agora - timedelta(seconds=30)):
                reg.anexar(s)
            reg.fechar()
            lidas = list(reg.ler(agora - timedelta(hours=1), agora))
            self.assertEqual(len(lidas), 6)
            velho = os.path.join(pasta, "samples-2000-01-01.csv")
            open(velho, "w").close()
            reg.podar(60)
            self.assertFalse(os.path.exists(velho))
            self.assertEqual(len(list(reg.ler(agora - timedelta(hours=1), agora))), 6)


class TesteSondas(unittest.TestCase):
    ROTAS = ("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
             "tun0\t00000000\t00000000\t0001\t0\t0\t50\t00000000\t0\t0\t0\n"
             "wlp2s0\t00000000\t0101A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"
             "enp3s0\t00000000\t0100A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
             "enp3s0\t0000A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n")

    def test_rota_padrao_prefere_placa_fisica_de_menor_metrica(self):
        self.assertEqual(sondas.rota_padrao(self.ROTAS), ("192.168.0.1", True))

    def test_sem_rota_padrao_e_sem_rede(self):
        self.assertEqual(sondas.rota_padrao(self.ROTAS.splitlines()[0] + "\n"), (None, False))

    def test_servidores_dns_evitam_o_cache_local(self):
        with tempfile.TemporaryDirectory() as pasta:
            stub, real = os.path.join(pasta, "stub"), os.path.join(pasta, "real")
            with open(stub, "w") as f:
                f.write("nameserver 127.0.0.53\noptions edns0\n")
            with open(real, "w") as f:
                f.write("# upstream\nnameserver 192.168.0.1\nnameserver fe80::1\nnameserver 8.8.8.8\n")
            self.assertEqual(sondas.servidores_dns_do_sistema((real, stub)), ["192.168.0.1", "8.8.8.8"])
            self.assertEqual(sondas.servidores_dns_do_sistema((os.path.join(pasta, "nao-existe"), stub)), ["127.0.0.53"])

    def _servidor_dns(self, rcode):
        """Um servidor DNS de mentira em 127.0.0.1 que responde a tudo com o rcode dado."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        s.settimeout(3)

        def responder():
            try:
                while True:
                    dados, origem = s.recvfrom(512)
                    ident = struct.unpack("!H", dados[:2])[0]
                    s.sendto(struct.pack("!HHHHHH", ident, 0x8180 | rcode, 1, 0, 0, 0) + dados[12:], origem)
            except OSError:
                pass
        threading.Thread(target=responder, daemon=True).start()
        return s

    def test_consulta_dns(self):
        pacote = sondas.montar_consulta("www.google.com", 0x1234)
        self.assertEqual(pacote[12:], b"\x03www\x06google\x03com\x00\x00\x01\x00\x01")
        bom, ruim = self._servidor_dns(0), self._servidor_dns(2)  # 2 = SERVFAIL
        try:
            ok, ms = sondas.consultar_dns("www.google.com", ["127.0.0.1"], 2, porta=bom.getsockname()[1])
            self.assertTrue(ok)
            self.assertGreaterEqual(ms, 1)
            ok, _ = sondas.consultar_dns("www.google.com", ["127.0.0.1"], 2, porta=ruim.getsockname()[1])
            self.assertFalse(ok)
            self.assertIsNone(sondas.codigo_resposta(struct.pack("!HHHHHH", 8, 0x8180, 1, 0, 0, 0), 7))
        finally:
            bom.close()
            ruim.close()

    def test_dns_so_falha_se_os_dois_nomes_falharem(self):
        s = sondas.Sondador(["127.0.0.1"], ["ruim.exemplo", "bom.exemplo"])
        antigo = sondas.consultar_dns
        sondas.consultar_dns = lambda nome, servidores, timeout: (nome.startswith("bom"), 7)
        try:
            self.assertEqual(s._dns(["10.0.0.1"]), (True, 7))
            sondas.consultar_dns = lambda nome, servidores, timeout: (False, 0)
            self.assertEqual(s._dns(["10.0.0.1"]), (False, 0))
        finally:
            sondas.consultar_dns = antigo
            s.fechar()

    def test_tcp_recusado_conta_so_quando_pedido(self):
        livre = socket.socket()
        livre.bind(("127.0.0.1", 0))
        porta = livre.getsockname()[1]
        livre.close()  # ninguém escutando: conexão recusada
        self.assertIsNone(sondas.conectar_tcp("127.0.0.1", porta, 1))
        self.assertIsNotNone(sondas.conectar_tcp("127.0.0.1", porta, 1, recusa_conta=True))


class TesteConfig(unittest.TestCase):
    def test_le_arquivo(self):
        with tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False) as f:
            f.write(config.EXEMPLO_PT.replace("intervalo_segundos = 2", "intervalo_segundos = 5")
                    .replace("# servidor = 192.168.0.10:445", "servidor = 192.168.0.10:445")
                    .replace("# impressora = 192.168.0.50", "impressora = 192.168.0.50\nlixo = nao-e-ip"))
        try:
            c = config.carregar(f.name)
            self.assertEqual(c.intervalo_segundos, 5)
            self.assertEqual(c.alvos, ["1.1.1.1", "8.8.8.8", "9.9.9.9"])
            self.assertEqual(c.internos, {"servidor": ("192.168.0.10", 445), "impressora": ("192.168.0.50", None)})
        finally:
            os.remove(f.name)


class TesteRelatorio(unittest.TestCase):
    def test_demo(self):
        amostras = demo.gerar(date(2026, 9, 26))
        fuso = relatorio.Fuso()
        d = relatorio.calcular(amostras, amostras[0].tempo, amostras[-1].tempo, Opcoes(), fuso)
        self.assertEqual(len(d.quedas), 9)
        self.assertEqual(d.quedas_por_lado[Lado.OPERADORA], 7)
        self.assertEqual(len(d.dias), 7)
        self.assertEqual([i.nome for i in d.internos], ["impressora", "servidor"])
        html = relatorio.gerar_html(d, fuso, ["1.1.1.1", "8.8.8.8", "9.9.9.9"], "teste")
        self.assertIn("9 quedas", html)
        self.assertIn("Rede interna", html)
        self.assertNotIn("<script", html)

    def test_sem_dados(self):
        d = relatorio.calcular([], T0, T0 + timedelta(days=1), Opcoes(), relatorio.Fuso())
        self.assertIn("Sem dados", relatorio.gerar_html(d, relatorio.Fuso(), [], "teste"))

    def test_formatos(self):
        self.assertEqual(relatorio.duracao(timedelta(seconds=45)), "45 s")
        self.assertEqual(relatorio.duracao(timedelta(seconds=432)), "7 min 12 s")
        self.assertEqual(relatorio.duracao(timedelta(minutes=125)), "2 h 05 min")
        self.assertEqual(relatorio.porcentagem(0.99999), "99,99%")
        self.assertEqual(relatorio.porcentagem(1.0), "100,00%")


class TesteBandeja(unittest.TestCase):
    """A lógica da bandeja (sem interface): ler o log aos poucos e decidir quando avisar."""

    def _gravar(self, pasta, amostras, sem_fim_de_linha=False):
        dia = amostras[0].tempo.astimezone().date()
        caminho = os.path.join(pasta, f"samples-{dia.isoformat()}.csv")
        with open(caminho, "a", encoding="utf-8") as f:
            texto = "".join(formatar(s) + "\n" for s in amostras)
            f.write(texto[:-1] if sem_fim_de_linha else texto)
        return dia

    def test_leitor_le_so_o_que_e_novo_e_espera_linha_completa(self):
        from outagelog.bandeja import LeitorIncremental
        with tempfile.TemporaryDirectory() as pasta:
            amostras = padrao("....", datetime.now(timezone.utc) - timedelta(seconds=60))
            dia = self._gravar(pasta, amostras[:2])
            leitor = LeitorIncremental(pasta)
            self.assertEqual(len(leitor.novas(dia)), 2)
            self.assertEqual(leitor.novas(dia), [])
            self._gravar(pasta, amostras[2:], sem_fim_de_linha=True)
            self.assertEqual(len(leitor.novas(dia)), 1)  # a última linha ainda não terminou
            with open(os.path.join(pasta, f"samples-{dia.isoformat()}.csv"), "a") as f:
                f.write("\n")
            self.assertEqual(len(leitor.novas(dia)), 1)

    def test_avisa_queda_e_volta_mas_nao_historico(self):
        from outagelog.bandeja import Observador
        avisos = []
        with tempfile.TemporaryDirectory() as pasta:
            inicio = datetime.now(timezone.utc) - timedelta(minutes=5)
            relogio = [inicio]
            hist = padrao("....PPPP....", inicio)  # queda antiga: não deve avisar
            self._gravar(pasta, hist)
            obs = Observador(pasta, SEM_AQUECIMENTO, lambda t, x, c: avisos.append((t, c)), agora=lambda: relogio[0])
            relogio[0] = hist[-1].tempo
            obs.carregar_historico()
            obs.atualizar()
            self.assertEqual(avisos, [])
            self.assertEqual(obs.cor, "verde")
            self.assertEqual(obs.quedas_hoje(), 1)

            novas = padrao("PPP", hist[-1].tempo + timedelta(seconds=2))
            self._gravar(pasta, novas)
            relogio[0] = novas[-1].tempo
            obs.atualizar()
            self.assertEqual(obs.cor, "vermelho")
            self.assertTrue(avisos[-1][0].startswith("Internet caiu"))
            self.assertIn("fora há", obs.resumo())

            volta = padrao("...", novas[-1].tempo + timedelta(seconds=2))
            self._gravar(pasta, volta)
            relogio[0] = volta[-1].tempo
            obs.atualizar()
            self.assertEqual(avisos[-1][0], "Internet voltou")
            self.assertEqual(obs.cor, "verde")
            self.assertEqual(len(avisos), 2)

    def test_avisa_uma_vez_quando_o_monitoramento_para(self):
        from outagelog.bandeja import Observador
        avisos = []
        with tempfile.TemporaryDirectory() as pasta:
            amostras = padrao("....", datetime.now(timezone.utc) - timedelta(minutes=5))
            self._gravar(pasta, amostras)
            relogio = [amostras[-1].tempo]
            obs = Observador(pasta, SEM_AQUECIMENTO, lambda t, x, c: avisos.append(t), agora=lambda: relogio[0])
            obs.carregar_historico()
            obs.atualizar()
            self.assertEqual(avisos, [])
            relogio[0] += timedelta(minutes=1)
            obs.atualizar()
            obs.atualizar()
            self.assertEqual(avisos, ["Monitoramento parado"])
            self.assertEqual(obs.cor, "cinza")

    def test_limite_de_avisos(self):
        from outagelog.bandeja import Observador
        avisos = []
        obs = Observador("/nao-existe", SEM_AQUECIMENTO, lambda t, x, c: avisos.append(t))
        for _ in range(10):
            obs._aviso("x", "y", "vermelho")
        self.assertEqual(len(avisos), 4)


class TesteIngles(unittest.TestCase):
    def setUp(self):
        idioma.definir("en")

    def tearDown(self):
        idioma.definir("pt")

    def test_relatorio_em_ingles(self):
        amostras = demo.gerar(date(2026, 9, 26))
        fuso = relatorio.Fuso()
        d = relatorio.calcular(amostras, amostras[0].tempo, amostras[-1].tempo, Opcoes(), fuso)
        html = relatorio.gerar_html(d, fuso, ["1.1.1.1"], "test")
        for texto in ("9 outages", "Local network", "Provider side", "Internet down, router OK", 'lang="en"'):
            self.assertIn(texto, html)
        for texto in ("quedas", "Rede interna", "operadora"):
            self.assertNotIn(texto, html)
        self.assertEqual(relatorio.porcentagem(0.5), "50.00%")
        self.assertEqual([i.nome for i in d.internos], ["fileserver", "printer"])

    def test_config_em_ingles(self):
        with tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False) as f:
            f.write(config.EXEMPLO_EN.replace("interval_seconds = 2", "interval_seconds = 7")
                    .replace("language = auto", "language = pt")
                    .replace("# printer = 192.168.0.50", "printer = 192.168.0.50   # inline comment"))
        try:
            c = config.carregar(f.name)
            self.assertEqual((c.intervalo_segundos, c.idioma), (7, "pt"))
            self.assertEqual(c.internos, {"printer": ("192.168.0.50", None)})
        finally:
            os.remove(f.name)

    def test_comandos_em_ingles(self):
        from outagelog import cli
        args = cli.montar_parser().parse_args(["report", "3", "--out", "x.html", "--no-open"])
        self.assertEqual((args.comando, args.dias, args.saida, args.nao_abrir), ("report", 3, "x.html", True))
        self.assertIs(cli.COMANDOS["self-test"], cli.COMANDOS["autoteste"])

    def test_deteccao_pelo_sistema(self):
        antigo = {k: os.environ.pop(k, None) for k in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")}
        try:
            os.environ["LANG"] = "pt_BR.UTF-8"
            self.assertEqual(idioma.detectar("auto"), "pt")
            os.environ["LANG"] = "de_DE.UTF-8"
            self.assertEqual(idioma.detectar("auto"), "en")
            self.assertEqual(idioma.detectar("pt"), "pt")
        finally:
            for k, v in antigo.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
