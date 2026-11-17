from django.urls import path

from . import views

app_name = "agenda"

urlpatterns = [
    # Visualização principal: calendário (dia, semana, mês e ano).
    path("", views.calendario, name="calendario"),
    # Listagem com filtros (visualização secundária, "Lista").
    path("lista/", views.lista, name="lista"),
    path("novo/", views.novo, name="novo"),
    path("<int:pk>/", views.detalhe, name="detalhe"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/situacao/", views.alterar_situacao, name="situacao"),
]
