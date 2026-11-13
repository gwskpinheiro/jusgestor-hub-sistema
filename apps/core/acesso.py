"""Autorização por registro (RN07).

Cada função devolve o conjunto de registros que o usuário pode consultar.
As views SEMPRE buscam registros a partir destes conjuntos, de modo que
conhecer o endereço (id) de um registro não autoriza a operação: um registro
fora do conjunto responde 404.

Regras (definidas pelo autor a partir do artigo):
- ADM acessa todos os registros.
- ADV acessa processos sob sua responsabilidade ou explicitamente autorizados
  (acesso_processo) e clientes autorizados (acesso_cliente).
- AST acessa clientes e processos autorizados pelo ADM.
- Acesso ao cliente NÃO libera automaticamente os processos desse cliente.
- Participar de um compromisso NÃO concede acesso ao processo vinculado.
"""
from django.db.models import Q

from apps.usuarios.models import Perfil


def e_adm(usuario):
    return bool(usuario.is_authenticated and usuario.is_active and usuario.perfil == Perfil.ADM)


def _ativo(usuario):
    return bool(usuario.is_authenticated and usuario.is_active)


def clientes_visiveis(usuario):
    from apps.clientes.models import AcessoCliente, Cliente

    qs = Cliente.objects.all()
    if e_adm(usuario):
        return qs
    if not _ativo(usuario):
        return qs.none()
    return qs.filter(pk__in=AcessoCliente.objects.filter(usuario=usuario).values("cliente_id"))


def ids_clientes_visiveis(usuario, ids):
    """Dos clientes informados, os que o usuário pode abrir (para decidir se o nome
    do cliente vira link). Apenas consulta clientes_visiveis: não concede acesso."""
    ids = {i for i in ids if i is not None}
    if not ids:
        return set()
    return set(clientes_visiveis(usuario).filter(pk__in=ids).values_list("pk", flat=True))


def processos_visiveis(usuario):
    from apps.processos.models import AcessoProcesso, Processo

    qs = Processo.objects.all()
    if e_adm(usuario):
        return qs
    if not _ativo(usuario):
        return qs.none()
    autorizados = AcessoProcesso.objects.filter(usuario=usuario).values("processo_id")
    if usuario.perfil == Perfil.ADV:
        return qs.filter(Q(responsavel=usuario) | Q(pk__in=autorizados))
    if usuario.perfil == Perfil.AST:
        return qs.filter(pk__in=autorizados)
    return qs.none()


def pode_editar_processo(usuario, processo):
    """ADM e ADV autorizados atualizam processos; AST apenas consulta (RF02)."""
    if processo.arquivado:
        return False
    if e_adm(usuario):
        return True
    return usuario.perfil == Perfil.ADV and processos_visiveis(usuario).filter(pk=processo.pk).exists()


def compromissos_visiveis(usuario):
    from apps.agenda.models import Compromisso, ParticipanteCompromisso

    qs = Compromisso.objects.all()
    if e_adm(usuario):
        return qs
    if not _ativo(usuario):
        return qs.none()
    participa = ParticipanteCompromisso.objects.filter(usuario=usuario).values("compromisso_id")
    return qs.filter(
        Q(responsavel=usuario) | Q(pk__in=participa) | Q(processo__in=processos_visiveis(usuario))
    )


def documentos_visiveis(usuario):
    """Documento de processo exige acesso ao processo; documento só de cliente
    exige acesso ao cliente."""
    from apps.documentos.models import Documento

    qs = Documento.objects.all()
    if e_adm(usuario):
        return qs
    if not _ativo(usuario):
        return qs.none()
    return qs.filter(
        Q(processo__in=processos_visiveis(usuario))
        | Q(processo__isnull=True, cliente__in=clientes_visiveis(usuario))
    )


def registros_hora_visiveis(usuario):
    """ADM consulta as horas da equipe; ADV, apenas as próprias (RN05)."""
    from apps.horas.models import RegistroHora

    qs = RegistroHora.objects.all()
    if e_adm(usuario):
        return qs
    if _ativo(usuario) and usuario.perfil == Perfil.ADV:
        return qs.filter(usuario=usuario)
    return qs.none()
