from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy

from .forms import LoginForm, TrocaSenhaForm


class LoginView(auth_views.LoginView):
    template_name = "usuarios/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    """Logout apenas por POST (proteção CSRF)."""


class TrocaSenhaView(auth_views.PasswordChangeView):
    template_name = "usuarios/trocar_senha.html"
    form_class = TrocaSenhaForm
    success_url = reverse_lazy("core:painel")

    def form_valid(self, form):
        resposta = super().form_valid(form)
        messages.success(self.request, "Senha alterada com sucesso.")
        return resposta
