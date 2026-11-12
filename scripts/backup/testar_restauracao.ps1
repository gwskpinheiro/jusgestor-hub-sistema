<#
.SYNOPSIS
    Testa a restauração de uma cópia de segurança em uma instância DESCARTÁVEL (RNF07).

.DESCRIPTION
    Nunca restaura por cima do banco principal. Passos:
      1. confere o SHA-256 dos arquivos da cópia (manifesto.txt);
      2. cria uma rede Docker interna (sem internet) e um contêiner PostgreSQL
         descartável, com a mesma imagem do serviço db;
      3. restaura banco.dump (pg_restore) e extrai documentos.tar.gz nesse contêiner;
      4. compara com a impressão digital tirada no momento da cópia:
         registros e hash de cada tabela, restrições, índices, sequências,
         FKs validadas, órfãos por chave estrangeira, SHA-256 de cada documento
         e existência/tamanho do arquivo de cada versão registrada;
      5. lê o banco restaurado pelo Django (verificar_banco e contagem pelo ORM);
      6. controle negativo: altera de propósito um registro e um arquivo NA CÓPIA
         e confirma que a verificação acusa a diferença;
      7. remove o contêiner e a rede descartáveis.

    O resultado é gravado em restauracao_<data>.txt dentro da pasta da cópia.
    Código de saída 0 = restauração comprovada; 1 = alguma verificação falhou.

.PARAMETER Backup
    Pasta da cópia (criada pelo backup.ps1). Padrão: a mais recente em backups\.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\backup\testar_restauracao.ps1
#>
param([string]$Backup)

. (Join-Path $PSScriptRoot 'comum.ps1')

$carimbo = Get-Date -Format 'yyyyMMdd-HHmmss'
$nome = "jusgestor-restauracao-$carimbo"
$rede = $nome
$senha = [guid]::NewGuid().ToString('N')   # só existe no contêiner descartável
$falhas = New-Object System.Collections.Generic.List[string]
$relatorio = New-Object System.Collections.Generic.List[string]

function Registrar {
    param([bool]$Ok, [string]$Texto)
    $marca = if ($Ok) { '[OK]   ' } else { '[FALHA]' }
    $relatorio.Add("$marca $Texto")
    if (-not $Ok) { $falhas.Add($Texto) }
    Write-Host "$marca $Texto" -ForegroundColor $(if ($Ok) { 'Green' } else { 'Red' })
}

function Ler-NoConteiner {
    param([string]$Arquivo)
    return @(Invoke-Docker exec $nome cat "/restauracao/$Arquivo" | Where-Object { $_ -ne '' })
}

function Get-Diferencas {
    # Linhas presentes em só uma das listas (aceita listas vazias).
    param([string[]]$A, [string[]]$B)
    if ($null -eq $A) { $A = @() }
    if ($null -eq $B) { $B = @() }
    if ($A.Count -eq 0) { return $B }
    if ($B.Count -eq 0) { return $A }
    return Compare-Object -CaseSensitive $A $B | ForEach-Object { $_.InputObject }
}

function Comparar-Impressoes {
    # Devolve os nomes (tipo|nome) cujas linhas diferem entre as duas impressões.
    param([string[]]$A, [string[]]$B)
    return Get-Diferencas $A $B |
        ForEach-Object { (Get-Campo $_ 0) + '|' + (Get-Campo $_ 1) } |
        Sort-Object -Unique
}

Push-Location $Raiz
try {
    Assert-AmbienteLocal

    # --- Cópia a testar --------------------------------------------------------
    if (-not $Backup) {
        $ultima = Get-ChildItem -LiteralPath (Join-Path $Raiz 'backups') -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'manifesto.txt') } |
            Sort-Object Name | Select-Object -Last 1
        if (-not $ultima) { throw 'Nenhuma cópia encontrada em backups\. Rode antes o backup.ps1.' }
        $Backup = $ultima.FullName
    }
    $Backup = (Resolve-Path -LiteralPath $Backup).Path
    $manifesto = @{}
    foreach ($linha in Read-Linhas (Join-Path $Backup 'manifesto.txt')) {
        if ($linha -match '^([a-z_0-9]+)=(.*)$') { $manifesto[$Matches[1]] = $Matches[2] }
    }
    $relatorio.Add("JusGestor Hub - teste de restauracao (RNF07) em $(Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')")
    $relatorio.Add("copia=$Backup (criada em $($manifesto['criado_em']))")
    Write-Host "Cópia: $Backup"

    # 1. Integridade dos arquivos da cópia.
    $arquivosCopia = [ordered]@{
        'banco.dump' = 'sha256_banco'; 'documentos.tar.gz' = 'sha256_documentos'
        'documentos.sha256' = 'sha256_lista_documentos'; 'impressao_origem.txt' = 'sha256_impressao'
    }
    foreach ($arquivo in $arquivosCopia.Keys) {
        $esperado = $manifesto[$arquivosCopia[$arquivo]]
        $ok = $esperado -and ((Get-Sha256 (Join-Path $Backup $arquivo)) -eq $esperado)
        Registrar $ok "SHA-256 de $arquivo confere com o manifesto"
    }
    if ($falhas.Count) { throw 'Arquivos da cópia corrompidos ou alterados; restauração não testada.' }

    # 2. Instância descartável, isolada (rede interna, sem portas publicadas).
    $idDb = (@(Invoke-Docker compose ps -q db) -join '').Trim()
    $idWeb = (@(Invoke-Docker compose ps -q web) -join '').Trim()
    $imagemDb = (@(Invoke-Docker inspect -f '{{.Config.Image}}' $idDb) -join '').Trim()
    $imagemWeb = (@(Invoke-Docker inspect -f '{{.Image}}' $idWeb) -join '').Trim()
    Invoke-Docker network create --internal --label jusgestor.restauracao=1 $rede | Out-Null
    Invoke-Docker run -d --rm --name $nome --network $rede --label jusgestor.restauracao=1 `
        -e "POSTGRES_PASSWORD=$senha" -e POSTGRES_DB=restaurado $imagemDb | Out-Null
    Write-Host "Instância descartável: $nome ($imagemDb)"
    # O servidor temporário da inicialização não escuta TCP; 127.0.0.1 só responde no servidor final.
    $pronto = $false
    for ($i = 0; $i -lt 90 -and -not $pronto; $i++) {
        & docker exec $nome pg_isready -q -h 127.0.0.1 -U postgres -d restaurado | Out-Null
        if ($LASTEXITCODE -eq 0) { $pronto = $true } else { Start-Sleep -Seconds 1 }
    }
    if (-not $pronto) { throw 'O PostgreSQL descartável não ficou pronto em 90 s.' }

    # 3. Restauração.
    Invoke-Docker exec $nome mkdir -p /restauracao | Out-Null
    foreach ($arquivo in 'banco.dump', 'documentos.tar.gz') {
        Invoke-Docker cp (Join-Path $Backup $arquivo) "${nome}:/restauracao/$arquivo" | Out-Null
    }
    foreach ($arquivo in 'verificar_banco.sql', 'restaurar_teste.sh') {
        Invoke-Docker cp (Join-Path $PSScriptRoot $arquivo) "${nome}:/restauracao/$arquivo" | Out-Null
    }
    $relogio = [System.Diagnostics.Stopwatch]::StartNew()
    Invoke-Docker exec $nome sh /restauracao/restaurar_teste.sh restaurar | Out-Null
    $relogio.Stop()
    Registrar $true ("pg_restore e extração dos documentos sem erros ({0:N1} s)" -f $relogio.Elapsed.TotalSeconds)

    # 4. Comparação com a origem.
    $origem = @(Read-Linhas (Join-Path $Backup 'impressao_origem.txt'))
    $restaurada = @(Ler-NoConteiner 'impressao_restaurada.txt')
    $diferentes = @(Comparar-Impressoes $origem $restaurada)

    $tabOrigem = @($origem | Where-Object { $_ -like 'tabela|*' })
    $tabDif = @($diferentes | Where-Object { $_ -like 'tabela|*' })
    $registros = 0
    foreach ($t in $tabOrigem) { $registros += [int64](Get-Campo $t 2) }
    Registrar ($tabOrigem.Count -gt 0 -and $tabDif.Count -eq 0) `
        "Tabelas: $($tabOrigem.Count - $tabDif.Count)/$($tabOrigem.Count) idênticas (contagem e hash de $registros registros)$(if ($tabDif) { ' - diferem: ' + ($tabDif -join ', ') })"
    foreach ($item in 'restricoes', 'indices', 'sequencias') {
        $linha = @($origem | Where-Object { $_ -like "estrutura|$item|*" })
        $ok = $linha.Count -eq 1 -and -not ($diferentes -contains "estrutura|$item")
        Registrar $ok "Estrutura - $item idênticos ($(if ($linha) { Get-Campo $linha[0] 2 } else { '?' }))"
    }
    $naoValidadas = @($restaurada | Where-Object { $_ -like 'estrutura|restricoes_nao_validadas|*' })
    Registrar ($naoValidadas.Count -eq 1 -and (Get-Campo $naoValidadas[0] 2) -eq '0') `
        'Todas as restrições (CHECK, chaves estrangeiras, únicas) recriadas e validadas pelo PostgreSQL contra os dados restaurados'
    $orfaos = @($restaurada | Where-Object { $_ -like 'orfaos|*' })
    $comOrfaos = @($orfaos | Where-Object { (Get-Campo $_ 2) -ne '0' })
    Registrar ($orfaos.Count -gt 0 -and $comOrfaos.Count -eq 0 -and -not ($diferentes -like 'orfaos|*')) `
        "Relacionamentos: $($orfaos.Count) chaves estrangeiras sem registros órfãos"

    # Documentos.
    $docsOrigem = @(Read-Linhas (Join-Path $Backup 'documentos.sha256'))
    $docsRestaurados = @(Ler-NoConteiner 'documentos_restaurada.sha256')
    $docsDif = @(Get-Diferencas $docsOrigem $docsRestaurados)
    Registrar ($docsDif.Count -eq 0) "Documentos: $($docsRestaurados.Count)/$($docsOrigem.Count) arquivos restaurados com SHA-256 idêntico"
    $versoes = @(Ler-NoConteiner 'versoes_restaurada.txt')
    $versoesRuins = @($versoes | Where-Object { $_ -ne 'ok' })
    Registrar ($versoesRuins.Count -eq 0) `
        "Versões de documento: $($versoes.Count - $versoesRuins.Count)/$($versoes.Count) com arquivo presente e tamanho igual ao registrado"

    # 5. A aplicação lê o banco restaurado (contêiner temporário, só na rede descartável).
    $django = @('run', '--rm', '--network', $rede, '--env-file', (Join-Path $Raiz '.env'),
        '-e', 'DB_ALVO=local', '-e', "POSTGRES_HOST=$nome", '-e', 'POSTGRES_PORT=5432',
        '-e', 'POSTGRES_DB=restaurado', '-e', 'POSTGRES_USER=postgres', '-e', "POSTGRES_PASSWORD=$senha",
        '-v', "${Raiz}:/app:ro", $imagemWeb)
    $verificacao = @(Invoke-Docker @django python manage.py verificar_banco)
    $pendentes = @($verificacao | Where-Object { $_ -like 'Migra*pendentes: 0' })
    Registrar ($pendentes.Count -eq 1) 'Django conecta ao banco restaurado: verificar_banco OK, 0 migrações pendentes'
    $contagemOrm = @(Invoke-Docker @django python /app/scripts/backup/contar_orm.py)
    $esperadoOrm = @{}
    foreach ($t in $tabOrigem) { $esperadoOrm[(Get-Campo $t 1)] = Get-Campo $t 2 }
    $ormDif = @($contagemOrm | Where-Object {
        $par = $_ -split '='
        -not $esperadoOrm.ContainsKey($par[0]) -or $esperadoOrm[$par[0]] -ne $par[1]
    })
    Registrar ($contagemOrm.Count -gt 0 -and $ormDif.Count -eq 0) `
        "ORM do Django: $($contagemOrm.Count) modelos com as mesmas contagens da origem$(if ($ormDif) { ' - diferem: ' + ($ormDif -join ', ') })"

    # 6. Controle negativo: a verificação precisa acusar uma alteração proposital.
    Invoke-Docker exec $nome sh /restauracao/restaurar_teste.sh controle | Out-Null
    $controle = @(Comparar-Impressoes $origem @(Ler-NoConteiner 'impressao_controle.txt'))
    Registrar (($controle -join ',') -eq 'tabela|django_migrations') `
        "Controle negativo (banco): alteração proposital de 1 registro detectada ($($controle -join ', '))"
    if ($docsOrigem.Count -gt 0) {
        $docsControle = @(Get-Diferencas $docsOrigem @(Ler-NoConteiner 'documentos_controle.sha256'))
        Registrar ($docsControle.Count -eq 2) 'Controle negativo (documentos): alteração proposital de 1 arquivo detectada'
    } else {
        $relatorio.Add('[INFO]  Controle negativo de documentos não aplicável: a cópia não tem arquivos.')
    }
}
catch {
    Registrar $false "Erro: $($_.Exception.Message)"
}
finally {
    # 7. Remove a instância descartável (o --rm apaga também o volume anônimo) e a rede.
    #    Erros aqui (ex.: contêiner nunca criado) não podem interromper a limpeza.
    $ErrorActionPreference = 'Continue'
    if (@(& docker ps -aq --filter "name=^$nome$")) { & docker stop $nome | Out-Null }
    $restos = @()
    for ($i = 0; $i -lt 20; $i++) {   # o --rm remove o contêiner de forma assíncrona
        $restos = @(& docker ps -aq --filter "name=^$nome$" | Where-Object { $_ })
        if ($restos.Count -eq 0) { break }
        Start-Sleep -Milliseconds 500
    }
    if (@(& docker network ls -q --filter "name=^$rede$")) { & docker network rm $rede | Out-Null }
    $restos = @($restos) + @(& docker network ls -q --filter "name=^$rede$" | Where-Object { $_ })
    Registrar ($restos.Count -eq 0) 'Instância e rede descartáveis removidas'
    Pop-Location
}

$saidaRelatorio = $null
if ($Backup -and (Test-Path -LiteralPath $Backup)) {
    $saidaRelatorio = Join-Path $Backup "restauracao_$carimbo.txt"
    $relatorio.Add($(if ($falhas.Count) { "RESULTADO=FALHA ($($falhas.Count))" } else { 'RESULTADO=OK' }))
    Write-Utf8 $saidaRelatorio $relatorio.ToArray()
}
Write-Host ''
if ($falhas.Count) {
    Write-Host "Restauração NÃO comprovada: $($falhas.Count) verificação(ões) falharam." -ForegroundColor Red
} else {
    Write-Host 'Restauração comprovada: cópia íntegra e idêntica à origem.' -ForegroundColor Green
}
if ($saidaRelatorio) { Write-Host "Relatório: $saidaRelatorio" }
exit $(if ($falhas.Count) { 1 } else { 0 })
