<#
.SYNOPSIS
    Cópia de segurança do banco PostgreSQL LOCAL e dos documentos anexados (RNF07).

.DESCRIPTION
    Cria uma pasta datada com:
      banco.dump            pg_dump em formato custom (-Fc), restaurável com pg_restore
      documentos.tar.gz     todos os arquivos do volume de documentos
      documentos.sha256     SHA-256 de cada arquivo de documento
      impressao_origem.txt  contagem e hash de cada tabela, estrutura e órfãos no momento da cópia
      manifesto.txt         data, versões e SHA-256 dos arquivos da cópia

    O banco principal é apenas LIDO. A impressão digital é tirada antes e
    depois do pg_dump; se o banco mudar no meio, a cópia é refeita (até 3 vezes).

    Só roda com DB_ALVO=local e com os serviços db e web em execução. Não acessa
    Supabase nem Render. A pasta backups\ está no .gitignore e no .dockerignore.

    A cópia contém dados pessoais e hashes de senha: guarde-a em local protegido.

.PARAMETER Destino
    Pasta onde a cópia será criada. Padrão: backups\ na raiz do projeto.
    Para a "cópia independente" do RNF07, use um disco externo ou copie a
    pasta gerada para outro dispositivo.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\backup\backup.ps1
#>
param([string]$Destino)

. (Join-Path $PSScriptRoot 'comum.ps1')

Push-Location $Raiz
$pasta = $null
$concluido = $false
try {
    Assert-AmbienteLocal
    if (-not $Destino) { $Destino = Join-Path $Raiz 'backups' }
    if (-not (Test-Path -LiteralPath $Destino)) { New-Item -ItemType Directory -Path $Destino | Out-Null }
    $Destino = (Resolve-Path -LiteralPath $Destino).Path
    $pasta = Join-Path $Destino (Get-Date -Format 'yyyyMMdd-HHmmss')
    New-Item -ItemType Directory -Path $pasta | Out-Null
    Write-Host "Cópia em: $pasta"

    Invoke-Docker compose cp scripts/backup/verificar_banco.sql db:/tmp/jusgestor_verificar_banco.sql | Out-Null

    # 1. Banco: impressão digital antes e depois do pg_dump, para garantir que correspondem.
    $antes = @()
    $consistente = $false
    for ($tentativa = 1; $tentativa -le 3 -and -not $consistente; $tentativa++) {
        $antes = @(Get-ImpressaoOrigem)
        Invoke-Docker compose exec -T db sh -c 'pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc -f /tmp/jusgestor_banco.dump' | Out-Null
        $depois = @(Get-ImpressaoOrigem)
        $mudou = @(Compare-Object -CaseSensitive $antes $depois | ForEach-Object { Get-Campo $_.InputObject 1 } | Sort-Object -Unique)
        if ($mudou.Count -eq 0) {
            $consistente = $true
        } else {
            Write-Warning "O banco mudou durante a cópia (tentativa $tentativa): $($mudou -join ', ')"
        }
    }
    if (-not $consistente) {
        throw 'O banco continuou mudando durante a cópia. Pare de usar o sistema no navegador e tente de novo.'
    }
    $dump = Join-Path $pasta 'banco.dump'
    Invoke-Docker compose cp db:/tmp/jusgestor_banco.dump $dump | Out-Null
    Write-Utf8 (Join-Path $pasta 'impressao_origem.txt') $antes

    # 2. Documentos: depois do banco, para que todo arquivo citado no dump já esteja
    #    na pasta (o sistema não apaga arquivos de versões).
    Invoke-Docker compose exec -T web sh /app/scripts/backup/empacotar_documentos.sh | Out-Null
    $pacote = Join-Path $pasta 'documentos.tar.gz'
    $listaDocs = Join-Path $pasta 'documentos.sha256'
    Invoke-Docker compose cp web:/tmp/jusgestor_documentos.tar.gz $pacote | Out-Null
    Invoke-Docker compose cp web:/tmp/jusgestor_documentos.sha256 $listaDocs | Out-Null

    # 3. Manifesto.
    $tabelas = @($antes | Where-Object { $_ -like 'tabela|*' })
    $registros = 0
    foreach ($t in $tabelas) { $registros += [int64](Get-Campo $t 2) }
    $arquivos = @(Read-Linhas $listaDocs).Count
    $versaoPgDump = (@(Invoke-Docker compose exec -T db pg_dump --version) -join '').Trim()
    $manifesto = @(
        'JusGestor Hub - copia de seguranca (RNF07)',
        "criado_em=$(Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')",
        'origem=PostgreSQL local (Docker Compose, servico db) e volume de documentos; DB_ALVO=local',
        "pg_dump=$versaoPgDump",
        "tabelas=$($tabelas.Count)",
        "registros=$registros",
        "arquivos_documentos=$arquivos",
        "sha256_banco=$(Get-Sha256 $dump)",
        "sha256_documentos=$(Get-Sha256 $pacote)",
        "sha256_lista_documentos=$(Get-Sha256 $listaDocs)",
        "sha256_impressao=$(Get-Sha256 (Join-Path $pasta 'impressao_origem.txt'))"
    )
    Write-Utf8 (Join-Path $pasta 'manifesto.txt') $manifesto
    $concluido = $true

    $tamanho = { param($p) '{0:N1} KiB' -f ((Get-Item -LiteralPath $p).Length / 1KB) }
    Write-Host ''
    Write-Host 'Cópia concluída.' -ForegroundColor Green
    Write-Host "  Banco:      $($tabelas.Count) tabelas, $registros registros, banco.dump $(& $tamanho $dump)"
    Write-Host "  Documentos: $arquivos arquivo(s), documentos.tar.gz $(& $tamanho $pacote)"
    Write-Host "  Pasta:      $pasta"
    Write-Host ''
    Write-Host 'Próximos passos: teste a restauração e guarde uma cópia em outro dispositivo:'
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\backup\testar_restauracao.ps1 -Backup `"$pasta`""
}
finally {
    # Remove os temporários dos contêineres, mesmo em caso de erro.
    & docker compose exec -T db rm -f /tmp/jusgestor_banco.dump /tmp/jusgestor_verificar_banco.sql | Out-Null
    & docker compose exec -T web rm -f /tmp/jusgestor_documentos.tar.gz /tmp/jusgestor_documentos.sha256 | Out-Null
    if (-not $concluido -and $pasta -and (Test-Path -LiteralPath $pasta)) {
        Remove-Item -LiteralPath $pasta -Recurse -Force   # cópia incompleta não fica parecendo válida
    }
    Pop-Location
}
