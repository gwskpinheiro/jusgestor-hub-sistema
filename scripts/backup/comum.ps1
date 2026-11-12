# Funções compartilhadas pelos scripts de backup e restauração (RNF07).
# Compatível com Windows PowerShell 5.1 e PowerShell 7.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Raiz = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Invoke-Docker {
    # Executa "docker <argumentos>" e interrompe se o código de saída não for 0.
    # Devolve a saída padrão (linhas). A saída de erro vai direto para o console.
    $saida = & docker @args
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao executar: docker $($args[0..([Math]::Min(2, $args.Count - 1))] -join ' ') ... (código $LASTEXITCODE)"
    }
    return $saida
}

function Write-Utf8 {
    param([string]$Caminho, [string[]]$Linhas)
    if ($null -eq $Linhas) { $Linhas = @() }
    [System.IO.File]::WriteAllLines($Caminho, $Linhas, $Utf8)
}

function Read-Linhas {
    param([string]$Caminho)
    return @([System.IO.File]::ReadAllLines($Caminho) | Where-Object { $_ -ne '' })
}

function Get-Sha256 {
    param([string]$Caminho)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Caminho).Hash.ToLowerInvariant()
}

function Assert-AmbienteLocal {
    # Recusa a execução se o projeto não estiver usando o PostgreSQL local do Docker.
    $arquivoEnv = Join-Path $Raiz '.env'
    $alvo = 'local'  # padrão de config/banco.py
    if (Test-Path -LiteralPath $arquivoEnv) {
        foreach ($linha in [System.IO.File]::ReadAllLines($arquivoEnv)) {
            if ($linha -match '^\s*DB_ALVO\s*=\s*(.*?)\s*$') {
                $alvo = $Matches[1].Trim('"', "'").ToLowerInvariant()
            }
        }
    }
    if ($alvo -ne 'local') {
        throw "DB_ALVO=$alvo no .env. Os scripts de backup só rodam com DB_ALVO=local."
    }
    $servicos = @(Invoke-Docker compose ps --status running --services)
    foreach ($servico in 'db', 'web') {
        if ($servicos -notcontains $servico) {
            throw "O serviço '$servico' do Docker Compose não está em execução. Rode: docker compose up -d"
        }
    }
    $alvoWeb = (@(Invoke-Docker compose exec -T web sh -c 'echo ${DB_ALVO:-local}') -join '').Trim()
    if ($alvoWeb -ne 'local') {
        throw "O contêiner web está com DB_ALVO=$alvoWeb. Os scripts de backup só rodam com DB_ALVO=local."
    }
}

function Get-ImpressaoOrigem {
    # Impressão digital do banco principal, em transação SOMENTE LEITURA.
    # Requer /tmp/jusgestor_verificar_banco.sql copiado para o contêiner db.
    return @(Invoke-Docker compose exec -T -e PGOPTIONS=-cdefault_transaction_read_only=on db `
            sh -c 'psql -X -q -At -U $POSTGRES_USER -d $POSTGRES_DB -f /tmp/jusgestor_verificar_banco.sql')
}

function Get-Campo {
    # Linha "tipo|nome|qtd|hash" -> campo pelo índice.
    param([string]$Linha, [int]$Indice)
    return ($Linha -split '\|')[$Indice]
}
