"""Nome sugerido ao salvar o relatório em PDF pelo navegador (título da página)."""
import re
from datetime import date, datetime
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tests import fabrica as f
from apps.relatorios import views


def titulo(resposta):
    return re.search(r"<title>(.*?)</title>", resposta.content.decode(), re.S).group(1).strip()


class NomePdfTests(SimpleTestCase):
    def test_formato_do_nome(self):
        esperado = {
            "financeiro": "JusGestor_Relatorio_Financeiro_12-11-2026",
            "processos": "JusGestor_Relatorio_Processos_12-11-2026",
            "agenda": "JusGestor_Relatorio_Agenda_12-11-2026",
            "horas": "JusGestor_Relatorio_Horas_Trabalhadas_12-11-2026",
        }
        for chave, nome in esperado.items():
            with self.subTest(tipo=chave):
                self.assertEqual(views.nome_pdf(views.TIPOS[chave], date(2026, 11, 12)), nome)
                self.assertRegex(nome, r"^[A-Za-z0-9_-]+$")  # sem acentos, espaços ou barras


class TituloDaPaginaTests(f.Cenario):
    def gerar(self, tipo, **filtros):
        return self.client.get(reverse("relatorios:relatorio", args=[tipo]), {"gerar": "1", **filtros})

    def test_relatorio_gerado_usa_o_nome_do_pdf_como_titulo(self):
        self.entrar(self.adm)
        fixo = timezone.make_aware(datetime(2026, 11, 12, 10, 30))
        with mock.patch("apps.relatorios.views.timezone.localtime", return_value=fixo):
            resposta = self.gerar("processos")
        self.assertEqual(titulo(resposta), "JusGestor_Relatorio_Processos_12-11-2026")
        self.assertContains(resposta, "data-imprimir")  # impressão continua pelo navegador

    def test_titulo_normal_antes_de_gerar_e_sem_dados(self):
        self.entrar(self.adm)
        antes = self.client.get(reverse("relatorios:relatorio", args=["financeiro"]))
        self.assertEqual(titulo(antes), "Relatório: Financeiro · JusGestor Hub")
        vazio = self.gerar("financeiro")  # não há lançamentos no cenário
        self.assertContains(vazio, "Nenhum dado encontrado")
        self.assertEqual(titulo(vazio), "Relatório: Financeiro · JusGestor Hub")

    def test_demais_paginas_mantem_o_titulo(self):
        self.entrar(self.adm)
        self.assertEqual(titulo(self.client.get(reverse("clientes:lista"))), "Clientes · JusGestor Hub")
