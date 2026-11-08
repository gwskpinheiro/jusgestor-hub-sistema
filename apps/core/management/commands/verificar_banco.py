"""Testa a conexão com o banco configurado, sem alterar nada.

Uso (Supabase, sem trocar o banco do servidor de desenvolvimento):
    docker compose run --rm -e DB_ALVO=supabase web python manage.py verificar_banco

Tudo é executado dentro de uma transação somente leitura. O comando não aplica
migrações, não cria tabelas e não exibe usuário nem senha.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from config.banco import ALVO_SUPABASE


class Command(BaseCommand):
    help = "Testa a conexão com o banco configurado (somente leitura)."

    def handle(self, *args, **opcoes):
        cfg = connection.settings_dict
        self.stdout.write(f"Alvo: {settings.BANCO_ALVO}")
        self.stdout.write(f"Servidor: {cfg['HOST']}:{cfg['PORT']}  Banco: {cfg['NAME']}")

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                    cursor.execute("SELECT current_setting('server_version')")
                    versao = cursor.fetchone()[0]
                ssl_ativo = bool(connection.connection.pgconn.ssl_in_use)
                tabelas = connection.introspection.table_names()
                executor = MigrationExecutor(connection)
                pendentes = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except DatabaseError as erro:
            # A mensagem do driver não inclui a senha; o tipo do erro ajuda no diagnóstico.
            raise CommandError(f"Falha na conexão ({type(erro).__name__}): {erro}".strip()) from erro

        sslmode = cfg.get("OPTIONS", {}).get("sslmode", "padrão do servidor")
        self.stdout.write(f"PostgreSQL: {versao}")
        self.stdout.write(f"SSL: {'ativo' if ssl_ativo else 'inativo'} (sslmode={sslmode})")
        self.stdout.write(f"Tabelas visíveis: {len(tabelas)}")
        self.stdout.write(f"Migrações pendentes: {len(pendentes)}")

        if settings.BANCO_ALVO == ALVO_SUPABASE and not ssl_ativo:
            raise CommandError("A conexão com o Supabase não está usando SSL.")
        self.stdout.write(self.style.SUCCESS("Conexão OK. Nenhuma alteração foi feita."))
