from django.urls import path

from . import views

app_name = "usuarios"

urlpatterns = [
    path("entrar/", views.LoginView.as_view(), name="login"),
    path("sair/", views.LogoutView.as_view(), name="logout"),
    path("senha/", views.TrocaSenhaView.as_view(), name="trocar_senha"),
]
