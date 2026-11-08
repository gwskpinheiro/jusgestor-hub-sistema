"""Revoga os privilégios dos papéis da Data API do Supabase (anon, authenticated).

Uso:
    # apenas verificar
    docker compose run --rm -e DB_ALVO=supabase web python manage.py proteger_data_api --verificar
    # aplicar (executar ANTES do primeiro migrate em um Supabase novo)
    docker compose run --rm -e DB_ALVO=supabase web python manage.py proteger_data_api

Somente os papéis anon e authenticated são afetados. O papel usado pelo Django
não perde nenhuma permissão. Ver apps/core/seguranca_banco.py.
"""
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.core.seguranca_banco import (
    padroes_expostos,
    papeis_existentes,
    privilegios_expostos,
    revogar_data_api,
)


class Command(BaseCommand):
    help = "Revoga os privilégios de anon/authenticated (Data API do Supabase) no schema public."

    def add_arguments(self, parser):
        parser.add_argument("--verificar", action="store_true", help="Apenas mostra a situação, sem alterar.")

    def handle(self, *args, verificar=False, **opcoes):
        with transaction.atomic(), connection.cursor() as cursor:
            if verificar:
                cursor.execute("SET TRANSACTION READ ONLY")
            papeis = papeis_existentes(cursor)
            if not papeis:
                self.stdout.write("Papéis anon/authenticated não existem neste banco. Nada a fazer.")
                return
            if not verificar:
                revogar_data_api(cursor)
                self.stdout.write(f"Privilégios revogados de: {', '.join(papeis)}")
            padroes = padroes_expostos(cursor)
            tabelas = privilegios_expostos(cursor)

        self.stdout.write(f"Privilégios padrão ainda concedidos a anon/authenticated: {len(padroes)}")
        for tipo, papel in padroes:
            self.stdout.write(f"  tipo={tipo} papel={papel}")
        self.stdout.write(f"Tabelas acessíveis por anon/authenticated: {len(tabelas)}")
        for tabela, papel, privs in tabelas:
            self.stdout.write(f"  {tabela}: {papel} ({privs})")
        if not padroes and not tabelas:
            self.stdout.write(self.style.SUCCESS("Tabelas do Django isoladas da Data API."))
