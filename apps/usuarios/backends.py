"""Autenticação por e-mail e senha com bloqueio temporário (RF01)."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.db import transaction
from django.utils import timezone

from .models import Usuario, UsuarioManager


class EmailBloqueioBackend(ModelBackend):
    """Autentica pelo e-mail e bloqueia a conta após falhas consecutivas.

    - Cinco falhas consecutivas (``LOGIN_MAX_TENTATIVAS``) bloqueiam o login
      por 15 minutos (``LOGIN_MINUTOS_BLOQUEIO``).
    - Durante o bloqueio nem a senha correta é aceita.
    - Um login bem-sucedido zera o contador.
    - Contas inativas nunca são autenticadas (``user_can_authenticate``).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = UsuarioManager.normalize_email(username or kwargs.get("email"))
        if not email or password is None:
            return None

        with transaction.atomic():
            try:
                usuario = Usuario.objects.select_for_update().get(email=email)
            except Usuario.DoesNotExist:
                # Executa o hash mesmo assim para reduzir a diferença de tempo
                # entre e-mail existente e inexistente.
                Usuario().set_password(password)
                return None

            agora = timezone.now()
            if usuario.esta_bloqueado(agora):
                return None

            campos = []
            if usuario.bloqueado_ate is not None:
                # O bloqueio anterior expirou: recomeça a contagem.
                usuario.bloqueado_ate = None
                usuario.tentativas_falhas = 0
                campos += ["bloqueado_ate", "tentativas_falhas"]

            if usuario.check_password(password):
                if not self.user_can_authenticate(usuario):
                    if campos:
                        usuario.save(update_fields=campos)
                    return None
                if usuario.tentativas_falhas:
                    usuario.tentativas_falhas = 0
                    campos.append("tentativas_falhas")
                if campos:
                    usuario.save(update_fields=sorted(set(campos)))
                return usuario

            usuario.tentativas_falhas += 1
            campos.append("tentativas_falhas")
            if usuario.tentativas_falhas >= settings.LOGIN_MAX_TENTATIVAS:
                usuario.bloqueado_ate = agora + timedelta(minutes=settings.LOGIN_MINUTOS_BLOQUEIO)
                campos.append("bloqueado_ate")
            usuario.save(update_fields=sorted(set(campos)))
            return None
