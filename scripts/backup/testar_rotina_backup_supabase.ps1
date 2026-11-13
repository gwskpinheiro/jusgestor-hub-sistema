<#
.SYNOPSIS
    Valida a rotina de backup do banco do Supabase SEM acessar o Supabase (RNF07).

.DESCRIPTION
    1. Proteções: backup_supabase.ps1 recusa executar sem -Projeto, com -Projeto
       diferente do configurado e com -Ensaio junto de -Projeto (nada é criado).
    2. Ensaio: o mesmo procedimento do backup remoto contra o PostgreSQL LOCAL.
    3. Restauração da cópia do ensaio num PostgreSQL local descartável
       (testar_restauracao.ps1), com comparação completa e controle negativo.
    4. Não sobrescrita: um segundo ensaio cria outra pasta e a primeira cópia
       continua idêntica.
    5. Cópia adulterada (1 byte do dump alterado) é recusada antes da restauração.
    Ao final, remove as pastas de ensaio criadas (use -Manter para guardá-las).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\backup\testar_rotina_backup_supabase.ps1
#>
param([switch]$Manter)

. (Join-Path $PSScriptRoot 'comum.ps1')

$falhas = 0
$criadas = New-Object System.Collections.Generic.List[string]
$script = Join-Path $PSScriptRoot 'backup_supabase.ps1'
$restauracao = Join-Path $PSScriptRoot 'testar_restauracao.ps1'
$baseRemota = Join-Path $Raiz 'backups\supabase'
$baseEnsaio = Join-Path $Raiz 'backups\supabase-ensaio'

function Resultado {
    param([bool]$Ok, [string]$Texto)
    if (-not $Ok) { $script:falhas++ }
    Write-Host "$(if ($Ok) { '[OK]   ' } else { '[FALHA]' }) $Texto" -ForegroundColor $(if ($Ok) { 'Green' } else { 'Red' })
}

function Executar {
    # Roda um script em outro processo; devolve @{ codigo; saida }.
    param([string]$Arquivo, [string[]]$Argumentos)
    $ErrorActionPreference = 'Continue'
    $saida = & powershell -NoProfile -ExecutionPolicy Bypass -File $Arquivo @Argumentos 2>&1 | ForEach-Object { "$_" }
    return @{ codigo = $LASTEXITCODE; saida = ($saida -join "`n") }
}

function Pastas { param([string]$Base) @(Get-ChildItem -LiteralPath $Base -Directory -ErrorAction SilentlyContinue | ForEach-Object FullName) }

function Nova-Pasta {
    param([string[]]$Antes)
    return @(Pastas $baseEnsaio | Where-Object { $Antes -notcontains $_ })
}

Push-Location $Raiz
try {
    Assert-AmbienteLocal
    $remotasAntes = Pastas $baseRemota

    # 1. Proteções do backup remoto (falham antes de qualquer conexão).
    $r = Executar $script @()
    Resultado ($r.codigo -ne 0 -and $r.saida -match 'confirme com -Projeto') 'Sem -Projeto: backup remoto recusado'
    $r = Executar $script @('-Projeto', 'projeto-errado-ficticio')
    Resultado ($r.codigo -ne 0 -and $r.saida -match 'não corresponde') 'Com -Projeto diferente do configurado: recusado'
    $r = Executar $script @('-Ensaio', '-Projeto', 'qualquer')
    Resultado ($r.codigo -ne 0 -and $r.saida -match 'Use -Ensaio OU -Projeto') '-Ensaio junto de -Projeto: recusado'
    Resultado ((@(Pastas $baseRemota) -join '|') -eq ($remotasAntes -join '|')) 'Nenhuma pasta criada em backups\supabase pelas tentativas recusadas'

    # 2. Ensaio (PostgreSQL local, mesmo procedimento do remoto).
    $antes = Pastas $baseEnsaio
    $r = Executar $script @('-Ensaio')
    $primeira = @(Nova-Pasta $antes)
    $primeira | ForEach-Object { $criadas.Add($_) }
    Resultado ($r.codigo -eq 0 -and $primeira.Count -eq 1 -and (Test-Path (Join-Path "$($primeira[0])" 'banco.dump'))) `
        "Ensaio do backup concluído ($(if ($primeira) { Split-Path $primeira[0] -Leaf } else { 'sem pasta' }))"
    if ($r.codigo -ne 0) { Write-Host $r.saida }
    $manifesto = if ($primeira) { Read-Linhas (Join-Path $primeira[0] 'manifesto.txt') } else { @() }
    Resultado ((@($manifesto | Where-Object { $_ -in 'tipo=banco', 'origem=ensaio', 'esquema=public' })).Count -eq 3) `
        'Manifesto: tipo=banco, origem=ensaio, esquema=public, SHA-256 do dump e da impressão'
    $segredos = @($manifesto + ($r.saida -split "`n")) -join "`n"
    $env_ = @{}
    foreach ($linha in [System.IO.File]::ReadAllLines((Join-Path $Raiz '.env'))) {
        if ($linha -match '^\s*([A-Z0-9_]+)\s*=(.*)$') { $env_[$Matches[1]] = $Matches[2].Trim() }
    }
    $vazou = @('POSTGRES_PASSWORD', 'SUPABASE_DB_PASSWORD', 'DJANGO_SECRET_KEY', 'SUPABASE_STORAGE_SECRET_ACCESS_KEY') |
        Where-Object { $env_[$_] -and $segredos.Contains($env_[$_]) }
    Resultado (@($vazou).Count -eq 0) 'Nenhuma credencial na saída nem no manifesto'

    # 3. Restauração num PostgreSQL local descartável.
    if ($primeira) {
        $r = Executar $restauracao @('-Backup', $primeira[0])
        Resultado ($r.codigo -eq 0 -and $r.saida -match 'Restauração comprovada') 'Restauração da cópia do ensaio comprovada (instância descartável)'
        $r.saida -split "`n" | Where-Object { $_ -match '^\[(OK|FALHA|INFO)' } | ForEach-Object { Write-Host "          $_" }
    }

    # 3b. Impressão digital independente da collation do servidor (causa das
    #     divergências na 1ª cópia real: Supabase usa C.UTF-8, o Docker usa en_US.utf8).
    if ($primeira) {
        $conteiner = "jusgestor-collation-$(Get-Date -Format 'yyyyMMddHHmmss')"
        $ErrorActionPreference = 'Continue'
        & docker run -d --rm --name $conteiner --network none -e "POSTGRES_PASSWORD=$([guid]::NewGuid().ToString('N'))" postgres:17 | Out-Null
        try {
            for ($i = 0; $i -lt 60; $i++) { & docker exec $conteiner pg_isready -q -h 127.0.0.1 -U postgres | Out-Null; if ($LASTEXITCODE -eq 0) { break }; Start-Sleep 1 }
            & docker exec $conteiner mkdir /c | Out-Null
            & docker cp (Join-Path $primeira[0] 'banco.dump') "${conteiner}:/c/banco.dump" | Out-Null
            & docker cp (Join-Path $PSScriptRoot 'verificar_banco.sql') "${conteiner}:/c/verificar_banco.sql" | Out-Null
            $roteiroCollation = Join-Path ([System.IO.Path]::GetTempPath()) "$conteiner.sh"
            [System.IO.File]::WriteAllText($roteiroCollation, (@(
                'set -e'
                "pg_restore -l /c/banco.dump | grep -v ' SCHEMA - public ' > /c/itens.lista"
                'for par in en_US.utf8:a C:b C.utf8:c; do'
                '  collation=${par%%:*}; banco=${par#*:}'
                '  createdb -U postgres -T template0 --lc-collate=$collation --lc-ctype=$collation $banco'
                '  pg_restore -U postgres --exit-on-error --no-owner --no-privileges -L /c/itens.lista -d $banco /c/banco.dump'
                '  psql -U postgres -X -q -At -d $banco -f /c/verificar_banco.sql > /c/$banco.txt'
                'done'
                'cmp -s /c/a.txt /c/b.txt && cmp -s /c/b.txt /c/c.txt && echo IDENTICAS'
            ) -join "`n") + "`n", (New-Object System.Text.UTF8Encoding $false))
            & docker cp $roteiroCollation "${conteiner}:/c/collation.sh" | Out-Null
            Remove-Item -LiteralPath $roteiroCollation
            $saidaCollation = (& docker exec $conteiner sh /c/collation.sh) -join ''
        } finally {
            & docker stop $conteiner | Out-Null
            $ErrorActionPreference = 'Stop'
        }
        Resultado ($saidaCollation -match 'IDENTICAS') 'Impressão digital idêntica em bancos en_US.utf8, C e C.utf8 (independe da collation)'
    }

    # 4. Não sobrescrita.
    if ($primeira) {
        $hashAntes = Get-Sha256 (Join-Path $primeira[0] 'banco.dump')
        Start-Sleep -Seconds 1
        $antes = Pastas $baseEnsaio
        $r = Executar $script @('-Ensaio')
        $segunda = @(Nova-Pasta $antes)
        $segunda | ForEach-Object { $criadas.Add($_) }
        Resultado ($r.codigo -eq 0 -and $segunda.Count -eq 1 -and $segunda[0] -ne $primeira[0] -and
            (Get-Sha256 (Join-Path $primeira[0] 'banco.dump')) -eq $hashAntes) `
            'Segundo backup criou outra pasta; a primeira cópia continua idêntica'
    }

    # 5. Cópia adulterada é recusada antes da restauração.
    if ($primeira) {
        $adulterada = "$($primeira[0])-adulterada"
        Copy-Item -LiteralPath $primeira[0] -Destination $adulterada -Recurse
        $criadas.Add($adulterada)
        $bytes = [System.IO.File]::ReadAllBytes((Join-Path $adulterada 'banco.dump'))
        $bytes[$bytes.Length - 1] = $bytes[$bytes.Length - 1] -bxor 1
        [System.IO.File]::WriteAllBytes((Join-Path $adulterada 'banco.dump'), $bytes)
        $r = Executar $restauracao @('-Backup', $adulterada)
        Resultado ($r.codigo -ne 0 -and $r.saida -match 'FALHA\]\s+SHA-256 de banco.dump') 'Cópia adulterada recusada (SHA-256 do dump não confere)'
    }
}
catch {
    Resultado $false "Erro: $($_.Exception.Message)"
}
finally {
    if (-not $Manter) {
        foreach ($pasta in $criadas) {
            if (Test-Path -LiteralPath $pasta) {
                & icacls $pasta /reset /T /Q | Out-Null   # desfaz a restrição de acesso antes de apagar
                Remove-Item -LiteralPath $pasta -Recurse -Force
            }
        }
        if ($criadas.Count) { Write-Host "Pastas de ensaio removidas: $($criadas.Count)" }
    }
    Pop-Location
}
Write-Host ''
if ($falhas) { Write-Host "Rotina NÃO validada: $falhas falha(s)." -ForegroundColor Red; exit 1 }
Write-Host 'Rotina de backup do Supabase validada (sem acessar o Supabase).' -ForegroundColor Green
exit 0
