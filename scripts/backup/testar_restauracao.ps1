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
      5. lê o banco restaurado pelo Django, com a versão do código cujas
         migrações são EXATAMENTE as registradas na cópia (o código atual, ou um
         commit anterior extraído do Git para uma pasta temporária); nenhuma
         migração é aplicada no banco restaurado;
      6. controle negativo: altera de propósito um registro e um arquivo NA CÓPIA
         e confirma que a verificação acusa a diferença;
      7. remove o contêiner, a rede e a pasta temporária.

    Impressão digital: no formato 2, a ordenação não depende do servidor. Cópias
    antigas (formato 1) foram calculadas com a collation padrão do servidor de
    origem; elas são conferidas com cada ordenação candidata e só passam se
    TODAS as linhas corresponderem com uma delas.

    A cópia é apenas lida. O resultado é gravado em backups\restauracoes\.
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
$temporaria = $null   # cópia temporária do código, se for preciso usar um commit anterior

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

    # Cópia completa (backup.ps1: banco + documentos) ou só do banco (backup_supabase.ps1).
    $temDocumentos = $manifesto.ContainsKey('sha256_documentos')
    if ($manifesto['origem']) { $relatorio.Add("origem=$($manifesto['origem']) ($($manifesto['descricao']))") }

    # 1. Integridade dos arquivos da cópia.
    $arquivosCopia = [ordered]@{ 'banco.dump' = 'sha256_banco'; 'impressao_origem.txt' = 'sha256_impressao' }
    if ($temDocumentos) {
        $arquivosCopia['documentos.tar.gz'] = 'sha256_documentos'
        $arquivosCopia['documentos.sha256'] = 'sha256_lista_documentos'
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
    foreach ($arquivo in @('banco.dump') + @(if ($temDocumentos) { 'documentos.tar.gz' })) {
        Invoke-Docker cp (Join-Path $Backup $arquivo) "${nome}:/restauracao/$arquivo" | Out-Null
    }
    foreach ($arquivo in 'verificar_banco.sql', 'restaurar_teste.sh') {
        Invoke-Docker cp (Join-Path $PSScriptRoot $arquivo) "${nome}:/restauracao/$arquivo" | Out-Null
    }
    $relogio = [System.Diagnostics.Stopwatch]::StartNew()
    Invoke-Docker exec $nome sh /restauracao/restaurar_teste.sh restaurar | Out-Null
    $relogio.Stop()
    Registrar $true ("pg_restore{0} sem erros ({1:N1} s)" -f $(if ($temDocumentos) { ' e extração dos documentos' } else { '' }), $relogio.Elapsed.TotalSeconds)

    # 4. Comparação com a origem.
    $origem = @(Read-Linhas (Join-Path $Backup 'impressao_origem.txt'))
    $ordenacaoLegada = $null
    if ($origem -contains 'formato|impressao|2|ordenacao=C') {
        $restaurada = @(Ler-NoConteiner 'impressao_restaurada.txt')
    } else {
        # Formato 1: ordenação de texto dependente da collation do servidor de origem
        # (padrão do PostgreSQL local, ou C no Supabase). Exige correspondência total.
        $melhor = $null
        foreach ($candidata in 'default', 'C') {
            Invoke-Docker exec $nome sh /restauracao/restaurar_teste.sh legado $candidata | Out-Null
            $linhas = @(Ler-NoConteiner 'impressao_legado.txt')
            $quantas = @(Comparar-Impressoes $origem $linhas).Count
            if ($null -eq $melhor -or $quantas -lt $melhor.diferencas) {
                $melhor = @{ ordenacao = $candidata; linhas = $linhas; diferencas = $quantas }
            }
            if ($quantas -eq 0) { break }
        }
        $ordenacaoLegada = $melhor.ordenacao
        $restaurada = $melhor.linhas
        $texto = "[INFO]  Impressão de origem no formato 1 (ordenação dependente do servidor): conferida com ordenação '$ordenacaoLegada'" +
            $(if ($melhor.diferencas -eq 0) { ' (todas as linhas correspondem).' } else { " (nenhuma ordenação candidata corresponde a todas as linhas)." })
        $relatorio.Add($texto)
        Write-Host $texto
    }
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
    $docsOrigem = @()
    if ($temDocumentos) {
        $docsOrigem = @(Read-Linhas (Join-Path $Backup 'documentos.sha256'))
        $docsRestaurados = @(Ler-NoConteiner 'documentos_restaurada.sha256')
        $docsDif = @(Get-Diferencas $docsOrigem $docsRestaurados)
        Registrar ($docsDif.Count -eq 0) "Documentos: $($docsRestaurados.Count)/$($docsOrigem.Count) arquivos restaurados com SHA-256 idêntico"
        $versoes = @(Ler-NoConteiner 'versoes_restaurada.txt')
        $versoesRuins = @($versoes | Where-Object { $_ -ne 'ok' })
        Registrar ($versoesRuins.Count -eq 0) `
            "Versões de documento: $($versoes.Count - $versoesRuins.Count)/$($versoes.Count) com arquivo presente e tamanho igual ao registrado"
    } else {
        $relatorio.Add('[INFO]  Cópia só do banco: os arquivos dos documentos têm backup próprio (exportar_documentos).')
        Write-Host '[INFO]  Cópia só do banco: os arquivos dos documentos têm backup próprio (exportar_documentos).'
    }

    # 5. A aplicação lê o banco restaurado (contêiner temporário, só na rede descartável),
    #    com a versão do código compatível com o esquema da cópia. Nenhuma migração é aplicada.
    $rotulos = @(Get-ChildItem -LiteralPath (Join-Path $Raiz 'apps') -Directory | ForEach-Object Name)
    $aplicadas = @(Invoke-Docker exec $nome psql -U postgres -d restaurado -X -At -c 'SELECT app || chr(46) || name FROM django_migrations' |
        Where-Object { $_ -and $rotulos -contains ($_ -split '\.')[0] } | Sort-Object)
    $padrao = '^apps/([a-z_]+)/migrations/([0-9][^/]*)\.py$'
    $doCodigoAtual = @(Get-ChildItem -Path (Join-Path $Raiz 'apps\*\migrations\0*.py') |
        ForEach-Object { "$($_.Directory.Parent.Name).$($_.BaseName)" } | Sort-Object)
    $codigo = $null; $descricaoCodigo = $null
    if (($doCodigoAtual -join ',') -eq ($aplicadas -join ',')) {
        $codigo = $Raiz; $descricaoCodigo = 'código atual'
    } else {
        foreach ($commit in @(& git rev-list HEAD)) {
            $doCommit = @(& git ls-tree -r --name-only $commit -- apps | Where-Object { $_ -match $padrao } |
                ForEach-Object { $_ -replace $padrao, '$1.$2' } | Sort-Object)
            if (($doCommit -join ',') -eq ($aplicadas -join ',')) {
                $temporaria = Join-Path ([System.IO.Path]::GetTempPath()) "jusgestor-codigo-$carimbo"
                New-Item -ItemType Directory -Path $temporaria | Out-Null
                & git archive --format=zip -o (Join-Path $temporaria 'codigo.zip') $commit
                Expand-Archive -LiteralPath (Join-Path $temporaria 'codigo.zip') -DestinationPath (Join-Path $temporaria 'codigo')
                $codigo = Join-Path $temporaria 'codigo'
                $descricaoCodigo = "commit $($commit.Substring(0, 7))"
                break
            }
        }
    }
    $faltantes = @($doCodigoAtual | Where-Object { $aplicadas -notcontains $_ })
    $texto = "[INFO]  Migrações do projeto na cópia: $($aplicadas -join ', ')" +
        $(if ($faltantes) { ". O código atual tem $($faltantes.Count) a mais, ainda não aplicadas na origem: $($faltantes -join ', ')." } else { '.' })
    $relatorio.Add($texto); Write-Host $texto
    Registrar ($null -ne $codigo) ("Versão do código compatível com o esquema da cópia: " +
        $(if ($codigo) { $descricaoCodigo } else { 'nenhuma (as migrações da cópia não correspondem a nenhum commit)' }))

    # Rede interna (sem internet) e variáveis do Supabase vazias: impossível alcançar o banco remoto.
    $django = @('run', '--rm', '--network', $rede, '--env-file', (Join-Path $Raiz '.env'),
        '-e', 'SUPABASE_DB_HOST=', '-e', 'SUPABASE_DB_USER=', '-e', 'SUPABASE_DB_PASSWORD=',
        '-e', 'SUPABASE_STORAGE_ACCESS_KEY_ID=', '-e', 'SUPABASE_STORAGE_SECRET_ACCESS_KEY=',
        '-e', 'DOCUMENTOS_ARMAZENAMENTO=local',
        '-e', 'DB_ALVO=local', '-e', "POSTGRES_HOST=$nome", '-e', 'POSTGRES_PORT=5432',
        '-e', 'POSTGRES_DB=restaurado', '-e', 'POSTGRES_USER=postgres', '-e', "POSTGRES_PASSWORD=$senha",
        '-v', "${codigo}:/app:ro", '-v', "$(Join-Path $PSScriptRoot 'contar_orm.py'):/verificacao/contar_orm.py:ro",
        $imagemWeb)
    if (-not $codigo) { throw 'Leitura pelo Django não testada: nenhuma versão do código corresponde ao esquema da cópia.' }
    # showmigrations só lê django_migrations: "[ ]" indica migração não aplicada.
    $plano = @(Invoke-Docker @django python manage.py showmigrations --plan)
    $naoAplicadas = @($plano | Where-Object { $_ -match '^\[ \]' })
    Registrar ($plano.Count -gt 0 -and $naoAplicadas.Count -eq 0) `
        "Django ($descricaoCodigo) conecta ao banco restaurado: $(@($plano | Where-Object { $_ -match '^\[X\]' }).Count) migrações aplicadas, $($naoAplicadas.Count) pendentes"
    $contagemOrm = @(Invoke-Docker @django python /verificacao/contar_orm.py)
    $esperadoOrm = @{}
    foreach ($t in $tabOrigem) { $esperadoOrm[(Get-Campo $t 1)] = Get-Campo $t 2 }
    $ormDif = @($contagemOrm | Where-Object {
        $par = $_ -split '='
        -not $esperadoOrm.ContainsKey($par[0]) -or $esperadoOrm[$par[0]] -ne $par[1]
    })
    Registrar ($contagemOrm.Count -gt 0 -and $ormDif.Count -eq 0) `
        "ORM do Django: $($contagemOrm.Count) modelos com as mesmas contagens da origem$(if ($ormDif) { ' - diferem: ' + ($ormDif -join ', ') })"

    # 6. Controle negativo: a verificação precisa acusar uma alteração proposital.
    $argumentosControle = @('exec', $nome, 'sh', '/restauracao/restaurar_teste.sh', 'controle') + @(if ($ordenacaoLegada) { $ordenacaoLegada })
    Invoke-Docker @argumentosControle | Out-Null
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
    if ($temporaria -and (Test-Path -LiteralPath $temporaria)) { Remove-Item -LiteralPath $temporaria -Recurse -Force }
    Registrar ($restos.Count -eq 0) 'Instância e rede descartáveis removidas'
    Pop-Location
}

# O relatório fica fora da pasta da cópia: a cópia é apenas lida.
$saidaRelatorio = $null
if ($Backup -and (Test-Path -LiteralPath $Backup)) {
    $pastaRelatorios = Join-Path $Raiz 'backups\restauracoes'
    if (-not (Test-Path -LiteralPath $pastaRelatorios)) { New-Item -ItemType Directory -Path $pastaRelatorios | Out-Null }
    $nomeCopia = ((Resolve-Path -LiteralPath $Backup).Path.Substring($Raiz.Length).Trim('\') -replace '^backups\\', '' -replace '[\\/]', '-')
    $saidaRelatorio = Join-Path $pastaRelatorios "$nomeCopia`_$carimbo.txt"
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
