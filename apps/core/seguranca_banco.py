"""Isolamento das tabelas do Django em relação à Data API do Supabase.

No Supabase, as tabelas criadas no schema ``public`` recebem por padrão todos
os privilégios para os papéis ``anon`` e ``authenticated``, usados pela API
REST (PostgREST). O JusGestor Hub não usa essa API: o acesso aos dados é feito
somente pelo Django, com autenticação e permissões próprias (RN07).

As funções abaixo revogam os privilégios SOMENTE desses dois papéis. O papel
que o Django usa para conectar (dono das tabelas) não é alterado. Em bancos sem
esses papéis (por exemplo, o PostgreSQL local do Docker), nada é executado.
"""

PAPEIS_DATA_API = ("anon", "authenticated")
SCHEMA = "public"


def papeis_existentes(cursor):
    cursor.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", [list(PAPEIS_DATA_API)])
    return sorted(linha[0] for linha in cursor.fetchall())


def comandos_revogacao(papeis):
    alvo = ", ".join(papeis)
    return [
        # Tabelas, sequências e funções que o papel conectado criar no futuro.
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} REVOKE ALL ON TABLES FROM {alvo}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} REVOKE ALL ON SEQUENCES FROM {alvo}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} REVOKE ALL ON FUNCTIONS FROM {alvo}",
        # Objetos que já existem no schema.
        f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM {alvo}",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {SCHEMA} FROM {alvo}",
        f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {SCHEMA} FROM {alvo}",
    ]


def revogar_data_api(cursor):
    """Revoga os privilégios de anon/authenticated. Retorna os papéis afetados."""
    papeis = papeis_existentes(cursor)
    if not papeis:
        return []
    for sql in comandos_revogacao(papeis):
        cursor.execute(sql)
    return papeis


def privilegios_expostos(cursor):
    """Lista (tabela, papel, privilégios) que anon/authenticated ainda têm no schema."""
    cursor.execute(
        """
        SELECT table_name, grantee, string_agg(privilege_type, ',' ORDER BY privilege_type)
        FROM information_schema.role_table_grants
        WHERE table_schema = %s AND grantee = ANY(%s)
        GROUP BY table_name, grantee
        ORDER BY table_name, grantee
        """,
        [SCHEMA, list(PAPEIS_DATA_API)],
    )
    return cursor.fetchall()


def padroes_expostos(cursor):
    """Privilégios padrão do papel conectado que ainda alcançam anon/authenticated."""
    cursor.execute(
        """
        SELECT d.defaclobjtype, a.grantee::regrole::text
        FROM pg_default_acl d
        JOIN pg_namespace n ON n.oid = d.defaclnamespace
        CROSS JOIN LATERAL aclexplode(d.defaclacl) a
        WHERE n.nspname = %s
          AND d.defaclrole = current_user::regrole
          AND a.grantee::regrole::text = ANY(%s)
        ORDER BY 1, 2
        """,
        [SCHEMA, list(PAPEIS_DATA_API)],
    )
    return cursor.fetchall()
