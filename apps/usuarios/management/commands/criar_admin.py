"""Cria uma conta de administrador com senha temporária aleatória.

Uso:
    docker compose exec web python manage.py criar_admin --email adm@exemplo.test --nome "Nome Fictício"

A senha é gerada aleatoriamente, exibida uma única vez e precisa ser trocada
no primeiro acesso (RF01). Nenhuma senha fixa é gravada no código.
"""
import secrets

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from apps.usuarios.models import Perfil, Usuario, UsuarioManager


class Command(BaseCommand):
    help = "Cria um administrador (ADM) com senha temporária aleatória."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--nome", required=True)

    def handle(self, *args, **opcoes):
        email = UsuarioManager.normalize_email(opcoes["email"])
        nome = opcoes["nome"].strip()
        try:
            validate_email(email)
        except ValidationError as erro:
            raise CommandError("E-mail inválido.") from erro
        if not nome:
            raise CommandError("Informe o nome.")
        if Usuario.objects.filter(email=email).exists():
            raise CommandError("Já existe um usuário com este e-mail.")

        senha = secrets.token_urlsafe(12)
        Usuario.objects.create_user(
            email=email, nome=nome, perfil=Perfil.ADM, password=senha, trocar_senha=True
        )
        self.stdout.write(self.style.SUCCESS(f"Administrador criado: {email}"))
        self.stdout.write(f"Senha temporária (exibida apenas agora): {senha}")
        self.stdout.write("A troca de senha será exigida no primeiro acesso.")
