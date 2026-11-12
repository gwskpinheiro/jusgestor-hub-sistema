"""RF09 — gerenciamento de usuários (RN06, RN07, RN08)."""
import re

from django.urls import reverse

from apps.clientes.models import AcessoCliente
from apps.core import acesso
from apps.core.tests import fabrica as f
from apps.processos.models import AcessoProcesso
from apps.usuarios.models import Perfil, Usuario


def senha_da_pagina(resposta):
    return re.search(r'class="senha-temporaria">([^<]+)<', resposta.content.decode()).group(1).strip()


class GestaoUsuariosTests(f.Cenario):
    def test_somente_adm(self):
        for u in (self.adv, self.ast):
            self.entrar(u)
            for url in (reverse("gestao_usuarios:lista"), reverse("gestao_usuarios:novo"),
                        reverse("gestao_usuarios:editar", args=[self.adm.pk])):
                with self.subTest(perfil=u.perfil, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_cria_conta_com_senha_temporaria_exibida_uma_vez(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("gestao_usuarios:novo"),
                                    {"nome": "Nova Assistente Fictícia", "email": "Nova@Exemplo.test", "perfil": "AST"})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("no-cache", resposta["Cache-Control"])
        novo = Usuario.objects.get(email="nova@exemplo.test")
        self.assertTrue(novo.trocar_senha)
        self.assertTrue(novo.check_password(senha_da_pagina(resposta)))
        self.assertNotIn("senha", str(list(resposta.wsgi_request._messages)))

    def test_email_duplicado_sem_diferenciar_maiusculas(self):
        self.entrar(self.adm)
        resposta = self.client.post(reverse("gestao_usuarios:novo"),
                                    {"nome": "X", "email": self.adv.email.upper(), "perfil": "ADV"})
        self.assertIn("email", resposta.context["form"].errors)

    def test_nao_elimina_o_ultimo_administrador_ativo(self):
        self.entrar(self.adm)
        url = reverse("gestao_usuarios:editar", args=[self.adm.pk])
        base = {"nome": self.adm.nome, "email": self.adm.email}
        for alteracao in ({"perfil": "ADM", "ativo": ""}, {"perfil": "ADV", "ativo": "on"}):
            with self.subTest(alteracao=alteracao):
                resposta = self.client.post(url, {**base, **alteracao})
                self.assertContains(resposta, "ao menos um administrador ativo")
                self.adm.refresh_from_db()
                self.assertTrue(self.adm.ativo and self.adm.perfil == Perfil.ADM)

    def test_com_dois_administradores_um_pode_ser_desativado(self):
        outro = f.usuario(Perfil.ADM)
        self.entrar(self.adm)
        self.client.post(reverse("gestao_usuarios:editar", args=[outro.pk]),
                         {"nome": outro.nome, "email": outro.email, "perfil": "ADM", "ativo": ""})
        outro.refresh_from_db()
        self.assertFalse(outro.ativo)
        # Conta preservada (RN08): desativada, não excluída.
        self.assertTrue(Usuario.objects.filter(pk=outro.pk).exists())

    def test_redefinir_senha(self):
        self.ast.tentativas_falhas = 3
        self.ast.save()
        self.entrar(self.adm)
        resposta = self.client.post(reverse("gestao_usuarios:redefinir_senha", args=[self.ast.pk]))
        self.ast.refresh_from_db()
        self.assertTrue(self.ast.trocar_senha)
        self.assertEqual(self.ast.tentativas_falhas, 0)
        self.assertTrue(self.ast.check_password(senha_da_pagina(resposta)))
        self.assertEqual(self.client.get(reverse("gestao_usuarios:redefinir_senha", args=[self.ast.pk])).status_code, 405)

    def test_atribui_acessos_a_clientes_e_processos(self):
        self.entrar(self.adm)
        self.client.post(reverse("gestao_usuarios:acessos", args=[self.ast.pk]),
                         {"clientes": [self.cli.pk], "processos": [self.proc2.pk]})
        self.assertEqual(list(AcessoCliente.objects.filter(usuario=self.ast).values_list("cliente_id", flat=True)), [self.cli.pk])
        self.assertEqual(list(AcessoProcesso.objects.filter(usuario=self.ast).values_list("processo_id", flat=True)), [self.proc2.pk])
        self.assertTrue(acesso.processos_visiveis(self.ast).filter(pk=self.proc2.pk).exists())
        # Revogação: lista vazia remove os acessos.
        self.client.post(reverse("gestao_usuarios:acessos", args=[self.ast.pk]), {})
        self.assertFalse(acesso.processos_visiveis(self.ast).exists())

    def test_usuario_desativado_perde_acesso_imediatamente(self):
        self.entrar(self.adv)
        Usuario.objects.filter(pk=self.adv.pk).update(ativo=False)
        resposta = self.client.get(reverse("processos:lista"))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("usuarios:login"), resposta["Location"])
