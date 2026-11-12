"""Comando popular_dados_teste: só banco local, idempotente e sem alterar dados existentes."""
from io import StringIO
from unittest import mock

from django.contrib.sessions.models import Session
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import override_settings

from apps.agenda.models import Compromisso, ParticipanteCompromisso
from apps.clientes.models import Cliente
from apps.core.management.commands import popular_dados_teste as cmd
from apps.core.tests import fabrica as f
from apps.processos.models import Processo


def rodar(*args):
    saida = StringIO()
    call_command("popular_dados_teste", *args, stdout=saida)
    return saida.getvalue()


class PopularDadosTesteTests(f.Cenario):
    def test_cria_clientes_processos_e_compromissos_sem_duplicar(self):
        antes = (Cliente.objects.count(), Processo.objects.count(), Compromisso.objects.count())
        rodar()
        self.assertIn("Criados — clientes: 0, processos: 0, compromissos: 0, participações: 0", rodar())
        self.assertEqual(Cliente.objects.count(), antes[0] + 50)
        self.assertEqual(Processo.objects.count(), antes[1] + 100)
        self.assertEqual(Compromisso.objects.count(), antes[2] + 300)
        self.assertEqual(Compromisso.objects.filter(descricao=cmd.MARCADOR).count(), 300)

    def test_recria_somente_o_que_falta(self):
        rodar()
        Processo.objects.filter(numero=cmd.numero_processo(7)).update(numero="manual-7")
        Compromisso.objects.filter(titulo=cmd.titulo_compromisso(3, 2)).update(titulo="manual")
        saida = rodar()
        # O processo 7 é recriado; os compromissos dele continuam no processo renomeado
        # (não são duplicados). Só o compromisso 3.2, renomeado, é recriado.
        self.assertIn("Criados — clientes: 0, processos: 1, compromissos: 1", saida)

    def test_nao_altera_registros_existentes(self):
        comp = f.compromisso(self.adv, self.proc, participantes=[self.ast])
        antes = [m.objects.values().get(pk=pk) for m, pk in
                 ((Cliente, self.cli.pk), (Processo, self.proc.pk), (type(self.adv), self.adv.pk),
                  (type(self.ast), self.ast.pk), (Compromisso, comp.pk))]
        rodar()
        depois = [m.objects.values().get(pk=pk) for m, pk in
                  ((Cliente, self.cli.pk), (Processo, self.proc.pk), (type(self.adv), self.adv.pk),
                   (type(self.ast), self.ast.pk), (Compromisso, comp.pk))]
        self.assertEqual(antes, depois)
        self.assertEqual(list(comp.participantes.values_list("usuario_id", flat=True)), [self.ast.pk])

    def test_agenda_variada_e_responsavel_do_processo(self):
        rodar()
        teste = Compromisso.objects.filter(descricao=cmd.MARCADOR)
        self.assertEqual(set(teste.values_list("tipo", flat=True)), {"compromisso", "tarefa", "prazo"})
        self.assertEqual(set(teste.values_list("situacao", flat=True)), {"pendente", "concluido", "cancelado"})
        destaques = {c.destaque() for c in teste}
        self.assertTrue({"vencido", "proximo", None} <= destaques)
        for c in teste.select_related("processo"):
            self.assertEqual(c.responsavel_id, c.processo.responsavel_id)

    def test_ast_participa_sem_ganhar_acesso_ao_processo(self):
        from apps.core.acesso import compromissos_visiveis, processos_visiveis

        rodar()
        participa = ParticipanteCompromisso.objects.filter(usuario=self.ast, compromisso__descricao=cmd.MARCADOR)
        self.assertEqual(participa.count(), 30)
        self.assertEqual(compromissos_visiveis(self.ast).filter(descricao=cmd.MARCADOR).count(), 30)
        self.assertFalse(processos_visiveis(self.ast).filter(descricao=cmd.MARCADOR).exists())

    def test_responsaveis_sao_adm_ou_adv(self):
        rodar()
        perfis = set(Processo.objects.filter(descricao=cmd.MARCADOR).values_list("responsavel__perfil", flat=True))
        self.assertEqual(perfis, {"ADM", "ADV"})

    def test_documentos_ficticios_nao_sao_validos(self):
        for n in range(1, 51):
            cpf, cnpj = cmd.cpf_ficticio(n), cmd.cnpj_ficticio(n)
            self.assertEqual((len(cpf), len(cnpj)), (11, 14))
            self.assertNotEqual(cpf[9], cmd._dv(cpf[:9], range(10, 1, -1)))
            self.assertNotEqual(cnpj[12], cmd._dv(cnpj[:12], (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)))

    def test_recusa_supabase(self):
        with override_settings(BANCO_ALVO="supabase"), self.assertRaisesMessage(CommandError, "DB_ALVO=local"):
            rodar()
        self.assertFalse(Cliente.objects.filter(observacoes=cmd.MARCADOR).exists())

    def test_recusa_host_do_supabase(self):
        with mock.patch.dict(connection.settings_dict, {"HOST": "aws-0.pooler.supabase.com"}):
            with self.assertRaisesMessage(CommandError, "Supabase"):
                cmd.verificar_banco_local()

    def test_recusa_render(self):
        with mock.patch.dict("os.environ", {"RENDER": "true"}), self.assertRaisesMessage(CommandError, "Render"):
            cmd.verificar_banco_local()

    def test_http_so_aceita_endereco_local(self):
        for url in ("https://jusgestor.onrender.com", "http://exemplo.test:8000", "ftp://127.0.0.1"):
            with self.subTest(url=url), self.assertRaisesMessage(CommandError, "endereços locais"):
                cmd.verificar_url_local(url)
        self.assertEqual(cmd.verificar_url_local("http://127.0.0.1:8000/"), "http://127.0.0.1:8000")

    def test_medicao_sem_problemas_e_sem_gravar_sessao(self):
        ultimo_login = type(self.adm).objects.get(pk=self.adm.pk).last_login
        saida = rodar("--medir", "--repeticoes", "1")
        self.assertIn("Nenhum problema", saida)
        self.assertIn("Agenda — todas, última página", saida)
        self.assertIn("Agenda — detalhe do compromisso", saida)
        self.assertFalse(Session.objects.exists())
        self.assertEqual(type(self.adm).objects.get(pk=self.adm.pk).last_login, ultimo_login)

    def test_http_apaga_a_sessao_temporaria_mesmo_com_falha(self):
        # Porta sem servidor: todas as requisições falham, mas a sessão é removida.
        saida = rodar("--http", "http://127.0.0.1:9", "--repeticoes", "1")
        self.assertIn("Problemas encontrados", saida)
        self.assertFalse(Session.objects.exists())

    def test_detecta_consultas_repetidas(self):
        sqls = [f'SELECT * FROM "cliente" WHERE "id" = {i}' for i in range(5)]
        self.assertEqual(cmd.Command.consultas_repetidas(sqls), 5)
        self.assertEqual(cmd.Command.consultas_repetidas(sqls[:2]), 0)
        somas = [f"SELECT SUM(valor) FROM lancamento WHERE situacao = '{s}' AND tipo = '{t}'"
                 for s in ("quitado", "pendente") for t in ("receita", "despesa")]
        self.assertEqual(cmd.Command.consultas_repetidas(somas), 0)
