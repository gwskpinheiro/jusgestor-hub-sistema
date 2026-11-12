"""Itens de navegação e perfis que podem vê-los.

Os perfis seguem o diagrama de casos de uso (Figura 1) e as regras RN03,
RN05, RN06 e RN09. Esconder um item não substitui a verificação no servidor:
cada view também verifica o perfil (RN07).

``url`` = None indica módulo ainda não implementado nesta fase.
"""
from dataclasses import dataclass

from apps.usuarios.models import Perfil

TODOS = (Perfil.ADM, Perfil.ADV, Perfil.AST)


@dataclass(frozen=True)
class ItemMenu:
    rotulo: str
    icone: str
    perfis: tuple
    url: str | None = None


ITENS_MENU = (
    ItemMenu("Painel", "painel", TODOS, "core:painel"),
    ItemMenu("Processos", "processos", TODOS, "processos:lista"),
    ItemMenu("Clientes", "clientes", TODOS, "clientes:lista"),
    ItemMenu("Agenda", "agenda", TODOS, "agenda:lista"),
    ItemMenu("Financeiro", "financeiro", (Perfil.ADM,)),
    ItemMenu("Documentos", "documentos", TODOS, "documentos:lista"),
    ItemMenu("Horas trabalhadas", "horas", (Perfil.ADM, Perfil.ADV), "horas:lista"),
    ItemMenu("Relatórios", "relatorios", (Perfil.ADM, Perfil.ADV)),
    ItemMenu("Usuários", "usuarios", (Perfil.ADM,)),
)


def itens_para(usuario):
    if not usuario.is_authenticated:
        return []
    return [item for item in ITENS_MENU if usuario.perfil in item.perfis]
