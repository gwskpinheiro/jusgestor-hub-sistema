"""Dados fictícios para os testes (RNF08). Nenhum dado real é usado."""
import itertools
import secrets

from django.test import TestCase

from apps.clientes.models import AcessoCliente, Cliente
from apps.usuarios.models import Perfil, Usuario

_seq = itertools.count(1)


def usuario(perfil, nome=None, **extra):
    n = next(_seq)
    extra.setdefault("trocar_senha", False)
    return Usuario.objects.create_user(
        f"{perfil.lower()}{n}@exemplo.test", nome or f"Pessoa Fictícia {perfil} {n}", perfil,
        secrets.token_urlsafe(16), **extra,
    )


def cliente(nome=None, **extra):
    return Cliente.objects.create(nome=nome or f"Cliente Fictício {next(_seq)}", **extra)


def autorizar_cliente(u, c):
    AcessoCliente.objects.create(usuario=u, cliente=c)


class Cenario(TestCase):
    """Escritório fictício com os três perfis.

    - ast não tem acessos até que o teste os conceda.
    """

    @classmethod
    def setUpTestData(cls):
        cls.adm = usuario(Perfil.ADM, "Administradora Fictícia")
        cls.adv = usuario(Perfil.ADV, "Advogado Fictício")
        cls.adv2 = usuario(Perfil.ADV, "Advogada Fictícia Dois")
        cls.ast = usuario(Perfil.AST, "Assistente Fictício")
        cls.cli = cliente("Cliente Alfa Fictício")
        cls.cli2 = cliente("Cliente Beta Fictício")

    def entrar(self, u):
        self.client.force_login(u)
