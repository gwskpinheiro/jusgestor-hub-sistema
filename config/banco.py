"""Seleção do banco de dados por variáveis de ambiente.

DB_ALVO=local     PostgreSQL do Docker (desenvolvimento e testes) — padrão.
DB_ALVO=supabase  PostgreSQL do Supabase via Session Pooler, com SSL obrigatório
                  (banco do sistema publicado).

Os testes automatizados só podem rodar com DB_ALVO=local, em um host que não
seja do Supabase (ver ``verificar_banco_de_teste`` e config/test_runner.py).

As funções recebem o mapeamento de ambiente como parâmetro para poderem ser
testadas sem conexão real e sem ler o .env.
"""
from django.core.exceptions import ImproperlyConfigured

ALVO_LOCAL = "local"
ALVO_SUPABASE = "supabase"
ALVOS = (ALVO_LOCAL, ALVO_SUPABASE)

# "disable", "allow" e "prefer" permitiriam conexão sem criptografia.
SSLMODES_SEGUROS = ("require", "verify-ca", "verify-full")
DOMINIOS_SUPABASE = ("supabase.com", "supabase.co")


def _texto(amb, nome, padrao=""):
    return (amb.get(nome) or padrao).strip()


def _obrigatoria(amb, nome, remover_espacos=True):
    valor = amb.get(nome) or ""
    if remover_espacos:
        valor = valor.strip()
    if not valor:
        raise ImproperlyConfigured(f"Variável de ambiente obrigatória ausente: {nome}")
    return valor


def _porta(amb, nome, padrao):
    valor = _texto(amb, nome, padrao)
    if not valor.isdigit() or not 0 < int(valor) < 65536:
        raise ImproperlyConfigured(f"{nome} deve ser um número de porta válido.")
    return valor


def e_host_supabase(host):
    host = (host or "").strip().lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in DOMINIOS_SUPABASE)


def alvo_do_banco(amb):
    alvo = _texto(amb, "DB_ALVO", ALVO_LOCAL).lower()
    if alvo not in ALVOS:
        raise ImproperlyConfigured(f"DB_ALVO deve ser um destes valores: {', '.join(ALVOS)}.")
    return alvo


def config_local(amb):
    host = _texto(amb, "POSTGRES_HOST", "db")
    if e_host_supabase(host):
        raise ImproperlyConfigured(
            "POSTGRES_HOST aponta para o Supabase. Use DB_ALVO=supabase e as variáveis SUPABASE_DB_*."
        )
    nome = _obrigatoria(amb, "POSTGRES_DB")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": nome,
        "USER": _obrigatoria(amb, "POSTGRES_USER"),
        "PASSWORD": _obrigatoria(amb, "POSTGRES_PASSWORD", remover_espacos=False),
        "HOST": host,
        "PORT": _porta(amb, "POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        # Banco de teste criado e destruído pelo Django no mesmo servidor local.
        "TEST": {"NAME": f"test_{nome}"},
    }


def config_supabase(amb):
    raiz_ca = _texto(amb, "SUPABASE_DB_SSLROOTCERT")
    sslmode = _texto(amb, "SUPABASE_DB_SSLMODE").lower() or ("verify-full" if raiz_ca else "require")
    if sslmode not in SSLMODES_SEGUROS:
        raise ImproperlyConfigured(
            f"SUPABASE_DB_SSLMODE deve ser um destes valores: {', '.join(SSLMODES_SEGUROS)}."
        )
    if sslmode in ("verify-ca", "verify-full") and not raiz_ca:
        raise ImproperlyConfigured(
            f"SUPABASE_DB_SSLMODE={sslmode} exige SUPABASE_DB_SSLROOTCERT (certificado CA do Supabase)."
        )

    opcoes = {
        "sslmode": sslmode,
        "connect_timeout": 10,
        "application_name": "jusgestor-hub",
    }
    if raiz_ca:
        opcoes["sslrootcert"] = raiz_ca

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _texto(amb, "SUPABASE_DB_NAME", "postgres"),
        "USER": _obrigatoria(amb, "SUPABASE_DB_USER"),
        "PASSWORD": _obrigatoria(amb, "SUPABASE_DB_PASSWORD", remover_espacos=False),
        "HOST": _obrigatoria(amb, "SUPABASE_DB_HOST"),
        "PORT": _porta(amb, "SUPABASE_DB_PORT", "5432"),
        # Session Pooler: cada conexão do Django ocupa uma sessão do pooler,
        # então conexões persistentes funcionam; a verificação de saúde evita
        # reutilizar uma conexão encerrada pelo pooler.
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": opcoes,
    }


def configurar_banco(amb):
    if alvo_do_banco(amb) == ALVO_SUPABASE:
        return config_supabase(amb)
    return config_local(amb)


def verificar_banco_de_teste(alvo, databases):
    """Impede que a suíte de testes use qualquer banco que não seja o local."""
    if alvo != ALVO_LOCAL:
        raise ImproperlyConfigured(
            "Os testes automatizados só podem ser executados com DB_ALVO=local "
            "(PostgreSQL do Docker). Execução interrompida antes de conectar."
        )
    for alias, cfg in databases.items():
        if e_host_supabase(cfg.get("HOST")):
            raise ImproperlyConfigured(
                f"O banco '{alias}' aponta para o Supabase. Os testes só podem usar o PostgreSQL local."
            )
