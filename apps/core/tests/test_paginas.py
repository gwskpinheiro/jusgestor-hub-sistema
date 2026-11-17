"""Renderização de todas as páginas, com dados, para cada perfil.

Garante que nenhum template quebra e que cada perfil recebe a resposta
esperada (200 = permitido, 403 = perfil sem permissão, 404 = registro não
autorizado).
"""
import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.core.tests import fabrica as f
from apps.documentos.armazenamento import gravar_versao
from apps.documentos.models import Documento
from apps.financeiro import servicos


class PaginasPorPerfilTests(f.Cenario):
    def setUp(self):
        raiz = tempfile.mkdtemp(prefix="docs-paginas-")
        self.addCleanup(shutil.rmtree, raiz, True)
        override = override_settings(DOCUMENTOS_ROOT=raiz)
        override.enable()
        self.addCleanup(override.disable)

        f.autorizar_cliente(self.ast, self.cli)
        f.autorizar_processo(self.ast, self.proc)
        self.comp = f.compromisso(self.adv, self.proc, participantes=[self.ast])
        self.hora = f.registro_hora(self.adv, self.proc, minutos=150)
        self.doc = Documento.objects.create(titulo="Contrato fictício", processo=self.proc, cliente=self.cli)
        self.versao = gravar_versao(self.doc, SimpleUploadedFile("contrato.pdf", b"%PDF-1.4 ficticio"), self.adv)
        self.lanc = servicos.converter_horas(administrador=self.adm, processo=self.proc, registros=[self.hora],
                                             valor=Decimal("375.00"), descricao="Honorários fictícios",
                                             vencimento=date(2026, 12, 15))

    def esperado(self):
        """{url: (ADM, ADV, AST)}"""
        cli, proc, comp, doc, lanc = self.cli.pk, self.proc.pk, self.comp.pk, self.doc.pk, self.lanc.pk
        r = reverse
        return {
            r("core:painel"): (200, 200, 200),
            r("clientes:lista"): (200, 200, 200),
            r("clientes:novo"): (200, 200, 200),
            r("clientes:detalhe", args=[cli]): (200, 404, 200),
            r("clientes:editar", args=[cli]): (200, 404, 200),
            r("processos:lista"): (200, 200, 200),
            r("processos:novo"): (200, 200, 403),
            r("processos:detalhe", args=[proc]): (200, 200, 200),
            r("processos:editar", args=[proc]): (200, 200, 403),
            r("agenda:lista"): (200, 200, 200),
            r("agenda:calendario"): (200, 200, 200),
            r("agenda:calendario") + "?visao=dia": (200, 200, 200),
            r("agenda:calendario") + "?visao=semana": (200, 200, 200),
            r("agenda:calendario") + "?visao=ano": (200, 200, 200),
            r("agenda:novo"): (200, 200, 200),
            r("agenda:detalhe", args=[comp]): (200, 200, 200),
            r("agenda:editar", args=[comp]): (200, 200, 200),
            r("documentos:lista"): (200, 200, 200),
            r("documentos:novo"): (200, 200, 200),
            r("documentos:detalhe", args=[doc]): (200, 200, 200),
            r("documentos:editar", args=[doc]): (200, 200, 200),
            r("documentos:baixar", args=[self.versao.pk]): (200, 200, 200),
            r("horas:lista"): (200, 200, 403),
            r("horas:novo"): (200, 200, 403),
            r("horas:editar", args=[self.hora.pk]): (404, 200, 403),
            r("financeiro:lista"): (200, 403, 403),
            r("financeiro:novo"): (200, 403, 403),
            r("financeiro:detalhe", args=[lanc]): (200, 403, 403),
            r("financeiro:editar", args=[lanc]): (200, 403, 403),
            r("financeiro:cobrar_horas") + f"?processo={proc}": (200, 403, 403),
            r("relatorios:indice"): (200, 200, 403),
            r("relatorios:relatorio", args=["processos"]) + "?gerar=1": (200, 200, 403),
            r("relatorios:relatorio", args=["agenda"]) + "?gerar=1": (200, 200, 403),
            r("relatorios:relatorio", args=["horas"]) + "?gerar=1": (200, 200, 403),
            r("relatorios:relatorio", args=["financeiro"]) + "?gerar=1": (200, 403, 403),
            r("gestao_usuarios:lista"): (200, 403, 403),
            r("gestao_usuarios:novo"): (200, 403, 403),
            r("gestao_usuarios:editar", args=[self.ast.pk]): (200, 403, 403),
            r("gestao_usuarios:acessos", args=[self.ast.pk]): (200, 403, 403),
            r("gestao_usuarios:acessos", args=[self.adm.pk]): (200, 403, 403),
        }

    def test_todas_as_paginas_por_perfil(self):
        for indice, usuario in enumerate((self.adm, self.adv, self.ast)):
            self.entrar(usuario)
            for url, codigos in self.esperado().items():
                with self.subTest(perfil=usuario.perfil, url=url):
                    self.assertEqual(self.client.get(url).status_code, codigos[indice])

    def test_adv_sem_vinculo_recebe_404_nos_registros(self):
        self.entrar(self.adv2)
        for url in (self.proc.get_absolute_url(), self.comp.get_absolute_url(), self.doc.get_absolute_url(),
                    reverse("documentos:baixar", args=[self.versao.pk]), reverse("clientes:detalhe", args=[self.cli.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_detalhes_exibem_os_vinculos(self):
        self.entrar(self.adm)
        processo = self.client.get(self.proc.get_absolute_url())
        for texto in ("Contrato fictício", self.comp.titulo, "2h30", "Honorários fictícios"):
            self.assertContains(processo, texto)
        lanc = self.client.get(self.lanc.get_absolute_url())
        self.assertContains(lanc, "R$ 375,00")
        self.assertContains(lanc, "Ativo desde")
        self.assertContains(self.client.get(reverse("documentos:lista")), "v1")
