"""RF07 — horas trabalhadas (RN05, RN07)."""
from datetime import date

from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.core.tests import fabrica as f
from apps.horas.models import RegistroHora


class HorasTests(f.Cenario):
    def dados(self, **extra):
        base = {"processo": self.proc.pk, "data_atividade": "2026-11-10", "minutos": "90", "atividade": "Elaboração de petição"}
        base.update(extra)
        return base

    def test_ast_nao_acessa_horas(self):
        self.entrar(self.ast)
        self.assertEqual(self.client.get(reverse("horas:lista")).status_code, 403)
        self.assertEqual(self.client.post(reverse("horas:novo"), self.dados()).status_code, 403)

    def test_registra_as_proprias_horas(self):
        self.entrar(self.adv)
        resposta = self.client.post(reverse("horas:novo"), self.dados(usuario=self.adv2.pk))
        self.assertRedirects(resposta, reverse("horas:lista"))
        registro = RegistroHora.objects.get()
        self.assertEqual((registro.usuario, registro.minutos, registro.data_atividade), (self.adv, 90, date(2026, 11, 10)))

    def test_minutos_positivos_e_campos_obrigatorios(self):
        self.entrar(self.adv)
        for minutos in ("0", "-30"):
            with self.subTest(minutos=minutos):
                self.assertIn("minutos", self.client.post(reverse("horas:novo"), self.dados(minutos=minutos)).context["form"].errors)
        erros = self.client.post(reverse("horas:novo"), self.dados(processo="", atividade="", data_atividade="")).context["form"].errors
        for campo in ("processo", "atividade", "data_atividade"):
            self.assertIn(campo, erros)

    def test_banco_recusa_minutos_nao_positivos(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            f.registro_hora(self.adv, self.proc, minutos=0)

    def test_processo_nao_autorizado(self):
        self.entrar(self.adv)
        self.assertIn("processo", self.client.post(reverse("horas:novo"), self.dados(processo=self.proc2.pk)).context["form"].errors)

    def test_adv_ve_apenas_as_proprias(self):
        f.registro_hora(self.adv, self.proc, atividade="Atividade do advogado")
        f.registro_hora(self.adv2, self.proc2, atividade="Atividade da outra advogada")
        self.entrar(self.adv)
        resposta = self.client.get(reverse("horas:lista") + "?visao=equipe")
        self.assertContains(resposta, "Atividade do advogado")
        self.assertNotContains(resposta, "Atividade da outra advogada")

    def test_adm_consulta_a_equipe(self):
        f.registro_hora(self.adv, self.proc, atividade="Atividade do advogado")
        f.registro_hora(self.adv2, self.proc2, atividade="Atividade da outra advogada")
        self.entrar(self.adm)
        resposta = self.client.get(reverse("horas:lista") + "?visao=equipe")
        self.assertContains(resposta, "Atividade do advogado")
        self.assertContains(resposta, "Atividade da outra advogada")
        self.assertNotContains(self.client.get(reverse("horas:lista")), "Atividade do advogado")

    def test_somente_o_autor_edita(self):
        registro = f.registro_hora(self.adv, self.proc)
        for outro in (self.adv2, self.adm):
            with self.subTest(outro=outro.nome):
                self.entrar(outro)
                self.assertEqual(self.client.get(reverse("horas:editar", args=[registro.pk])).status_code, 404)
        self.entrar(self.adv)
        self.client.post(reverse("horas:editar", args=[registro.pk]), self.dados(minutos="45"))
        registro.refresh_from_db()
        self.assertEqual(registro.minutos, 45)

