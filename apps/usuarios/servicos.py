"""Regras de gerenciamento de contas (RF09; RN06, RN08)."""
import secrets

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Perfil, Usuario

MENSAGEM_ULTIMO_ADM = "Operação recusada: o sistema precisa manter ao menos um administrador ativo."


def gerar_senha_temporaria():
    return secrets.token_urlsafe(12)


def salvar_usuario(usuario):
    """Grava alterações de perfil/situação impedindo eliminar o último ADM ativo (RN06).

    Os administradores ativos são bloqueados (SELECT ... FOR UPDATE) para que duas
    alterações simultâneas não removam, juntas, os dois últimos administradores.
    """
    with transaction.atomic():
        ativos = list(
            Usuario.objects.select_for_update().filter(perfil=Perfil.ADM, ativo=True).values_list("pk", flat=True)
        )
        continuara_adm_ativo = usuario.perfil == Perfil.ADM and usuario.ativo
        if usuario.pk in ativos and not continuara_adm_ativo and len(ativos) <= 1:
            raise ValidationError(MENSAGEM_ULTIMO_ADM)
        usuario.save()
    return usuario


def criar_usuario(*, nome, email, perfil):
    senha = gerar_senha_temporaria()
    usuario = Usuario.objects.create_user(email=email, nome=nome, perfil=perfil, password=senha, trocar_senha=True)
    return usuario, senha


def redefinir_senha(usuario):
    """Gera nova senha temporária, exige troca no próximo acesso e encerra as sessões
    existentes (a troca do hash invalida as sessões do Django)."""
    senha = gerar_senha_temporaria()
    usuario.set_password(senha)
    usuario.trocar_senha = True
    usuario.tentativas_falhas = 0
    usuario.bloqueado_ate = None
    usuario.save(update_fields=["password", "trocar_senha", "tentativas_falhas", "bloqueado_ate"])
    return senha


def definir_acessos(usuario, clientes, processos):
    """Substitui as autorizações explícitas do usuário (RF09)."""
    from apps.clientes.models import AcessoCliente
    from apps.processos.models import AcessoProcesso

    with transaction.atomic():
        AcessoCliente.objects.filter(usuario=usuario).delete()
        AcessoProcesso.objects.filter(usuario=usuario).delete()
        AcessoCliente.objects.bulk_create([AcessoCliente(usuario=usuario, cliente=c) for c in clientes])
        AcessoProcesso.objects.bulk_create([AcessoProcesso(usuario=usuario, processo=p) for p in processos])
