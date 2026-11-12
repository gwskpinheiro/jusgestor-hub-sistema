#!/bin/sh
# Executado DENTRO do contêiner "web" pelo backup.ps1 (RNF07).
# Empacota os documentos anexados (somente leitura da pasta) e gera a lista
# SHA-256 de cada arquivo. Saída em /tmp; o backup.ps1 copia e apaga.
set -eu
ORIGEM="${DOCUMENTOS_ROOT:-/data/documentos}"
tar -czf /tmp/jusgestor_documentos.tar.gz -C "$ORIGEM" .
(cd "$ORIGEM" && find . -type f -exec sha256sum {} + | sort -k2) > /tmp/jusgestor_documentos.sha256
