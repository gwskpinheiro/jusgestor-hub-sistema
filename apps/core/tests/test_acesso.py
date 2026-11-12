"""Autorização por registro (RN07) — matriz de visibilidade."""
from apps.core import acesso
from apps.core.tests import fabrica as f
from apps.documentos.models import Documento


class VisibilidadeTests(f.Cenario):
    def ids(self, qs):
        return set(qs.values_list("pk", flat=True))

    def test_adm_ve_todos_os_registros(self):
        self.assertEqual(self.ids(acesso.clientes_visiveis(self.adm)), {self.cli.pk, self.cli2.pk})
        self.assertEqual(self.ids(acesso.processos_visiveis(self.adm)), {self.proc.pk, self.proc2.pk})

    def test_adv_ve_processos_sob_sua_responsabilidade(self):
        self.assertEqual(self.ids(acesso.processos_visiveis(self.adv)), {self.proc.pk})

    def test_adv_ve_processo_explicitamente_autorizado(self):
        f.autorizar_processo(self.adv, self.proc2)
        self.assertEqual(self.ids(acesso.processos_visiveis(self.adv)), {self.proc.pk, self.proc2.pk})

    def test_ast_sem_acessos_nao_ve_nada(self):
        self.assertFalse(acesso.clientes_visiveis(self.ast).exists())
        self.assertFalse(acesso.processos_visiveis(self.ast).exists())

    def test_acesso_ao_cliente_nao_libera_processos(self):
        f.autorizar_cliente(self.ast, self.cli)
        self.assertEqual(self.ids(acesso.clientes_visiveis(self.ast)), {self.cli.pk})
        self.assertFalse(acesso.processos_visiveis(self.ast).exists())

    def test_ast_ve_processo_autorizado(self):
        f.autorizar_processo(self.ast, self.proc)
        self.assertEqual(self.ids(acesso.processos_visiveis(self.ast)), {self.proc.pk})

    def test_usuario_inativo_nao_ve_nada(self):
        self.adv.ativo = False
        self.assertFalse(acesso.processos_visiveis(self.adv).exists())
        self.adm.ativo = False
        self.assertFalse(acesso.clientes_visiveis(self.adm).exists())

    def test_ast_nao_edita_processo_e_adv_autorizado_edita(self):
        f.autorizar_processo(self.ast, self.proc)
        self.assertFalse(acesso.pode_editar_processo(self.ast, self.proc))
        self.assertTrue(acesso.pode_editar_processo(self.adv, self.proc))
        self.assertFalse(acesso.pode_editar_processo(self.adv, self.proc2))

    def test_processo_arquivado_nao_e_editavel(self):
        self.proc.arquivado = True
        self.assertFalse(acesso.pode_editar_processo(self.adm, self.proc))

    def test_participar_de_compromisso_nao_libera_processo(self):
        comp = f.compromisso(self.adv, self.proc, participantes=[self.ast])
        self.assertIn(comp.pk, self.ids(acesso.compromissos_visiveis(self.ast)))
        self.assertNotIn(self.proc.pk, self.ids(acesso.processos_visiveis(self.ast)))

    def test_compromisso_visivel_por_acesso_ao_processo(self):
        comp = f.compromisso(self.adv2, self.proc)  # adv é responsável pelo processo
        self.assertIn(comp.pk, self.ids(acesso.compromissos_visiveis(self.adv)))
        self.assertNotIn(comp.pk, self.ids(acesso.compromissos_visiveis(self.ast)))

    def test_documento_de_processo_exige_acesso_ao_processo(self):
        doc_proc = Documento.objects.create(titulo="Doc do processo", processo=self.proc, cliente=self.cli)
        doc_cli = Documento.objects.create(titulo="Doc do cliente", cliente=self.cli)
        f.autorizar_cliente(self.ast, self.cli)
        self.assertEqual(self.ids(acesso.documentos_visiveis(self.ast)), {doc_cli.pk})
        f.autorizar_processo(self.ast, self.proc)
        self.assertEqual(self.ids(acesso.documentos_visiveis(self.ast)), {doc_cli.pk, doc_proc.pk})

    def test_horas_adv_apenas_proprias_adm_equipe_ast_nenhuma(self):
        h1 = f.registro_hora(self.adv, self.proc)
        h2 = f.registro_hora(self.adv2, self.proc2)
        self.assertEqual(self.ids(acesso.registros_hora_visiveis(self.adv)), {h1.pk})
        self.assertEqual(self.ids(acesso.registros_hora_visiveis(self.adm)), {h1.pk, h2.pk})
        self.assertFalse(acesso.registros_hora_visiveis(self.ast).exists())
