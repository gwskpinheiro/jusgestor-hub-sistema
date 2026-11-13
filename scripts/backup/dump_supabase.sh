#!/bin/sh
# Executado DENTRO de um contêiner PostgreSQL descartável pelo backup_supabase.ps1 (RNF07).
#
# ORIGEM=supabase  banco do Supabase (Session Pooler, SSL obrigatório), com as
#                  variáveis SUPABASE_DB_* recebidas do .env pelo --env-file
# ORIGEM=ensaio    PostgreSQL LOCAL do Docker (mesmo procedimento, para validar
#                  a rotina sem acessar o Supabase)
#
# Somente leitura na origem:
# - a impressão digital roda em BEGIN ... READ ONLY (verificar_banco.sql);
# - o pg_dump usa, por padrão, uma transação REPEATABLE READ, READ ONLY;
# - nenhum comando de escrita é enviado ao servidor.
# Apenas o esquema "public" (tabelas do sistema) é copiado; os esquemas internos
# do Supabase (auth, storage, realtime...) não fazem parte do sistema.
# Credenciais nunca são impressas.
set -eu
S=/saida

case "${ORIGEM:-}" in
    supabase)
        export PGHOST="${SUPABASE_DB_HOST:?}" PGPORT="${SUPABASE_DB_PORT:-5432}" \
            PGDATABASE="${SUPABASE_DB_NAME:-postgres}" PGUSER="${SUPABASE_DB_USER:?}" \
            PGPASSWORD="${SUPABASE_DB_PASSWORD:?}" PGSSLMODE="${SUPABASE_DB_SSLMODE:-require}"
        case "$PGSSLMODE" in
            require|verify-ca|verify-full) ;;
            *) echo "SUPABASE_DB_SSLMODE inseguro: use require, verify-ca ou verify-full." >&2; exit 3 ;;
        esac
        if [ -n "${SUPABASE_DB_SSLROOTCERT:-}" ]; then
            export PGSSLROOTCERT="/certs/$(basename "$SUPABASE_DB_SSLROOTCERT")"
        fi
        ;;
    ensaio)
        export PGHOST=db PGPORT=5432 PGDATABASE="${POSTGRES_DB:?}" PGUSER="${POSTGRES_USER:?}" \
            PGPASSWORD="${POSTGRES_PASSWORD:?}" PGSSLMODE=disable
        ;;
    *)
        echo "ORIGEM deve ser supabase ou ensaio." >&2
        exit 2
        ;;
esac
# Variáveis que não são necessárias aqui saem do ambiente do processo.
unset SUPABASE_DB_PASSWORD POSTGRES_PASSWORD SUPABASE_STORAGE_SECRET_ACCESS_KEY \
      SUPABASE_STORAGE_ACCESS_KEY_ID DJANGO_SECRET_KEY 2>/dev/null || true
export PGAPPNAME=jusgestor-backup-rnf07 PGCONNECT_TIMEOUT=20

psql -X -q -At -v ON_ERROR_STOP=1 -c "SELECT current_setting('server_version')" > "$S/versao_servidor.txt"
pg_dump --version > "$S/versao_pg_dump.txt"

tentativa=1
while [ "$tentativa" -le 3 ]; do
    psql -X -q -At -v ON_ERROR_STOP=1 -f /scripts/verificar_banco.sql > "$S/impressao_antes.txt"
    pg_dump --format=custom --schema=public --no-owner --no-privileges --file="$S/banco.dump.parcial"
    psql -X -q -At -v ON_ERROR_STOP=1 -f /scripts/verificar_banco.sql > "$S/impressao_depois.txt"
    if cmp -s "$S/impressao_antes.txt" "$S/impressao_depois.txt"; then
        mv "$S/banco.dump.parcial" "$S/banco.dump"
        mv "$S/impressao_antes.txt" "$S/impressao_origem.txt"
        rm -f "$S/impressao_depois.txt"
        echo "consistente_na_tentativa=$tentativa"
        exit 0
    fi
    echo "O banco mudou durante a cópia (tentativa $tentativa); repetindo." >&2
    tentativa=$((tentativa + 1))
done
rm -f "$S/banco.dump.parcial" "$S/impressao_antes.txt" "$S/impressao_depois.txt"
echo "O banco continuou mudando durante a cópia; nenhum dump foi mantido." >&2
exit 4
