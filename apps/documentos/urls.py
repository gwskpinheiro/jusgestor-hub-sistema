from django.urls import path

from . import views

app_name = "documentos"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("novo/", views.novo, name="novo"),
    path("<int:pk>/", views.detalhe, name="detalhe"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/versoes/", views.nova_versao, name="nova_versao"),
    path("versoes/<int:pk>/baixar/", views.baixar, name="baixar"),
    path("versoes/<int:pk>/visualizar/", views.visualizar, name="visualizar"),
]
