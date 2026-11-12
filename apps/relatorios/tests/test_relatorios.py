"""RF08 — relatórios (RN09) e fluxo da Figura 2."""
from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.core.tests import fabrica as f
from apps.financeiro import servicos
from apps.financeiro.models import LancamentoFinanceiro


def url(tipo, **params):
    from urllib.parse import urlencode

    return reverse("relatorios:relatorio", args=[tipo]) + ("?" + urlencode(params, doseq=True) if params else "")


class RelatoriosTests(f.Cenario):
    def test_perfis(self):
        self.entrar(self.ast)
        self.assertEqual(self.client.get(reverse("relatorios:indice")).status_code, 403)
        self.assertEqual(self.client.get(url("processos")).status_code, 403)
        self.entrar(self.adv)
        self.assertNotContains(self.client.get(reverse("relatorios:indice")), "Financeiro")
        self.assertEqual(self.client.get(url("financeiro", gerar=1)).status_code, 403)
        self.assertEqual(self.client.get(url("inexistente")).status_code, 404)
        self.entrar(self.adm)
        self.assertEqual(self.client.get(url("financeiro")).status_code, 200)

    def test_fluxo_sem_solicitacao_nao_gera(self):
        self.entrar(self.adm)
        resposta = self.client.get(url("processos"))
        self.assertIsNone(resposta.context["resultado"])
        self.assertContains(resposta, "Gerar relatório")

    def test_informa_ausencia_de_dados(self):
        self.entrar(self.adm)
        resposta = self.client.get(url("horas", gerar=1))
        self.assertContains(resposta, "Nenhum dado encontrado")
        self.assertEqual(self.client.get(url("horas", gerar=1, formato="csv"))["Content-Type"].split(";")[0], "text/html")

    def test_periodo_invalido(self):
        self.entrar(self.adm)
        resposta = self.client.get(url("processos", gerar=1, de="2026-12-31", ate="2026-01-01"))
        self.assertIn("ate", resposta.context["form"].errors)

    def test_processos_do_adv_somente_autorizados(self):
        self.entrar(self.adv)
        resposta = self.client.get(url("processos", gerar=1))
        self.assertContains(resposta, self.proc.titulo)
        self.assertNotContains(resposta, self.proc2.titulo)
        self.assertContains(resposta, "Imprimir / salvar em PDF")

    def test_adv_ve_apenas_as_proprias_horas_mesmo_forcando_filtro(self):
        f.registro_hora(self.adv, self.proc, atividade="Hora do advogado")
        f.registro_hora(self.adv2, self.proc2, atividade="Hora da outra advogada")
        self.entrar(self.adv)
        resposta = self.client.get(url("horas", gerar=1, usuario_filtro=self.adv2.pk))
        self.assertContains(resposta, "Hora do advogado")
        self.assertNotContains(resposta, "Hora da outra advogada")

    def test_agenda_oculta_processo_sem_acesso(self):
        f.compromisso(self.adv, self.proc, participantes=[self.ast], titulo="Reunião fictícia")
        self.entrar(self.adv2)
        f.compromisso(self.adv, self.proc, participantes=[self.adv2], titulo="Reunião com participante")
        resposta = self.client.get(url("agenda", gerar=1))
        self.assertContains(resposta, "Reunião com participante")
        self.assertContains(resposta, "(processo sem acesso)")
        self.assertNotContains(resposta, self.proc.titulo)

    def test_exporta_csv_com_bom_separador_e_protecao_contra_formulas(self):
        f.cliente("=HYPERLINK(\"http://exemplo.test\")")
        cli_formula = f.cliente("=1+1 Cliente")
        f.processo(cli_formula, self.adv, titulo="+cmd processo")
        self.entrar(self.adm)
        resposta = self.client.get(url("processos", gerar=1, formato="csv"))
        self.assertEqual(resposta["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", resposta["Content-Disposition"])
        conteudo = resposta.content.decode("utf-8")
        self.assertTrue(conteudo.startswith("﻿Número;Título;Cliente"))
        self.assertIn("'+cmd processo;'=1+1 Cliente", conteudo)
        self.assertNotIn(";=1+1", conteudo)

    def test_financeiro_totais_e_csv(self):
        lanc = LancamentoFinanceiro.objects.create(criado_por=self.adm, descricao="Honorários fictícios", tipo="receita",
                                                   valor=Decimal("1234.50"), vencimento=date(2026, 11, 1))
        servicos.quitar(lanc, date(2026, 11, 2))
        self.entrar(self.adm)
        resposta = self.client.get(url("financeiro", gerar=1))
        self.assertContains(resposta, "R$ 1.234,50")
        self.assertIn(("Saldo quitado", "R$ 1.234,50"), resposta.context["resultado"].resumo)
        csv = self.client.get(url("financeiro", gerar=1, formato="csv")).content.decode()
        self.assertIn("1234,50", csv)

    def test_painel_por_perfil(self):
        self.entrar(self.ast)
        painel = self.client.get(reverse("core:painel"))
        self.assertNotContains(painel, "Saldo financeiro")
        self.assertNotContains(painel, "horas no mês")
        self.entrar(self.adv)
        painel = self.client.get(reverse("core:painel"))
        self.assertNotContains(painel, "Saldo financeiro")
        self.assertContains(painel, "Minhas horas no mês")
        self.entrar(self.adm)
        self.assertContains(self.client.get(reverse("core:painel")), "Saldo financeiro")
