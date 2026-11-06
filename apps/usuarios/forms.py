from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Usuario, UsuarioManager


class LoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="E-mail",
        max_length=254,
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )
    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    error_messages = {
        "invalid_login": "E-mail ou senha inválidos. Verifique os dados e tente novamente.",
        "inactive": "Esta conta está inativa. Procure o administrador do escritório.",
        "bloqueado": (
            "Acesso bloqueado temporariamente após cinco tentativas sem sucesso. "
            "Aguarde 15 minutos e tente novamente."
        ),
    }

    def clean(self):
        email = self.cleaned_data.get("username")
        senha = self.cleaned_data.get("password")
        if email is not None and senha:
            self.user_cache = authenticate(self.request, username=email, password=senha)
            if self.user_cache is None:
                bloqueado = Usuario.objects.filter(
                    email=UsuarioManager.normalize_email(email),
                    bloqueado_ate__gt=timezone.now(),
                ).exists()
                if bloqueado:
                    raise ValidationError(self.error_messages["bloqueado"], code="bloqueado")
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


class TrocaSenhaForm(PasswordChangeForm):
    """Troca de senha com rótulos em português e campos padronizados."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Senha atual"
        self.fields["new_password1"].label = "Nova senha"
        self.fields["new_password2"].label = "Confirmação da nova senha"

    def save(self, commit=True):
        self.user.trocar_senha = False
        return super().save(commit=commit)
