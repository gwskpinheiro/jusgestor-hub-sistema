from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.usuarios.models import Perfil, Usuario


class CriarAdminTests(TestCase):
    def executar(self, **opcoes):
        saida = StringIO()
        call_command("criar_admin", stdout=saida, **opcoes)
        return saida.getvalue()

    def test_cria_adm_com_senha_temporaria_aleatoria(self):
        saida = self.executar(email="Admin@Exemplo.test", nome="Administração Fictícia")
        usuario = Usuario.objects.get(email="admin@exemplo.test")
        self.assertEqual(usuario.perfil, Perfil.ADM)
        self.assertTrue(usuario.trocar_senha)
        senha = saida.split("Senha temporária (exibida apenas agora): ")[1].split()[0]
        self.assertTrue(usuario.check_password(senha))

    def test_senhas_geradas_sao_diferentes(self):
        s1 = self.executar(email="a1@exemplo.test", nome="A1")
        s2 = self.executar(email="a2@exemplo.test", nome="A2")
        extrair = lambda s: s.split("agora): ")[1].split()[0]
        self.assertNotEqual(extrair(s1), extrair(s2))

    def test_recusa_email_duplicado(self):
        self.executar(email="adm@exemplo.test", nome="ADM")
        with self.assertRaises(CommandError):
            self.executar(email="ADM@exemplo.test", nome="Outro")

    def test_recusa_email_invalido(self):
        with self.assertRaises(CommandError):
            self.executar(email="nao-e-email", nome="X")
