"""Tabelas ``cliente`` e ``acesso_cliente`` (Figura 3)."""
import re

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


def so_digitos(valor):
    return re.sub(r"\D", "", valor or "")


class Cliente(models.Model):
    nome = models.CharField("nome", max_length=200)
    # Somente dígitos: 11 (CPF) ou 14 (CNPJ). A formatação é feita na exibição.
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=14, null=True, blank=True)
    email = models.EmailField("e-mail", max_length=254, null=True, blank=True)
    telefone = models.CharField("telefone", max_length=20, null=True, blank=True)
    endereco = models.TextField("endereço", null=True, blank=True)
    observacoes = models.TextField("observações", null=True, blank=True)
    arquivado = models.BooleanField("arquivado", default=False)
    criado_em = models.DateTimeField("criado em", default=timezone.now, editable=False)

    class Meta:
        db_table = "cliente"
        ordering = ["nome"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cpf_cnpj__isnull=True) | models.Q(cpf_cnpj__regex=r"^([0-9]{11}|[0-9]{14})$"),
                name="cliente_cpf_cnpj_digitos",
            ),
        ]

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return reverse("clientes:detalhe", args=[self.pk])


class AcessoCliente(models.Model):
    """Autorização de um usuário (ADV/AST) sobre um cliente (RF09)."""

    pk = models.CompositePrimaryKey("usuario_id", "cliente_id")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="acessos_cliente")
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="acessos")

    class Meta:
        db_table = "acesso_cliente"
