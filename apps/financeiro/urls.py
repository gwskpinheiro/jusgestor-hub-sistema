from django.urls import path

from . import views

app_name = "financeiro"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("novo/", views.novo, name="novo"),
    path("cobrar-horas/", views.cobrar_horas, name="cobrar_horas"),
    path("<int:pk>/", views.detalhe, name="detalhe"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/quitar/", views.quitar, name="quitar"),
    path("<int:pk>/cancelar/", views.cancelar, name="cancelar"),
]
