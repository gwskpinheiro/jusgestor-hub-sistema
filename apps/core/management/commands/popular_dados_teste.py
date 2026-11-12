"""Popula o banco LOCAL com dados fictícios para o ensaio de desempenho (RNF04).

RNF04 (artigo, Tabela 4): "Concluir consultas de clientes, processos e agenda
em até três segundos no ensaio local com um usuário, 50 clientes e 100
processos."

Uso:
    docker compose run --rm web python manage.py popular_dados_teste
    docker compose exec web python manage.py popular_dados_teste --medir
    docker compose exec web python manage.py popular_dados_teste --medir --http

Cria 50 clientes, 100 processos (2 por cliente) e 300 compromissos (3 por
processo). Pode ser executado novamente sem duplicar nada:
- clientes: e-mail ``cliente-teste-NN@exemplo.test``;
- processos: número ``NNNNNNN-00.2026.0.00.0000`` (segmento de justiça 0,
  inexistente no padrão CNJ);
- compromissos: título com o código ``[T-NNN.K]`` + descrição-marcador.
Registros que já existem não são alterados.

Dados fictícios (RNF08):
- nomes genéricos ("Pessoa Fictícia Teste NN", "Empresa Fictícia Teste NN Ltda");
- CPF/CNPJ com dígitos verificadores propositalmente inválidos;
- telefone com DDD 00 e e-mail no domínio reservado ``exemplo.test``.

Processos e compromissos são distribuídos entre os usuários ADM e ADV ativos
já existentes (somente referência; os usuários não são alterados). O primeiro
AST ativo, se houver, participa de 1 a cada 10 compromissos novos (participar
não dá acesso ao processo). Nenhuma autorização (acesso_cliente /
acesso_processo) é criada.

``--medir`` chama as views diretamente (consulta + template), sem login, sem
gravar sessão e sem alterar ``last_login``.
``--http`` mede também a resposta HTTP completa do servidor em execução
(``docker compose exec``), como ADM, usando uma sessão temporária que é
apagada ao final. Só aceita endereços locais.

O comando recusa qualquer banco que não seja o PostgreSQL local do Docker.
"""
import os
import re
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse
from django.utils import timezone

from apps.agenda.models import Compromisso, ParticipanteCompromisso, SituacaoCompromisso, TipoCompromisso
from apps.clientes.models import Cliente
from apps.processos.models import Processo, SituacaoProcesso
from apps.usuarios.models import Perfil, Usuario
from config import ambiente
from config.banco import ALVO_LOCAL, e_host_supabase

TOTAL_CLIENTES = 50
PROCESSOS_POR_CLIENTE = 2
COMPROMISSOS_POR_PROCESSO = 3
CLIENTES_ARQUIVADOS = (49, 50)  # e os processos deles
MARCADOR = "Dado fictício gerado pelo comando popular_dados_teste (RNF04/RNF08)."
TITULOS = (
    "Ação de cobrança", "Revisão contratual", "Reclamação trabalhista",
    "Inventário", "Ação de alimentos", "Execução de título extrajudicial",
)
# (tipo, título) dos 3 compromissos de cada processo.
COMPROMISSOS = (
    (TipoCompromisso.COMPROMISSO, "Audiência"),
    (TipoCompromisso.PRAZO, "Prazo de manifestação"),
    (TipoCompromisso.TAREFA, "Revisar peças"),
)
LIMITE_RNF04 = 3.0  # segundos
HOSTS_HTTP = ("127.0.0.1", "localhost")
# Chave arbitrária do lock consultivo que impede duas cargas simultâneas.
CHAVE_LOCK = 724_031_002


def verificar_banco_local():
    """Interrompe se o banco configurado não for o PostgreSQL local."""
    host = connection.settings_dict.get("HOST", "")
    if settings.BANCO_ALVO != ALVO_LOCAL:
        raise CommandError(f"DB_ALVO={settings.BANCO_ALVO}. Este comando só roda com DB_ALVO=local.")
    if e_host_supabase(host):
        raise CommandError("O host do banco pertence ao Supabase. Comando recusado.")
    if ambiente.no_render(os.environ):
        raise CommandError("Ambiente Render detectado. Comando recusado.")
    if connection.vendor != "postgresql":
        raise CommandError("O banco local deve ser PostgreSQL.")
    return host


def verificar_url_local(url):
    partes = urlsplit(url)
    if partes.scheme != "http" or partes.hostname not in HOSTS_HTTP:
        raise CommandError(f"--http só aceita endereços locais ({', '.join(HOSTS_HTTP)}).")
    return url.rstrip("/")


# --- Dados fictícios -------------------------------------------------------

def _dv(digitos, pesos):
    resto = sum(int(d) * p for d, p in zip(digitos, pesos)) % 11
    return "0" if resto < 2 else str(11 - resto)


def _invalidar(base, dv1, dv2):
    """Troca o 1º dígito verificador por outro: o número nunca é um documento válido."""
    return base + str((int(dv1) + 1) % 10) + dv2


def cpf_ficticio(n):
    base = f"9{n:08d}"
    dv1 = _dv(base, range(10, 1, -1))
    dv2 = _dv(base + dv1, range(11, 1, -1))
    return _invalidar(base, dv1, dv2)


def cnpj_ficticio(n):
    base = f"9{n:07d}0001"
    dv1 = _dv(base, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    dv2 = _dv(base + dv1, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return _invalidar(base, dv1, dv2)


def email_cliente(n):
    return f"cliente-teste-{n:02d}@exemplo.test"


def numero_processo(n):
    return f"{n:07d}-00.2026.0.00.0000"


def titulo_compromisso(i, k):
    return f"{COMPROMISSOS[k - 1][1]} — fictício [T-{i:03d}.{k}]"


def dados_cliente(n, agora):
    pj = n % 2 == 0
    return Cliente(
        nome=f"Empresa Fictícia Teste {n:02d} Ltda" if pj else f"Pessoa Fictícia Teste {n:02d}",
        cpf_cnpj=cnpj_ficticio(n) if pj else cpf_ficticio(n),
        email=email_cliente(n),
        telefone=f"(00) 0000-{n:04d}",
        endereco=f"Rua Fictícia, nº {n} — Cidade Exemplo",
        observacoes=MARCADOR,
        arquivado=n in CLIENTES_ARQUIVADOS,
        criado_em=agora - timedelta(days=2 * (TOTAL_CLIENTES - n) + 1),
    )


def dados_compromisso(i, k, processo, base):
    """Datas de ~30 dias atrás a ~70 dias à frente, com vencidos e próximas 24 h.

    ``base`` é o início da hora atual, para que as datas fiquem em horas cheias.
    """
    tipo = COMPROMISSOS[k - 1][0]
    if k == 1:    # audiências: uma por dia, de -29 a +70 dias, às 14h
        inicio = (base + timedelta(days=i - 30)).replace(hour=14)
    elif k == 2:  # prazos espalhados em -20 a +69 dias, às 18h
        inicio = (base + timedelta(days=(i * 7) % 90 - 20)).replace(hour=18)
    else:         # tarefas concentradas em -12 a +35 horas (vencidos e próximas 24 h)
        inicio = base + timedelta(hours=i % 48 - 12)
    n = (i - 1) * COMPROMISSOS_POR_PROCESSO + k
    if n % 10 == 0:
        situacao = SituacaoCompromisso.CANCELADO
    elif n % 4 == 0:
        situacao = SituacaoCompromisso.CONCLUIDO
    else:
        situacao = SituacaoCompromisso.PENDENTE
    return Compromisso(
        responsavel_id=processo.responsavel_id,
        processo=processo,
        titulo=titulo_compromisso(i, k),
        descricao=MARCADOR,
        tipo=tipo,
        inicio=inicio,
        fim=inicio + timedelta(hours=1) if tipo == TipoCompromisso.COMPROMISSO else None,
        situacao=situacao,
    )


# --- Comando ---------------------------------------------------------------

class Command(BaseCommand):
    help = ("Popula o banco LOCAL com 50 clientes, 100 processos e 300 compromissos fictícios "
            "(sem duplicar) e mede as consultas do RNF04.")

    def add_arguments(self, parser):
        parser.add_argument("--medir", action="store_true",
                            help="Mede tempo e consultas de clientes, processos e agenda.")
        parser.add_argument("--repeticoes", type=int, default=5,
                            help="Repetições por cenário na medição (padrão: 5).")
        parser.add_argument("--http", nargs="?", const="http://127.0.0.1:8000", default=None, metavar="URL",
                            help="Mede também a resposta HTTP do servidor local em execução "
                                 "(padrão: http://127.0.0.1:8000).")

    def handle(self, *args, medir=False, repeticoes=5, http=None, **opcoes):
        host = verificar_banco_local()
        base_http = verificar_url_local(http) if http else None
        cfg = connection.settings_dict
        self.stdout.write(f"Banco: DB_ALVO={settings.BANCO_ALVO}, host={host}, nome={cfg['NAME']}")

        criados = self.popular()
        self.stdout.write(self.style.SUCCESS(
            "Criados — clientes: {}, processos: {}, compromissos: {}, participações: {} "
            "(já existentes foram mantidos sem alteração).".format(*criados)
        ))
        self.stdout.write(
            f"Totais no banco: {Cliente.objects.count()} clientes, {Processo.objects.count()} processos, "
            f"{Compromisso.objects.count()} compromissos."
        )
        repeticoes = max(1, repeticoes)
        problemas = []
        if medir:
            problemas += self.medir(repeticoes)
        if base_http:
            problemas += self.medir_http(base_http, repeticoes)
        if medir or base_http:
            self.stdout.write("")
            if problemas:
                self.stdout.write(self.style.WARNING("Problemas encontrados:"))
                for p in problemas:
                    self.stdout.write(f"  - {p}")
            else:
                self.stdout.write(self.style.SUCCESS(
                    "Nenhum problema: respostas 200, dentro do limite do RNF04 e sem consultas repetidas (N+1)."
                ))

    @transaction.atomic
    def popular(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [CHAVE_LOCK])

        responsaveis = list(
            Usuario.objects.filter(ativo=True, perfil__in=(Perfil.ADM, Perfil.ADV)).order_by("id")
        )
        if not responsaveis:
            raise CommandError("Nenhum usuário ADM ou ADV ativo para ser responsável pelos processos.")

        agora = timezone.now()
        emails = [email_cliente(n) for n in range(1, TOTAL_CLIENTES + 1)]
        existentes = {c.email for c in Cliente.objects.filter(email__in=emails, observacoes=MARCADOR)}
        novos_clientes = [dados_cliente(n, agora) for n in range(1, TOTAL_CLIENTES + 1)
                          if email_cliente(n) not in existentes]
        Cliente.objects.bulk_create(novos_clientes)
        clientes = {c.email: c for c in Cliente.objects.filter(email__in=emails, observacoes=MARCADOR)}

        total = TOTAL_CLIENTES * PROCESSOS_POR_CLIENTE
        numeros = [numero_processo(i) for i in range(1, total + 1)]
        # Qualquer processo com esses números (mesmo cadastrado à mão) é preservado.
        ja_usados = set(Processo.objects.filter(numero__in=numeros).values_list("numero", flat=True))
        novos_processos = []
        for i in range(1, total + 1):
            if numero_processo(i) in ja_usados:
                continue
            n_cliente = (i - 1) // PROCESSOS_POR_CLIENTE + 1
            novos_processos.append(Processo(
                cliente=clientes[email_cliente(n_cliente)],
                responsavel=responsaveis[(i - 1) % len(responsaveis)],
                numero=numero_processo(i),
                titulo=f"{TITULOS[(i - 1) % len(TITULOS)]} — fictício {i:03d}",
                descricao=MARCADOR,
                situacao=SituacaoProcesso.ENCERRADO if i % 5 == 0 else SituacaoProcesso.ATIVO,
                arquivado=n_cliente in CLIENTES_ARQUIVADOS,
                criado_em=agora - timedelta(days=total - i, hours=i % 24),
            ))
        Processo.objects.bulk_create(novos_processos)

        novos_comp, participacoes = self.popular_agenda(numeros, agora)
        return len(novos_clientes), len(novos_processos), novos_comp, participacoes

    def popular_agenda(self, numeros, agora):
        # Somente processos de teste ainda marcados (não toca em processos cadastrados à mão).
        processos = {p.numero: p for p in Processo.objects.filter(numero__in=numeros, descricao=MARCADOR)}
        ja_existem = set(Compromisso.objects.filter(descricao=MARCADOR).values_list("titulo", flat=True))
        # Hora local (America/Sao_Paulo), para que "14h" e "18h" sejam horários locais.
        base = timezone.localtime(agora).replace(minute=0, second=0, microsecond=0)
        novos = []
        for i, numero in enumerate(numeros, start=1):
            processo = processos.get(numero)
            if processo is None:
                continue
            for k in range(1, COMPROMISSOS_POR_PROCESSO + 1):
                if titulo_compromisso(i, k) not in ja_existem:
                    novos.append(dados_compromisso(i, k, processo, base))
        Compromisso.objects.bulk_create(novos)

        assistente = Usuario.objects.filter(ativo=True, perfil=Perfil.AST).order_by("id").first()
        participacoes = []
        if assistente:
            participacoes = [ParticipanteCompromisso(compromisso=c, usuario=assistente)
                             for n, c in enumerate(novos, start=1) if n % 10 == 0]
            ParticipanteCompromisso.objects.bulk_create(participacoes, ignore_conflicts=True)
        return len(novos), len(participacoes)

    # --- Medição -----------------------------------------------------------

    def cenarios(self, usuario):
        from apps.core.acesso import compromissos_visiveis

        c, p, a = reverse("clientes:lista"), reverse("processos:lista"), reverse("agenda:lista")
        hoje = timezone.localdate()
        lista = [
            ("Clientes — página 1", c, {}),
            ("Clientes — página 2", c, {"pagina": "2"}),
            ("Clientes — busca 'Fictícia'", c, {"q": "Fictícia"}),
            ("Clientes — busca por CPF", c, {"q": cpf_ficticio(1)[:6]}),
            ("Clientes — arquivados", c, {"arquivados": "1"}),
            ("Processos — página 1", p, {}),
            ("Processos — página 4", p, {"pagina": "4"}),
            ("Processos — encerrados", p, {"situacao": "encerrado"}),
            ("Processos — busca por cliente", p, {"q": "Empresa Fictícia"}),
            ("Processos — arquivados", p, {"arquivados": "1"}),
            ("Agenda — padrão (pendentes)", a, {}),
            ("Agenda — todas, página 1", a, {"situacao": "todas"}),
            ("Agenda — todas, última página", a, {"situacao": "todas", "pagina": "99"}),
            ("Agenda — concluídos", a, {"situacao": "concluido"}),
            ("Agenda — tipo prazo", a, {"tipo": "prazo"}),
            ("Agenda — próximos 30 dias", a, {"situacao": "todas", "de": hoje.isoformat(),
                                              "ate": (hoje + timedelta(days=30)).isoformat()}),
            ("Agenda — sou o responsável", a, {"meus": "1"}),
        ]
        exemplo = compromissos_visiveis(usuario).filter(descricao=MARCADOR).order_by("pk").first()
        if exemplo:
            lista.append(("Agenda — detalhe do compromisso", exemplo.get_absolute_url(), {}))
        lista.append(("Painel (destaques da agenda)", reverse("core:painel"), {}))
        return lista

    def executar(self, usuario, url, params):
        request = RequestFactory().get(url, params)
        request.user = usuario
        request.session = SessionStore()  # nunca é gravada
        with CaptureQueriesContext(connection) as consultas:
            inicio = time.perf_counter()
            resposta = resolve(url).func(request, **resolve(url).kwargs)
            duracao = time.perf_counter() - inicio
        return resposta, duracao, [q["sql"] for q in consultas.captured_queries]

    @staticmethod
    def linhas(conteudo):
        """Linhas da tabela, sem o cabeçalho e sem a linha "Nenhum ... encontrado"."""
        if b"<table" not in conteudo:
            return "—"
        return conteudo.count(b"<tr>") - 1 - (b'class="vazio"' in conteudo)

    def medir(self, repeticoes):
        usuarios = [u for perfil in (Perfil.ADM, Perfil.ADV, Perfil.AST)
                    if (u := Usuario.objects.filter(ativo=True, perfil=perfil).order_by("id").first())]
        self.stdout.write("")
        self.stdout.write(f"Medição no servidor (view: consultas + template), {repeticoes} repetições "
                          f"após 1 aquecimento. Limite RNF04: {LIMITE_RNF04:.0f} s.")
        problemas = []
        for usuario in usuarios:
            self.stdout.write("")
            self.stdout.write(f"Perfil {usuario.perfil} (usuário id {usuario.pk})")
            self.stdout.write(f"  {'Cenário':<36}{'linhas':>7}{'mediana':>11}{'máximo':>10}{'consultas':>11}")
            for nome, url, params in self.cenarios(usuario):
                self.executar(usuario, url, params)  # aquecimento
                tempos = []
                for _ in range(repeticoes):
                    resposta, duracao, sqls = self.executar(usuario, url, params)
                    tempos.append(duracao)
                if resposta.status_code != 200:
                    problemas.append(f"{usuario.perfil} / {nome}: HTTP {resposta.status_code}")
                mediana, maximo = statistics.median(tempos), max(tempos)
                self.stdout.write(f"  {nome:<36}{self.linhas(resposta.content):>7}{mediana * 1000:>9.1f}ms"
                                  f"{maximo * 1000:>8.1f}ms{len(sqls):>11}")
                if maximo > LIMITE_RNF04:
                    problemas.append(f"{usuario.perfil} / {nome}: {maximo:.2f} s (acima de {LIMITE_RNF04:.0f} s)")
                repetidas = self.consultas_repetidas(sqls)
                if repetidas:
                    problemas.append(f"{usuario.perfil} / {nome}: consulta repetida {repetidas} vezes (possível N+1)")
        return problemas

    def medir_http(self, base, repeticoes):
        """Resposta HTTP completa (servidor + rede local), como um único usuário ADM."""
        usuario = Usuario.objects.filter(ativo=True, perfil=Perfil.ADM).order_by("id").first()
        if usuario is None:
            return ["--http: nenhum ADM ativo para a medição."]
        if usuario.trocar_senha:
            return ["--http: o ADM ainda precisa trocar a senha temporária; medição HTTP não realizada."]

        self.stdout.write("")
        self.stdout.write(f"Medição HTTP em {base} como ADM (usuário id {usuario.pk}), {repeticoes} repetições "
                          f"após 1 aquecimento. Tempo até receber a resposta inteira.")
        self.stdout.write(f"  {'Cenário':<36}{'status':>7}{'mediana':>11}{'máximo':>10}{'KiB':>8}")
        sessao = SessionStore()
        sessao[SESSION_KEY] = str(usuario.pk)
        sessao[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
        sessao[HASH_SESSION_KEY] = usuario.get_session_auth_hash()
        sessao.create()
        abridor = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        problemas = []
        try:
            for nome, url, params in self.cenarios(usuario):
                endereco = base + url + ("?" + urlencode(params) if params else "")
                pedido = urllib.request.Request(endereco, headers={
                    "Cookie": f"{settings.SESSION_COOKIE_NAME}={sessao.session_key}"})
                tempos, status, tamanho = [], None, 0
                try:
                    for n in range(repeticoes + 1):
                        inicio = time.perf_counter()
                        with abridor.open(pedido, timeout=30) as resposta:
                            corpo = resposta.read()
                            status, final = resposta.status, resposta.geturl()
                        if n:  # a primeira é aquecimento
                            tempos.append(time.perf_counter() - inicio)
                    tamanho = len(corpo)
                except (urllib.error.URLError, OSError) as erro:
                    problemas.append(f"HTTP / {nome}: {erro}")
                    self.stdout.write(f"  {nome:<36}{'erro':>7}")
                    continue
                if final != endereco:
                    problemas.append(f"HTTP / {nome}: redirecionado para {urlsplit(final).path}")
                mediana, maximo = statistics.median(tempos), max(tempos)
                self.stdout.write(f"  {nome:<36}{status:>7}{mediana * 1000:>9.1f}ms{maximo * 1000:>8.1f}ms"
                                  f"{tamanho / 1024:>8.1f}")
                if maximo > LIMITE_RNF04:
                    problemas.append(f"HTTP / {nome}: {maximo:.2f} s (acima de {LIMITE_RNF04:.0f} s)")
        finally:
            sessao.delete()  # a sessão temporária não permanece no banco
        return problemas

    @staticmethod
    def consultas_repetidas(sqls, limite=3):
        """Maior número de repetições de uma mesma consulta, se ≥ limite.

        Ignora apenas os números (ids), que é o que muda num N+1 (uma consulta
        por linha). Consultas com filtros de texto diferentes (ex.: as somas
        fixas de receitas/despesas do painel) não contam como repetição.
        """
        normalizadas = Counter(re.sub(r"\b\d+\b", "?", sql) for sql in sqls)
        maior = max(normalizadas.values(), default=0)
        return maior if maior >= limite else 0
