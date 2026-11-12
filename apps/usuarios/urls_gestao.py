from django.urls import path

from . import views_gestao as views

app_name = "gestao_usuarios"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("novo/", views.novo, name="novo"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/senha/", views.redefinir_senha, name="redefinir_senha"),
    path("<int:pk>/acessos/", views.acessos, name="acessos"),
]
