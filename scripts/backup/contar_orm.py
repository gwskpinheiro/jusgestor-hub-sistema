"""Conta os registros de cada modelo pelo ORM do Django (RNF07).

Executado pelo testar_restauracao.ps1 em um contêiner temporário ligado SOMENTE
ao banco descartável restaurado, para comprovar que a aplicação lê a cópia.
Saída: "tabela=quantidade" por linha. Somente leitura.
"""
import os
import sys

sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection  # noqa: E402

if connection.settings_dict["NAME"] != "restaurado":
    sys.exit("Recusado: este script só lê o banco descartável 'restaurado'.")

with connection.cursor() as cursor:
    cursor.execute("SET default_transaction_read_only = on")

for modelo in sorted(apps.get_models(), key=lambda m: m._meta.db_table):
    print(f"{modelo._meta.db_table}={modelo._default_manager.count()}")
