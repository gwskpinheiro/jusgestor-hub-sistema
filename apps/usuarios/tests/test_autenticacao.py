"""Testes do RF01: login, logout, contas inativas, bloqueio, sessão e troca de senha."""
import secrets
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.usuarios.models import Perfil, Usuario


def senha_aleatoria():
    return "T3ste-" + secrets.token_urlsafe(12)


class BaseAuth(TestCase):
    def setUp(self):
        self.senha = senha_aleatoria()
        self.usuario = Usuario.objects.create_user(
            "advogada@exemplo.test", "Advogada Fictícia", Perfil.ADV, self.senha, trocar_senha=False
        )
        self.url_login = reverse("usuarios:login")

    def entrar(self, email=None, senha=None):
        return self.client.post(self.url_login, {"username": email or self.usuario.email, "password": senha or self.senha})

    def recarregar(self):
        self.usuario.refresh_from_db()


class LoginTests(BaseAuth):
    def test_pagina_de_login_abre_sem_autenticacao(self):
        self.assertEqual(self.client.get(self.url_login).status_code, 200)

    def test_login_por_email_e_senha(self):
        resposta = self.entrar()
        self.assertRedirects(resposta, reverse("core:painel"))
        self.assertIn(SESSION_KEY, self.client.session)

    def test_email_sem_diferenciar_maiusculas(self):
        resposta = self.entrar(email="ADVOGADA@Exemplo.test")
        self.assertRedirects(resposta, reverse("core:painel"))

    def test_senha_errada_mostra_mensagem_generica(self):
        resposta = self.entrar(senha="errada")
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "E-mail ou senha inválidos")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_email_inexistente_mostra_mesma_mensagem(self):
        resposta = self.entrar(email="ninguem@exemplo.test")
        self.assertContains(resposta, "E-mail ou senha inválidos")

    def test_conta_inativa_nao_entra(self):
        self.usuario.ativo = False
        self.usuario.save()
        resposta = self.entrar()
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_conta_desativada_durante_a_sessao_perde_acesso(self):
        self.entrar()
        Usuario.objects.filter(pk=self.usuario.pk).update(ativo=False)
        resposta = self.client.get(reverse("core:painel"))
        self.assertRedirects(resposta, f"{self.url_login}?next=/")

    def test_campos_obrigatorios(self):
        resposta = self.client.post(self.url_login, {"username": "", "password": ""})
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context["form"].errors)


class BloqueioTests(BaseAuth):
    def errar(self, vezes):
        for _ in range(vezes):
            self.entrar(senha="senha-errada")

    def test_falhas_sao_contadas_e_zeradas_no_sucesso(self):
        self.errar(3)
        self.recarregar()
        self.assertEqual(self.usuario.tentativas_falhas, 3)
        self.entrar()
        self.recarregar()
        self.assertEqual(self.usuario.tentativas_falhas, 0)

    def test_cinco_falhas_bloqueiam_por_15_minutos(self):
        self.errar(4)
        self.recarregar()
        self.assertIsNone(self.usuario.bloqueado_ate)

        antes = timezone.now()
        resposta = self.entrar(senha="senha-errada")
        self.assertContains(resposta, "Acesso bloqueado temporariamente")
        self.recarregar()
        self.assertIsNotNone(self.usuario.bloqueado_ate)
        duracao = self.usuario.bloqueado_ate - antes
        self.assertTrue(timedelta(minutes=14, seconds=59) <= duracao <= timedelta(minutes=15, seconds=5))

    def test_senha_correta_nao_entra_durante_o_bloqueio(self):
        self.errar(settings.LOGIN_MAX_TENTATIVAS)
        resposta = self.entrar()
        self.assertContains(resposta, "Acesso bloqueado temporariamente")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_login_liberado_apos_15_minutos(self):
        self.errar(settings.LOGIN_MAX_TENTATIVAS)
        depois = timezone.now() + timedelta(minutes=15, seconds=1)
        with mock.patch("django.utils.timezone.now", return_value=depois):
            resposta = self.entrar()
        self.assertRedirects(resposta, reverse("core:painel"), fetch_redirect_response=False)
        self.recarregar()
        self.assertIsNone(self.usuario.bloqueado_ate)
        self.assertEqual(self.usuario.tentativas_falhas, 0)

    def test_falhas_nao_consecutivas_nao_bloqueiam(self):
        self.errar(4)
        self.entrar()
        self.client.logout()
        self.errar(4)
        self.recarregar()
        self.assertIsNone(self.usuario.bloqueado_ate)


class SessaoELogoutTests(BaseAuth):
    def test_sessao_expira_apos_30_minutos_sem_atividade(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 30 * 60)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)
        self.entrar()
        self.assertEqual(self.client.session.get_expiry_age(), 30 * 60)

    def test_paginas_internas_exigem_login(self):
        resposta = self.client.get(reverse("core:painel"))
        self.assertRedirects(resposta, f"{self.url_login}?next=/")

    def test_logout_por_post_encerra_sessao(self):
        self.entrar()
        resposta = self.client.post(reverse("usuarios:logout"))
        self.assertRedirects(resposta, self.url_login)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_logout_por_get_nao_e_aceito(self):
        self.entrar()
        self.assertEqual(self.client.get(reverse("usuarios:logout")).status_code, 405)


class TrocaSenhaTests(TestCase):
    def setUp(self):
        self.temporaria = senha_aleatoria()
        self.usuario = Usuario.objects.create_user(
            "assistente@exemplo.test", "Assistente Fictícia", Perfil.AST, self.temporaria
        )
        self.client.post(reverse("usuarios:login"), {"username": self.usuario.email, "password": self.temporaria})
        self.url_troca = reverse("usuarios:trocar_senha")

    def test_senha_temporaria_redireciona_para_troca(self):
        self.assertRedirects(self.client.get(reverse("core:painel")), self.url_troca)

    def test_troca_libera_acesso_e_mantem_sessao(self):
        nova = senha_aleatoria()
        resposta = self.client.post(
            self.url_troca, {"old_password": self.temporaria, "new_password1": nova, "new_password2": nova}
        )
        self.assertRedirects(resposta, reverse("core:painel"))
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.trocar_senha)
        self.assertTrue(self.usuario.check_password(nova))
        self.assertEqual(self.client.get(reverse("core:painel")).status_code, 200)

    def test_senha_fraca_e_recusada(self):
        resposta = self.client.post(
            self.url_troca, {"old_password": self.temporaria, "new_password1": "12345678", "new_password2": "12345678"}
        )
        self.assertEqual(resposta.status_code, 200)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.trocar_senha)

    def test_logout_continua_disponivel_durante_troca_obrigatoria(self):
        resposta = self.client.post(reverse("usuarios:logout"))
        self.assertRedirects(resposta, reverse("usuarios:login"))
