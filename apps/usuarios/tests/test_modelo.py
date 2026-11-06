from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from apps.usuarios.models import Perfil, Usuario


class ModeloUsuarioTests(TestCase):
    def test_tabela_e_coluna_de_senha_seguem_modelo_relacional(self):
        self.assertEqual(Usuario._meta.db_table, "usuario")
        self.assertEqual(Usuario._meta.get_field("password").column, "senha_hash")
        with connection.cursor() as cursor:
            colunas = {c.name for c in connection.introspection.get_table_description(cursor, "usuario")}
        esperadas = {"id", "nome", "email", "senha_hash", "perfil", "ativo", "trocar_senha", "criado_em",
                     "tentativas_falhas", "bloqueado_ate", "last_login"}
        self.assertEqual(colunas, esperadas)

    def test_cria_usuario_com_email_normalizado_e_senha_em_hash(self):
        u = Usuario.objects.create_user("  Fulano@Exemplo.TEST ", "Fulano Fictício", Perfil.ADV, "senha-de-teste-123")
        self.assertEqual(u.email, "fulano@exemplo.test")
        self.assertNotEqual(u.password, "senha-de-teste-123")
        self.assertTrue(u.check_password("senha-de-teste-123"))
        self.assertTrue(u.trocar_senha, "Conta nova deve exigir troca de senha")
        self.assertTrue(u.ativo)

    def test_sem_senha_a_conta_fica_com_senha_inutilizavel(self):
        u = Usuario.objects.create_user("sem.senha@exemplo.test", "Sem Senha", Perfil.AST)
        self.assertFalse(u.has_usable_password())

    def test_is_active_reflete_coluna_ativo(self):
        u = Usuario.objects.create_user("a@exemplo.test", "A", Perfil.AST, "senha-de-teste-123")
        u.ativo = False
        self.assertFalse(u.is_active)

    def test_email_unico_sem_diferenciar_maiusculas(self):
        Usuario.objects.create_user("dup@exemplo.test", "Um", Perfil.ADV, "x")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.create(email="DUP@exemplo.test", nome="Dois", perfil=Perfil.ADV)

    def test_banco_rejeita_perfil_invalido(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.create(email="x@exemplo.test", nome="X", perfil="XYZ")

    def test_create_user_rejeita_perfil_invalido(self):
        with self.assertRaises(ValueError):
            Usuario.objects.create_user("y@exemplo.test", "Y", "XYZ", "x")
