#!/bin/sh
# Executado DENTRO do contêiner PostgreSQL DESCARTÁVEL pelo testar_restauracao.ps1
# (RNF07). Nunca é executado no contêiner "db" do sistema.
#
#   sh restaurar_teste.sh restaurar             restaura banco e documentos e gera as verificações
#   sh restaurar_teste.sh legado <ordenacao>    impressão no formato 1 (cópias antigas), com a
#                                               ordenação de texto indicada (ex.: C, default)
#   sh restaurar_teste.sh controle [ordenacao]  altera a cópia restaurada de propósito e refaz as
#                                               verificações (controle negativo); com ordenação,
#                                               usa o formato 1
set -eu
D=/restauracao
export PGUSER=postgres
OPCOES=""

verificar() {
    sufixo="$1"
    # shellcheck disable=SC2086
    psql -X -q -At -d restaurado $OPCOES -f "$D/verificar_banco.sql" > "$D/impressao_$sufixo.txt"
    (cd "$D/documentos" && find . -type f -exec sha256sum {} + | sort -k2) > "$D/documentos_$sufixo.sha256"
    # Cópia só do banco (ex.: Supabase): os arquivos têm backup próprio no Storage.
    if [ ! -f "$D/documentos.tar.gz" ]; then
        : > "$D/versoes_$sufixo.txt"
        return
    fi
    # Cada versão registrada no banco restaurado deve ter seu arquivo, com o mesmo tamanho.
    psql -X -q -At -F ' ' -d restaurado \
        -c "SELECT caminho_arquivo, tamanho_bytes FROM versao_documento ORDER BY id" |
    while read -r caminho tamanho; do
        arquivo="$D/documentos/$caminho"
        if [ ! -f "$arquivo" ]; then
            echo "ausente"
        elif [ "$(stat -c %s "$arquivo")" != "$tamanho" ]; then
            echo "tamanho_diferente"
        else
            echo "ok"
        fi
    done > "$D/versoes_$sufixo.txt"
}

case "${1:-}" in
    restaurar)
        # Dumps de um esquema específico (--schema=public, cópia do Supabase) trazem
        # "CREATE SCHEMA public", que já existe num banco novo: esse item é retirado
        # da lista. Nas cópias completas do banco local ele não aparece.
        pg_restore -l "$D/banco.dump" | grep -v ' SCHEMA - public ' > "$D/itens.lista"
        pg_restore --exit-on-error --no-owner --no-privileges -L "$D/itens.lista" -d restaurado "$D/banco.dump"
        mkdir -p "$D/documentos"
        if [ -f "$D/documentos.tar.gz" ]; then
            tar -xzf "$D/documentos.tar.gz" -C "$D/documentos"
        fi
        verificar restaurada
        ;;
    legado)
        psql -X -q -At -d restaurado -v legado=1 -v ordenacao="${2:?}" -f "$D/verificar_banco.sql" \
            > "$D/impressao_legado.txt"
        ;;
    controle)
        if [ -n "${2:-}" ]; then
            OPCOES="-v legado=1 -v ordenacao=$2"
        fi
        # Altera UM registro e (se houver) UM arquivo, somente na cópia descartável.
        psql -X -q -d restaurado -c \
            "UPDATE django_migrations SET name = name || '_alterado' WHERE id = (SELECT min(id) FROM django_migrations)"
        primeiro=$(cd "$D/documentos" && find . -type f | sort | head -n 1)
        if [ -n "$primeiro" ]; then
            printf 'x' >> "$D/documentos/$primeiro"
        fi
        verificar controle
        ;;
    *)
        echo "uso: sh restaurar_teste.sh restaurar|controle" >&2
        exit 2
        ;;
esac
