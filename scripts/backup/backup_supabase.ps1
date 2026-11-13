<#
.SYNOPSIS
    Cópia de segurança do banco PostgreSQL do SUPABASE (somente leitura) (RNF07).

.DESCRIPTION
    Executa pg_dump num contêiner PostgreSQL descartável, com as variáveis
    SUPABASE_DB_* do .env (as credenciais ficam dentro do contêiner e nunca são
    exibidas). Copia o esquema "public" (tabelas do sistema) e cria uma pasta
    nova, que nunca sobrescreve cópias anteriores:

      backups\supabase\AAAAMMDD-HHMMSS\
        banco.dump            pg_dump -Fc --schema=public --no-owner --no-privileges
        impressao_origem.txt  contagem e hash de cada tabela, estrutura e órfãos
                              (tirada antes e depois do dump; precisam ser iguais)
        manifesto.txt         origem, versões e SHA-256 dos arquivos

    Somente leitura: a impressão digital roda em transação READ ONLY e o
    pg_dump usa transação REPEATABLE READ, READ ONLY. Nada é gravado no Supabase.

    Para restaurar e conferir (SEMPRE num PostgreSQL local descartável):
      powershell -ExecutionPolicy Bypass -File scripts\backup\testar_restauracao.ps1 -Backup <pasta>

.PARAMETER Projeto
    Referência do projeto Supabase (a parte depois de "postgres." em
    SUPABASE_DB_USER). Obrigatória: confirma explicitamente o backup remoto.

.PARAMETER Ensaio
    Executa o MESMO procedimento contra o PostgreSQL LOCAL do Docker, sem
    acessar o Supabase (pasta backups\supabase-ensaio\).

.PARAMETER Destino
    Pasta base (padrão: backups\supabase ou backups\supabase-ensaio).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\backup\backup_supabase.ps1 -Ensaio
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\backup\backup_supabase.ps1 -Projeto <referencia-do-projeto>
#>
param([string]$Projeto, [switch]$Ensaio, [string]$Destino)

. (Join-Path $PSScriptRoot 'comum.ps1')

function Read-Env {
    # Lê o .env sem exibir nada. Devolve um dicionário nome -> valor.
    $valores = @{}
    $arquivo = Join-Path $Raiz '.env'
    if (-not (Test-Path -LiteralPath $arquivo)) { throw 'Arquivo .env não encontrado.' }
    foreach ($linha in [System.IO.File]::ReadAllLines($arquivo)) {
        if ($linha -match '^\s*([A-Z0-9_]+)\s*=(.*)$') { $valores[$Matches[1]] = $Matches[2].Trim().Trim('"', "'") }
    }
    return $valores
}

function Ocultar {
    param([string]$Texto, [hashtable]$Env)
    foreach ($nome in 'SUPABASE_DB_PASSWORD', 'POSTGRES_PASSWORD', 'SUPABASE_STORAGE_SECRET_ACCESS_KEY',
                      'SUPABASE_STORAGE_ACCESS_KEY_ID', 'DJANGO_SECRET_KEY') {
        $segredo = $Env[$nome]
        if ($segredo) { $Texto = $Texto.Replace($segredo, '***') }
    }
    return $Texto
}

Push-Location $Raiz
$pasta = $null
$concluido = $false
$env_ = @{}
try {
    $env_ = Read-Env
    $imagem = ([regex]::Match([System.IO.File]::ReadAllText((Join-Path $Raiz 'docker-compose.yml')), 'image:\s*(postgres:\S+)')).Groups[1].Value
    if (-not $imagem) { throw 'Imagem do PostgreSQL não encontrada no docker-compose.yml.' }
    $argumentosRede = @()
    $montagens = @('-v', "$(Join-Path $PSScriptRoot '.'):/scripts:ro")

    if ($Ensaio) {
        if ($Projeto) { throw 'Use -Ensaio OU -Projeto, não os dois.' }
        Assert-AmbienteLocal
        $idDb = (@(Invoke-Docker compose ps -q db) -join '').Trim()
        $rede = (@(Invoke-Docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' $idDb) -join '').Trim()
        $argumentosRede = @('--network', $rede)
        $origem = 'ensaio'
        $descricao = 'PostgreSQL LOCAL do Docker (ensaio; Supabase não acessado)'
        $base = if ($Destino) { $Destino } else { Join-Path $Raiz 'backups\supabase-ensaio' }
    } else {
        # --- Proteções antes de qualquer conexão ---------------------------
        $servidor = "$($env_['SUPABASE_DB_HOST'])".ToLowerInvariant()
        if ($servidor -notmatch '^[a-z0-9.-]+\.supabase\.(com|co)$') {
            throw 'SUPABASE_DB_HOST não é um host do Supabase. Backup remoto não executado.'
        }
        $usuario = "$($env_['SUPABASE_DB_USER'])"
        if ($usuario -notmatch '^postgres\.([a-z0-9]+)$') {
            throw 'SUPABASE_DB_USER deve ter o formato postgres.<referencia-do-projeto> (Session Pooler).'
        }
        $referencia = $Matches[1]
        if (-not $Projeto) {
            throw 'Backup remoto não executado: confirme com -Projeto <referencia-do-projeto>.'
        }
        if ($Projeto -ne $referencia) {
            throw 'Backup remoto não executado: -Projeto não corresponde ao projeto configurado em SUPABASE_DB_USER.'
        }
        if (-not $env_['SUPABASE_DB_PASSWORD']) { throw 'Preencha SUPABASE_DB_PASSWORD no .env.' }
        $ssl = if ($env_['SUPABASE_DB_SSLMODE']) { $env_['SUPABASE_DB_SSLMODE'] } else { 'require' }
        if ($ssl -notin 'require', 'verify-ca', 'verify-full') {
            throw "SUPABASE_DB_SSLMODE=$ssl não é seguro. Use require, verify-ca ou verify-full."
        }
        if ($ssl -like 'verify-*') {
            $certificado = $env_['SUPABASE_DB_SSLROOTCERT']
            $local = if ($certificado) { Join-Path (Join-Path $Raiz 'certs') (Split-Path $certificado -Leaf) } else { $null }
            if (-not $local -or -not (Test-Path -LiteralPath $local)) {
                throw "SUPABASE_DB_SSLMODE=$ssl exige o certificado em certs\ (SUPABASE_DB_SSLROOTCERT)."
            }
            $montagens += @('-v', "$(Join-Path $Raiz 'certs'):/certs:ro")
        }
        $origem = 'supabase'
        $descricao = "Supabase (projeto $referencia, Session Pooler, sslmode=$ssl)"
        $base = if ($Destino) { $Destino } else { Join-Path $Raiz 'backups\supabase' }
    }

    # --- Pasta nova (nunca sobrescreve) --------------------------------------
    if (-not (Test-Path -LiteralPath $base)) { New-Item -ItemType Directory -Path $base | Out-Null }
    $pasta = Join-Path (Resolve-Path -LiteralPath $base).Path (Get-Date -Format 'yyyyMMdd-HHmmss')
    if (Test-Path -LiteralPath $pasta) { $pasta = $null; throw 'Já existe uma cópia com este horário; tente de novo em alguns segundos.' }
    New-Item -ItemType Directory -Path $pasta | Out-Null
    Write-Host "Origem: $descricao"
    Write-Host "Cópia em: $pasta"

    # --- pg_dump no contêiner descartável -------------------------------------
    $argumentos = @('run', '--rm', '--env-file', (Join-Path $Raiz '.env'), '-e', "ORIGEM=$origem") + $argumentosRede +
        $montagens + @('-v', "${pasta}:/saida", $imagem, 'sh', '/scripts/dump_supabase.sh')
    # Avisos do pg_dump vão para o stderr; no PowerShell 5.1 isso não pode interromper o script.
    $ErrorActionPreference = 'Continue'
    $saida = & docker @argumentos 2>&1 | ForEach-Object { Ocultar "$_" $env_ }
    $codigo = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $saida | ForEach-Object { if ($_ -and $_ -notlike 'consistente_na_tentativa=*') { Write-Host "  $_" } }
    if ($codigo -ne 0) { throw "pg_dump não concluído (código $codigo). Nenhuma cópia foi mantida." }
    $tentativa = (@($saida | Where-Object { $_ -like 'consistente_na_tentativa=*' }) -join '').Split('=')[-1]

    # --- Manifesto ------------------------------------------------------------
    $dump = Join-Path $pasta 'banco.dump'
    $impressao = Join-Path $pasta 'impressao_origem.txt'
    $tabelas = @(Read-Linhas $impressao | Where-Object { $_ -like 'tabela|*' })
    if ($tabelas.Count -eq 0) { throw 'A impressão digital da origem não tem tabelas; cópia descartada.' }
    $registros = 0
    foreach ($t in $tabelas) { $registros += [int64](Get-Campo $t 2) }
    $versaoServidor = (Read-Linhas (Join-Path $pasta 'versao_servidor.txt') -join '').Trim()
    $versaoDump = (Read-Linhas (Join-Path $pasta 'versao_pg_dump.txt') -join '').Trim()
    Remove-Item -LiteralPath (Join-Path $pasta 'versao_servidor.txt'), (Join-Path $pasta 'versao_pg_dump.txt')
    $manifesto = @(
        'JusGestor Hub - copia de seguranca do banco (RNF07)',
        "criado_em=$(Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')",
        "tipo=banco",
        "origem=$origem",
        "descricao=$descricao",
        "esquema=public",
        "servidor=PostgreSQL $versaoServidor",
        "pg_dump=$versaoDump",
        "consistente_na_tentativa=$tentativa",
        "tabelas=$($tabelas.Count)",
        "registros=$registros",
        "documentos=nao incluidos (Supabase Storage: exportar_documentos)",
        "sha256_banco=$(Get-Sha256 $dump)",
        "sha256_impressao=$(Get-Sha256 $impressao)"
    )
    Write-Utf8 (Join-Path $pasta 'manifesto.txt') $manifesto
    $concluido = $true

    # Pasta acessível somente ao usuário atual (melhor esforço no Windows): a
    # permissão é definida na pasta e herdada pelos arquivos dela.
    & icacls $pasta /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" /Q | Out-Null
    $protegida = $LASTEXITCODE -eq 0
    if ($protegida) { Get-Content -LiteralPath (Join-Path $pasta 'manifesto.txt') -TotalCount 1 | Out-Null }

    Write-Host ''
    Write-Host 'Cópia do banco concluída (somente leitura na origem).' -ForegroundColor Green
    Write-Host "  Origem:  $descricao"
    Write-Host "  Banco:   $($tabelas.Count) tabelas, $registros registros, dump consistente na tentativa $tentativa"
    Write-Host ("  Arquivo: banco.dump {0:N1} KiB" -f ((Get-Item -LiteralPath $dump).Length / 1KB))
    Write-Host "  Pasta:   $pasta$(if ($protegida) { ' (acesso restrito ao usuário atual)' })"
    Write-Host ''
    Write-Host 'Próximo passo: restaurar e conferir num PostgreSQL local descartável:'
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\backup\testar_restauracao.ps1 -Backup `"$pasta`""
}
catch {
    Write-Host (Ocultar "Erro: $($_.Exception.Message)" $env_) -ForegroundColor Red
    exit 1
}
finally {
    if (-not $concluido -and $pasta -and (Test-Path -LiteralPath $pasta)) {
        Remove-Item -LiteralPath $pasta -Recurse -Force   # cópia incompleta não fica parecendo válida
    }
    Pop-Location
}
