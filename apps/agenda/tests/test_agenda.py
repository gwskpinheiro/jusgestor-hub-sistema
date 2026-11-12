"""RF04 — agenda (RN02, RN07)."""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from apps.agenda.models import Compromisso, Destaque, ParticipanteCompromisso
from apps.core.tests import fabrica as f

FMT = "%Y-%m-%dT%H:%M"


class DestaqueTests(SimpleTestCase):
    """RN02: destacar pendências vencidas e das próximas 24 horas."""

    def comp(self, inicio, fim=None, situacao="pendente"):
        return Compromisso(titulo="x", inicio=inicio, fim=fim, situacao=situacao)

    def test_regras_de_destaque(self):
        agora = timezone.now()
        casos = [
            (self.comp(agora - timedelta(hours=1)), Destaque.VENCIDO),
            (self.comp(agora + timedelta(hours=5)), Destaque.PROXIMO),
            (self.comp(agora + timedelta(hours=30)), None),
            (self.comp(agora - timedelta(hours=1), fim=agora + timedelta(hours=1)), Destaque.PROXIMO),
            (self.comp(agora - timedelta(hours=1), situacao="concluido"), None),
            (self.comp(agora + timedelta(hours=2), situacao="cancelado"), None),
        ]
        for comp, esperado in casos:
            with self.subTest(inicio=comp.inicio, situacao=comp.situacao):
                self.assertEqual(comp.destaque(agora), esperado)


class AgendaTests(f.Cenario):
    def dados(self, **extra):
        base = {"titulo": "Audiência fictícia", "tipo": "compromisso", "situacao": "pendente",
                "inicio": (timezone.localtime() + timedelta(days=2)).strftime(FMT), "fim": "",
                "responsavel": self.adv.pk, "processo": self.proc.pk, "descricao": ""}
        base.update(extra)
        return base

    def test_registra_com_participantes(self):
        self.entrar(self.adv)
        resposta = self.client.post(reverse("agenda:novo"), self.dados(participantes=[self.ast.pk, self.adv2.pk]))
        comp = Compromisso.objects.get(titulo="Audiência fictícia")
        self.assertRedirects(resposta, comp.get_absolute_url())
        self.assertEqual(set(comp.participantes.values_list("usuario_id", flat=True)), {self.ast.pk, self.adv2.pk})

    def test_data_responsavel_e_situacao_obrigatorios(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("agenda:novo"), self.dados(inicio="", responsavel="", situacao=""))
        erros = resposta.context["form"].errors
        for campo in ("inicio", "responsavel", "situacao"):
            self.assertIn(campo, erros)

    def test_termino_antes_do_inicio(self):
        self.entrar(self.adm)
        inicio = timezone.localtime() + timedelta(days=2)
        resposta = self.client.post(reverse("agenda:novo"), self.dados(
            inicio=inicio.strftime(FMT), fim=(inicio - timedelta(hours=1)).strftime(FMT)))
        self.assertIn("fim", resposta.context["form"].errors)

    def test_banco_recusa_termino_antes_do_inicio(self):
        agora = timezone.now()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Compromisso.objects.create(titulo="x", responsavel=self.adm, inicio=agora, fim=agora - timedelta(hours=1))

    def test_nao_adm_nao_cria_registro_que_deixaria_de_ver(self):
        self.entrar(self.ast)
        resposta = self.client.post(reverse("agenda:novo"), self.dados(processo="", responsavel=self.adv.pk))
        self.assertContains(resposta, "responsável ou participante")
        resposta = self.client.post(reverse("agenda:novo"), self.dados(processo="", participantes=[self.ast.pk]))
        self.assertEqual(resposta.status_code, 302)

    def test_ast_nao_vincula_processo_nao_autorizado(self):
        self.entrar(self.ast)
        resposta = self.client.post(reverse("agenda:novo"), self.dados(responsavel=self.ast.pk))
        self.assertIn("processo", resposta.context["form"].errors)

    def test_participante_ve_compromisso_mas_nao_o_processo(self):
        comp = f.compromisso(self.adv, self.proc, participantes=[self.ast])
        self.entrar(self.ast)
        resposta = self.client.get(comp.get_absolute_url())
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.context["ve_processo"])
        self.assertNotContains(resposta, self.proc.get_absolute_url())
        self.assertEqual(self.client.get(self.proc.get_absolute_url()).status_code, 404)

    def test_compromisso_alheio_responde_404(self):
        comp = f.compromisso(self.adv2, self.proc2)
        self.entrar(self.adv)
        self.assertEqual(self.client.get(comp.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(reverse("agenda:situacao", args=[comp.pk]),
                                          {"situacao": "cancelado"}).status_code, 404)

    def test_alterar_situacao_sem_excluir(self):
        comp = f.compromisso(self.adv)
        self.entrar(self.adv)
        self.client.post(reverse("agenda:situacao", args=[comp.pk]), {"situacao": "concluido"})
        comp.refresh_from_db()
        self.assertEqual(comp.situacao, "concluido")

    def test_edicao_atualiza_participantes(self):
        comp = f.compromisso(self.adv, participantes=[self.ast])
        self.entrar(self.adv)
        self.client.post(reverse("agenda:editar", args=[comp.pk]), self.dados(
            processo="", participantes=[self.adv2.pk], titulo=comp.titulo))
        self.assertEqual(list(ParticipanteCompromisso.objects.filter(compromisso=comp).values_list("usuario_id", flat=True)),
                         [self.adv2.pk])

    def test_lista_e_painel_mostram_destaques(self):
        f.compromisso(self.adv, titulo="Prazo vencido fictício", tipo="prazo",
                      inicio=timezone.now() - timedelta(hours=3))
        f.compromisso(self.adv, titulo="Reunião amanhã fictícia", inicio=timezone.now() + timedelta(hours=6))
        f.compromisso(self.adv, titulo="Reunião distante fictícia", inicio=timezone.now() + timedelta(days=5))
        self.entrar(self.adv)
        lista = self.client.get(reverse("agenda:lista"))
        self.assertContains(lista, "Vencido")
        self.assertEqual(lista.context["total_destacados"], 2)
        painel = self.client.get(reverse("core:painel"))
        self.assertContains(painel, "Prazo vencido fictício")
        self.assertContains(painel, "Reunião amanhã fictícia")
        self.assertNotContains(painel, "Reunião distante fictícia")
