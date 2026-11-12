#!/bin/sh
# Executado DENTRO do contêiner PostgreSQL DESCARTÁVEL pelo testar_restauracao.ps1
# (RNF07). Nunca é executado no contêiner "db" do sistema.
#
#   sh restaurar_teste.sh restaurar   restaura banco e documentos e gera as verificações
#   sh restaurar_teste.sh controle    altera a cópia restaurada de propósito e refaz as
#                                     verificações (controle negativo)
set -eu
D=/restauracao
export PGUSER=postgres

verificar() {
    sufixo="$1"
    psql -X -q -At -d restaurado -f "$D/verificar_banco.sql" > "$D/impressao_$sufixo.txt"
    (cd "$D/documentos" && find . -type f -exec sha256sum {} + | sort -k2) > "$D/documentos_$sufixo.sha256"
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
        pg_restore --exit-on-error --no-owner --no-privileges -d restaurado "$D/banco.dump"
        mkdir -p "$D/documentos"
        tar -xzf "$D/documentos.tar.gz" -C "$D/documentos"
        verificar restaurada
        ;;
    controle)
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
