"""Verificações de perfil executadas no servidor (RN07, RNF02).

A autenticação é exigida globalmente por ``LoginRequiredMiddleware``. Este
módulo acrescenta a verificação de perfil. A autorização por registro
(acesso a clientes e processos) será implementada junto com esses módulos.
"""
from functools import wraps

from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied


def tem_perfil(usuario, *perfis):
    return bool(
        usuario
        and usuario.is_authenticated
        and usuario.is_active
        and usuario.perfil in perfis
    )


def perfil_requerido(*perfis):
    """Decorador de view: responde 403 se o perfil não estiver entre ``perfis``."""

    def decorador(view):
        @wraps(view)
        def envoltorio(request, *args, **kwargs):
            if not tem_perfil(request.user, *perfis):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return envoltorio

    return decorador


class PerfilRequeridoMixin(AccessMixin):
    """Equivalente a ``perfil_requerido`` para views baseadas em classe."""

    perfis_permitidos = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not tem_perfil(request.user, *self.perfis_permitidos):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
