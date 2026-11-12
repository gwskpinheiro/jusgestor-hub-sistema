"""RF02 — processos (RN01, RN07, RN08)."""
from django.urls import reverse

from apps.core.tests import fabrica as f
from apps.processos.models import Processo


class ProcessosTests(f.Cenario):
    def dados(self, **extra):
        base = {"titulo": "Processo Novo Fictício", "cliente": self.cli.pk, "responsavel": self.adv.pk,
                "situacao": "ativo", "numero": "", "descricao": ""}
        base.update(extra)
        return base

    def test_adm_cadastra_com_cliente_e_responsavel(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("processos:novo"), self.dados(numero="0000002-22.2026.8.16.0001"))
        novo = Processo.objects.get(numero="0000002-22.2026.8.16.0001")
        self.assertRedirects(resposta, novo.get_absolute_url())
        self.assertEqual(novo.responsavel, self.adv)

    def test_numero_processual_unico(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("processos:novo"), self.dados(numero=self.proc.numero))
        self.assertContains(resposta, "Já existe um processo com este número no escritório.")

    def test_numero_vazio_pode_se_repetir(self):
        self.entrar(self.adm)
        self.client.post(reverse("processos:novo"), self.dados(titulo="Sem número 1"))
        self.client.post(reverse("processos:novo"), self.dados(titulo="Sem número 2"))
        self.assertEqual(Processo.objects.filter(numero__isnull=True, titulo__startswith="Sem número").count(), 2)

    def test_responsavel_deve_ser_adm_ou_adv(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("processos:novo"), self.dados(responsavel=self.ast.pk))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("responsavel", resposta.context["form"].errors)

    def test_cliente_e_titulo_obrigatorios(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("processos:novo"), self.dados(cliente="", titulo=""))
        erros = resposta.context["form"].errors
        self.assertIn("cliente", erros)
        self.assertIn("titulo", erros)

    def test_adv_e_sempre_o_responsavel_do_que_cadastra(self):
        f.autorizar_cliente(self.adv, self.cli)
        self.entrar(self.adv)
        self.client.post(reverse("processos:novo"), self.dados(titulo="Do advogado", responsavel=self.adv2.pk))
        self.assertEqual(Processo.objects.get(titulo="Do advogado").responsavel, self.adv)

    def test_adv_nao_usa_cliente_nao_autorizado(self):
        self.entrar(self.adv)
        resposta = self.client.post(reverse("processos:novo"), self.dados(cliente=self.cli2.pk))
        self.assertIn("cliente", resposta.context["form"].errors)

    def test_ast_apenas_consulta(self):
        f.autorizar_processo(self.ast, self.proc)
        self.entrar(self.ast)
        self.assertEqual(self.client.get(reverse("processos:novo")).status_code, 403)
        self.assertEqual(self.client.get(reverse("processos:editar", args=[self.proc.pk])).status_code, 403)
        resposta = self.client.get(reverse("processos:detalhe", args=[self.proc.pk]))
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.context["pode_editar"])
        self.assertNotIn("horas", resposta.context)
        self.assertNotIn("lancamentos", resposta.context)

    def test_adv_nao_acessa_processo_de_outro(self):
        self.entrar(self.adv)
        self.assertEqual(self.client.get(reverse("processos:detalhe", args=[self.proc2.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("processos:editar", args=[self.proc2.pk])).status_code, 404)

    def test_adv_atualiza_processo_autorizado_sem_trocar_responsavel(self):
        self.entrar(self.adv)
        self.client.post(reverse("processos:editar", args=[self.proc.pk]),
                         self.dados(titulo="Título atualizado", responsavel=self.adv2.pk))
        self.proc.refresh_from_db()
        self.assertEqual(self.proc.titulo, "Título atualizado")
        self.assertEqual(self.proc.responsavel, self.adv)

    def test_somente_adm_arquiva_e_vinculos_permanecem(self):
        h = f.registro_hora(self.adv, self.proc)
        self.entrar(self.adv)
        self.assertEqual(self.client.post(reverse("processos:arquivar", args=[self.proc.pk])).status_code, 403)
        self.entrar(self.adm)
        self.client.post(reverse("processos:arquivar", args=[self.proc.pk]))
        self.proc.refresh_from_db()
        self.assertTrue(self.proc.arquivado)
        h.refresh_from_db()
        self.assertEqual(h.processo, self.proc)

    def test_processo_arquivado_nao_e_editado(self):
        self.proc.arquivado = True
        self.proc.save()
        self.entrar(self.adm)
        resposta = self.client.get(reverse("processos:editar", args=[self.proc.pk]))
        self.assertRedirects(resposta, self.proc.get_absolute_url())

    def test_lista_filtra_por_permissao(self):
        self.entrar(self.adv)
        resposta = self.client.get(reverse("processos:lista"))
        self.assertContains(resposta, self.proc.titulo)
        self.assertNotContains(resposta, self.proc2.titulo)
