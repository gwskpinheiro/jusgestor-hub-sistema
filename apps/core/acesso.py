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
