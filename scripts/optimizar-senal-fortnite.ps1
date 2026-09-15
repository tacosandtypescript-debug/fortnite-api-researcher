param(
    [switch]$Apply,
    [switch]$NoSend,
    [ValidateRange(4, 50)]
    [int]$Count = 20
)

$ErrorActionPreference = "Stop"

function Get-FirstMatchValue {
    param(
        [string]$Text,
        [string]$Pattern
    )
    $match = [regex]::Match($Text, $Pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase -bor [System.Text.RegularExpressions.RegexOptions]::Multiline)
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return $null
}

function Get-WlanSnapshot {
    $service = Get-Service -Name WlanSvc -ErrorAction SilentlyContinue
    if ($service -and $service.Status -ne 'Running') {
        return [ordered]@{
            available = $false
            serviceStatus = [string]$service.Status
            state = 'wlansvc-stopped'
            error = 'El servicio WLAN AutoConfig no esta ejecutandose.'
            ssid = $null
            signalPercent = $null
            channel = $null
            radioType = $null
            receiveRateMbps = $null
            transmitRateMbps = $null
        }
    }
    $lines = @(netsh wlan show interfaces 2>$null)
    $text = $lines -join "`n"
    if ($text -match '(?i)(no wireless interface|no hay ninguna interfaz inalambrica|no se encontr)' ) {
        return [ordered]@{
            available = $false
            serviceStatus = if ($service) { [string]$service.Status } else { $null }
            state = 'no-wifi-interface'
            error = 'Windows no reporto una interfaz Wi-Fi disponible.'
            ssid = $null
            signalPercent = $null
            channel = $null
            radioType = $null
            receiveRateMbps = $null
            transmitRateMbps = $null
        }
    }
    $signal = Get-FirstMatchValue $text '^(?:\s*Signal|\s*Senal)\s*:\s*(\d+)%'
    $channel = Get-FirstMatchValue $text '^(?:\s*Channel|\s*Canal)\s*:\s*(\d+)'
    $ssid = Get-FirstMatchValue $text '^\s*SSID\s*:\s*(.+)$'
    $radio = Get-FirstMatchValue $text '^(?:\s*Radio type|\s*Tipo de radio)\s*:\s*(.+)$'
    $receive = Get-FirstMatchValue $text '^(?:\s*Receive rate \(Mbps\)|\s*Tasa de recepcion \(Mbps\))\s*:\s*(.+)$'
    $transmit = Get-FirstMatchValue $text '^(?:\s*Transmit rate \(Mbps\)|\s*Tasa de transmision \(Mbps\))\s*:\s*(.+)$'
    $state = Get-FirstMatchValue $text '^(?:\s*State|\s*Estado)\s*:\s*(.+)$'
    return [ordered]@{
        available = [bool]$signal
        serviceStatus = if ($service) { [string]$service.Status } else { $null }
        state = $state
        ssid = $ssid
        signalPercent = if ($signal) { [int]$signal } else { $null }
        channel = if ($channel) { [int]$channel } else { $null }
        radioType = $radio
        receiveRateMbps = $receive
        transmitRateMbps = $transmit
    }
}

function Get-NetworkAdapterSnapshot {
    if (-not (Get-Command Get-NetAdapter -ErrorAction SilentlyContinue)) { return @() }
    @(Get-NetAdapter -Physical -ErrorAction SilentlyContinue | ForEach-Object {
        [ordered]@{
            name = $_.Name
            description = $_.InterfaceDescription
            status = [string]$_.Status
            linkSpeed = [string]$_.LinkSpeed
            mediaType = [string]$_.MediaType
        }
    })
}

function Invoke-PingProbe {
    param(
        [string]$HostName,
        [int]$ProbeCount
    )
    $addresses = @()
    try {
        $addresses = @(Resolve-DnsName -Name $HostName -Type A -ErrorAction Stop | Where-Object Type -eq 'A' | Select-Object -ExpandProperty IPAddress -Unique)
    } catch {
        $addresses = @()
    }
    $lines = @(ping.exe -n $ProbeCount -w 1200 $HostName 2>&1)
    $text = $lines -join "`n"
    $lossMatch = [regex]::Match($text, '\((\d+)%')
    $receivedMatch = [regex]::Match($text, '(?:Received|Recibidos)\s*=\s*(\d+)')
    $summaryMatch = [regex]::Match($text, '(?:Minimum|M.nimo|Minimo)\s*=\s*(\d+)ms,\s*(?:Maximum|M.ximo|Maximo)\s*=\s*(\d+)ms,\s*(?:Average|Media|Promedio)\s*=\s*(\d+)ms', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    $result = [ordered]@{
        host = $HostName
        resolvedIPv4 = @($addresses)
        replies = if ($receivedMatch.Success) { [int]$receivedMatch.Groups[1].Value } else { $null }
        packetLossPercent = if ($lossMatch.Success) { [int]$lossMatch.Groups[1].Value } else { $null }
        minMs = if ($summaryMatch.Success) { [int]$summaryMatch.Groups[1].Value } else { $null }
        maxMs = if ($summaryMatch.Success) { [int]$summaryMatch.Groups[2].Value } else { $null }
        avgMs = if ($summaryMatch.Success) { [int]$summaryMatch.Groups[3].Value } else { $null }
    }
    if (-not $summaryMatch.Success) { $result.error = "No se pudo interpretar el resumen de ping" }
    return $result
}

function Invoke-SafeOptimization {
    $actions = @()
    $dnsOutput = @(ipconfig.exe /flushdns 2>&1)
    $actions += [ordered]@{
        action = 'ipconfig /flushdns'
        succeeded = ($LASTEXITCODE -eq 0)
        note = 'Limpia la cache DNS local; no cambia el proveedor DNS.'
    }
    $tcpOutput = @(netsh.exe int tcp set global autotuninglevel=normal 2>&1)
    $actions += [ordered]@{
        action = 'netsh int tcp set global autotuninglevel=normal'
        succeeded = ($LASTEXITCODE -eq 0)
        note = 'Restaura el autoajuste TCP estandar de Windows.'
    }
    return $actions
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$outputDirectory = Join-Path $projectRoot 'salidas'
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$retrievedAt = (Get-Date).ToUniversalTime().ToString('o')

$probes = @(
    (Invoke-PingProbe 'ping-nae.ds.on.epicgames.com' $Count),
    (Invoke-PingProbe 'ping-nac.ds.on.epicgames.com' $Count),
    (Invoke-PingProbe 'ping-naw.ds.on.epicgames.com' $Count)
)
$optimization = [ordered]@{
    applied = [bool]$Apply
    actions = @()
    note = if ($Apply) { 'Se solicitaron los ajustes conservadores.' } else { 'Modo auditoria: no se aplicaron cambios.' }
}
if ($Apply) { $optimization.actions = @(Invoke-SafeOptimization) }
$report = [ordered]@{
    investigation = [ordered]@{
        topic = 'Diagnostico y optimizacion segura de senal para Fortnite en Windows'
        retrievedAt = $retrievedAt
        computer = $env:COMPUTERNAME
        mode = if ($Apply) { 'audit-and-apply' } else { 'audit-only' }
        pingCount = $Count
        sources = @(
            'https://www.epicgames.com/help/en-US/c5719335176219/c5719372265755/a5720393283867',
            'https://www.epicgames.com/help/c-34254770/c-33726977/a13493305?lang=uk'
        )
    }
    wifi = Get-WlanSnapshot
    networkAdapters = Get-NetworkAdapterSnapshot
    probes = $probes
    optimization = $optimization
    safety = [ordered]@{
        changesNotMade = @('MTU', 'registro', 'servidores DNS', 'controladores', 'firewall', 'potencia del adaptador')
        limitation = 'El script mide la ruta y aplica ajustes conservadores; no puede aumentar fisicamente la senal de la antena ni garantizar un ping menor.'
    }
}

$fileName = "{0}-diagnostico-senal-fortnite.json" -f (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$outputPath = Join-Path $outputDirectory $fileName
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outputPath -Encoding UTF8

if (-not $NoSend) {
    Push-Location $projectRoot
    try {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        $pythonArguments = @()
        if (-not $pythonCommand) {
            $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
            $pythonArguments = @('-3')
        }
        if (-not $pythonCommand) {
            throw 'No se encontró Python. Activa el entorno virtual o instala Python 3.10+.'
        }
        & $pythonCommand.Source @pythonArguments -m fortnite_research.cli send-file $outputPath --caption 'Diagnostico de senal Fortnite en Windows'
        if ($LASTEXITCODE -ne 0) { throw 'El envio por Telegram no fue confirmado' }
    } finally {
        Pop-Location
    }
}

Write-Output "REPORTE: $outputPath"
