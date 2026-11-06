import secrets

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.core.permissoes import perfil_requerido
from apps.usuarios.models import Perfil, Usuario


def criar(perfil):
    return Usuario.objects.create_user(
        f"{perfil.lower()}@exemplo.test", f"Pessoa Fictícia {perfil}", perfil,
        secrets.token_urlsafe(16), trocar_senha=False,
    )


class MenuPorPerfilTests(TestCase):
    """Itens do menu conforme o diagrama de casos de uso (Figura 1)."""

    esperado = {
        Perfil.ADM: ["Painel", "Processos", "Clientes", "Agenda", "Financeiro", "Documentos",
                     "Horas trabalhadas", "Relatórios", "Usuários"],
        Perfil.ADV: ["Painel", "Processos", "Clientes", "Agenda", "Documentos", "Horas trabalhadas", "Relatórios"],
        Perfil.AST: ["Painel", "Processos", "Clientes", "Agenda", "Documentos"],
    }

    def test_menu_de_cada_perfil(self):
        for perfil, rotulos in self.esperado.items():
            with self.subTest(perfil=perfil):
                self.client.force_login(criar(perfil))
                resposta = self.client.get(reverse("core:painel"))
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual([i["rotulo"] for i in resposta.context["menu_itens"]], rotulos)
                self.client.logout()

    def test_painel_exibe_nome_e_perfil(self):
        self.client.force_login(criar(Perfil.ADV))
        resposta = self.client.get(reverse("core:painel"))
        self.assertContains(resposta, "Pessoa Fictícia ADV")
        self.assertContains(resposta, "Advogado")


class PerfilRequeridoTests(TestCase):
    def setUp(self):
        self.fabrica = RequestFactory()

        @perfil_requerido(Perfil.ADM)
        def view_somente_adm(request):
            return HttpResponse("ok")

        self.view = view_somente_adm

    def requisitar(self, usuario):
        request = self.fabrica.get("/qualquer/")
        request.user = usuario
        return self.view(request)

    def test_adm_acessa(self):
        self.assertEqual(self.requisitar(criar(Perfil.ADM)).status_code, 200)

    def test_outros_perfis_recebem_403(self):
        for perfil in (Perfil.ADV, Perfil.AST):
            with self.subTest(perfil=perfil), self.assertRaises(PermissionDenied):
                self.requisitar(criar(perfil))

    def test_usuario_inativo_recebe_403(self):
        adm = criar(Perfil.ADM)
        adm.ativo = False
        with self.assertRaises(PermissionDenied):
            self.requisitar(adm)


class PaginasDeErroTests(TestCase):
    def test_404_personalizada(self):
        self.client.force_login(criar(Perfil.AST))
        resposta = self.client.get("/nao-existe/")
        self.assertEqual(resposta.status_code, 404)
        self.assertContains(resposta, "Página não encontrada", status_code=404)
