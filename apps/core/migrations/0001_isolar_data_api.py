"""Isola as tabelas do Django da Data API do Supabase.

Revoga, no schema public, os privilégios dos papéis anon e authenticated
(atuais e padrão para objetos futuros). Não altera o papel usado pelo Django.
Em bancos sem esses papéis (PostgreSQL local do Docker), não faz nada.

Ver apps/core/seguranca_banco.py e docs/supabase.md.
"""
from django.db import migrations

from apps.core.seguranca_banco import revogar_data_api


def isolar(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        revogar_data_api(cursor)


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("sessions", "0001_initial"),
        ("usuarios", "0001_initial"),
    ]

    operations = [
        # Sem reversão: devolver acesso à Data API não é uma operação desejada.
        migrations.RunPython(isolar, migrations.RunPython.noop),
    ]
