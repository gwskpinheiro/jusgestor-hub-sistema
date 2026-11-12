"""Dados fictícios para os testes (RNF08). Nenhum dado real é usado."""
import itertools
import secrets
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Compromisso, ParticipanteCompromisso
from apps.clientes.models import AcessoCliente, Cliente
from apps.processos.models import AcessoProcesso, Processo
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


def processo(cliente_, responsavel, **extra):
    extra.setdefault("titulo", f"Processo Fictício {next(_seq)}")
    return Processo.objects.create(cliente=cliente_, responsavel=responsavel, **extra)


def autorizar_cliente(u, c):
    AcessoCliente.objects.create(usuario=u, cliente=c)


def autorizar_processo(u, p):
    AcessoProcesso.objects.create(usuario=u, processo=p)


def compromisso(responsavel, processo_=None, participantes=(), **extra):
    extra.setdefault("titulo", f"Compromisso Fictício {next(_seq)}")
    extra.setdefault("inicio", timezone.now() + timedelta(days=3))
    c = Compromisso.objects.create(responsavel=responsavel, processo=processo_, **extra)
    for u in participantes:
        ParticipanteCompromisso.objects.create(compromisso=c, usuario=u)
    return c


def registro_hora(u, processo_, minutos=60, **extra):
    from apps.horas.models import RegistroHora

    extra.setdefault("data_atividade", date.today())
    extra.setdefault("atividade", "Atividade fictícia")
    return RegistroHora.objects.create(usuario=u, processo=processo_, minutos=minutos, **extra)


class Cenario(TestCase):
    """Escritório fictício com os três perfis.

    - adv é responsável por ``proc``; adv2 é responsável por ``proc2``.
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
        cls.proc = processo(cls.cli, cls.adv, titulo="Ação Fictícia Alfa", numero="0000001-11.2026.8.16.0001")
        cls.proc2 = processo(cls.cli2, cls.adv2, titulo="Ação Fictícia Beta")

    def entrar(self, u):
        self.client.force_login(u)
