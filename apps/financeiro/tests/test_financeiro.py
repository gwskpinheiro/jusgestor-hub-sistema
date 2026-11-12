"""RF05 — financeiro (RN03, RN07, RN10)."""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.core.tests import fabrica as f
from apps.financeiro import servicos
from apps.financeiro.models import CobrancaHora, LancamentoFinanceiro


class FinanceiroTests(f.Cenario):
    def lancamento(self, **extra):
        base = dict(criado_por=self.adm, descricao="Honorários fictícios", tipo="receita",
                    valor=Decimal("1500.00"), vencimento=date(2026, 12, 10))
        base.update(extra)
        return LancamentoFinanceiro.objects.create(**base)

    def dados(self, **extra):
        base = {"tipo": "receita", "descricao": "Honorários fictícios", "valor": "1500.00",
                "vencimento": "2026-12-10", "cliente": "", "processo": ""}
        base.update(extra)
        return base

    def test_restrito_ao_adm(self):
        lanc = self.lancamento()
        urls = [reverse("financeiro:lista"), reverse("financeiro:novo"), reverse("financeiro:cobrar_horas"),
                reverse("financeiro:detalhe", args=[lanc.pk]), reverse("financeiro:editar", args=[lanc.pk])]
        for perfil_usuario in (self.adv, self.ast):
            self.entrar(perfil_usuario)
            for url in urls:
                with self.subTest(usuario=perfil_usuario.perfil, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(reverse("financeiro:cancelar", args=[lanc.pk])).status_code, 403)
        lanc.refresh_from_db()
        self.assertEqual(lanc.situacao, "pendente")

    def test_registra_lancamento_com_vinculo_opcional_ao_processo(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("financeiro:novo"), self.dados(processo=self.proc.pk))
        lanc = LancamentoFinanceiro.objects.get()
        self.assertRedirects(resposta, lanc.get_absolute_url())
        self.assertEqual((lanc.cliente, lanc.processo, lanc.criado_por, lanc.situacao),
                         (self.cli, self.proc, self.adm, "pendente"))

    def test_valor_positivo_e_campos_obrigatorios(self):
        self.entrar(self.adm)
        for valor in ("0", "-10"):
            with self.subTest(valor=valor):
                self.assertIn("valor", self.client.post(reverse("financeiro:novo"), self.dados(valor=valor)).context["form"].errors)
        erros = self.client.post(reverse("financeiro:novo"), self.dados(tipo="", descricao="", vencimento="")).context["form"].errors
        for campo in ("tipo", "descricao", "vencimento"):
            self.assertIn(campo, erros)

    def test_banco_recusa_valor_nao_positivo_e_quitacao_incoerente(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.lancamento(valor=Decimal("0"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.lancamento(situacao="quitado")  # sem data da quitação

    def test_cliente_diferente_do_processo(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("financeiro:novo"), self.dados(processo=self.proc.pk, cliente=self.cli2.pk))
        self.assertIn("cliente", resposta.context["form"].errors)

    def test_quitar_registra_data(self):
        lanc = self.lancamento()
        self.entrar(self.adm)
        self.client.post(reverse("financeiro:quitar", args=[lanc.pk]), {"data_quitacao": "2026-11-05"})
        lanc.refresh_from_db()
        self.assertEqual((lanc.situacao, lanc.data_quitacao), ("quitado", date(2026, 11, 5)))

    def test_quitacao_no_futuro_e_quitacao_repetida(self):
        lanc = self.lancamento()
        with self.assertRaises(ValidationError):
            servicos.quitar(lanc, timezone.localdate() + timedelta(days=1))
        servicos.quitar(lanc, timezone.localdate())
        with self.assertRaises(ValidationError):
            servicos.quitar(lanc, timezone.localdate())
        with self.assertRaises(ValidationError):
            servicos.cancelar(lanc)

    def test_lancamento_quitado_nao_e_editado(self):
        lanc = self.lancamento()
        servicos.quitar(lanc, timezone.localdate())
        self.entrar(self.adm)
        self.client.post(reverse("financeiro:editar", args=[lanc.pk]), self.dados(valor="1.00"))
        lanc.refresh_from_db()
        self.assertEqual(lanc.valor, Decimal("1500.00"))

    def test_totais_consideram_quitados(self):
        servicos.quitar(self.lancamento(valor=Decimal("1000")), timezone.localdate())
        servicos.quitar(self.lancamento(tipo="despesa", valor=Decimal("250")), timezone.localdate())
        self.lancamento(valor=Decimal("999"))  # pendente
        self.entrar(self.adm)
        totais = self.client.get(reverse("financeiro:lista")).context["totais"]
        self.assertEqual((totais["receitas"], totais["despesas"], totais["saldo"], totais["a_receber"]),
                         (Decimal("1000"), Decimal("250"), Decimal("750"), Decimal("999")))


class ConversaoHorasTests(f.Cenario):
    """RN10: conversão confirmada de horas em cobrança."""

    def converter(self, registros, processo=None):
        return servicos.converter_horas(administrador=self.adm, processo=processo or self.proc, registros=registros,
                                        valor=Decimal("450.00"), descricao="Horas fictícias", vencimento=date(2026, 12, 1))

    def test_gera_receita_pendente_vinculada(self):
        h1, h2 = f.registro_hora(self.adv, self.proc), f.registro_hora(self.adm, self.proc)
        lanc = self.converter([h1, h2])
        self.assertEqual((lanc.tipo, lanc.situacao, lanc.processo, lanc.cliente, lanc.valor),
                         ("receita", "pendente", self.proc, self.cli, Decimal("450.00")))
        self.assertEqual(set(lanc.cobrancas.values_list("registro_hora_id", flat=True)), {h1.pk, h2.pk})

    def test_registro_admite_um_vinculo_ativo(self):
        h = f.registro_hora(self.adv, self.proc)
        self.converter([h])
        with self.assertRaises(ValidationError):
            self.converter([h])
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)  # nada parcial gravado

    def test_indice_parcial_do_banco_impede_dois_vinculos_ativos(self):
        h = f.registro_hora(self.adv, self.proc)
        lanc = self.converter([h])
        with self.assertRaises(IntegrityError), transaction.atomic():
            CobrancaHora.objects.create(lancamento=lanc, registro_hora=h)

    def test_registros_de_outro_processo_sao_recusados(self):
        h = f.registro_hora(self.adv2, self.proc2)
        with self.assertRaises(ValidationError):
            self.converter([h])
        self.assertFalse(LancamentoFinanceiro.objects.exists())

    def test_cancelar_libera_vinculo_e_preserva_historico(self):
        h = f.registro_hora(self.adv, self.proc)
        lanc = self.converter([h])
        servicos.cancelar(lanc)
        cobranca = CobrancaHora.objects.get(lancamento=lanc)
        self.assertIsNotNone(cobranca.liberado_em)
        self.assertIsNone(h.cobranca_ativa())
        novo = self.converter([h])  # horas disponíveis novamente
        self.assertEqual(CobrancaHora.objects.filter(registro_hora=h).count(), 2)
        self.assertEqual(novo.cobrancas.get().registro_hora, h)

    def test_tela_de_conversao(self):
        h = f.registro_hora(self.adv, self.proc, atividade="Audiência fictícia")
        self.entrar(self.adm)
        url = reverse("financeiro:cobrar_horas") + f"?processo={self.proc.pk}"
        self.assertContains(self.client.get(url), "Audiência fictícia")
        resposta = self.client.post(url, {"registros": [h.pk], "valor": "200.00", "descricao": "Cobrança",
                                          "vencimento": "2026-12-20"})
        lanc = LancamentoFinanceiro.objects.get()
        self.assertRedirects(resposta, lanc.get_absolute_url())
        self.assertNotContains(self.client.get(url), "Audiência fictícia")

    def test_tela_exige_registro_e_valor(self):
        f.registro_hora(self.adv, self.proc)
        self.entrar(self.adm)
        url = reverse("financeiro:cobrar_horas") + f"?processo={self.proc.pk}"
        erros = self.client.post(url, {"valor": "0", "descricao": "x", "vencimento": "2026-12-20"}).context["form"].errors
        self.assertIn("registros", erros)
        self.assertIn("valor", erros)
