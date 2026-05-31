param(
    [string]$RepoRoot,
    [string]$PythonPath,
    [string]$DaemonHost = "127.0.0.1",
    [int]$DaemonPort = 8765,
    [string]$HubHost = $env:ENGRAM_WATCHDOG_HUB_HOST,
    [int]$HubPort = 8767,
    [string]$SyncHost = $env:ENGRAM_WATCHDOG_SYNC_HOST,
    [int]$SyncPort = 8766,
    [int]$MaxBodyBytes = 104857600,
    [int]$RestartCooldownSeconds = 300,
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    param([string]$ConfiguredRoot)
    if ([string]::IsNullOrWhiteSpace($ConfiguredRoot)) {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    }
    return (Resolve-Path $ConfiguredRoot).Path
}

function Get-LocalAppDataPath {
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        return $env:LOCALAPPDATA
    }
    return (Join-Path $env:USERPROFILE "AppData\Local")
}

function Get-TailscaleIPv4 {
    try {
        $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -like "100.*" -and
                ($_.InterfaceAlias -like "*Tailscale*" -or $_.InterfaceDescription -like "*Tailscale*")
            } |
            Sort-Object InterfaceMetric, IPAddress
        if ($addresses) {
            return [string]$addresses[0].IPAddress
        }
    } catch {
        return $null
    }
    return $null
}

function Read-WatchdogState {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return @{}
    }
    try {
        $raw = Get-Content -LiteralPath $Path -Raw
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return @{}
        }
        $decoded = $raw | ConvertFrom-Json
        $result = @{}
        foreach ($property in $decoded.PSObject.Properties) {
            $result[$property.Name] = $property.Value
        }
        return $result
    } catch {
        return @{}
    }
}

function Write-WatchdogEvent {
    param(
        [string]$Level,
        [string]$Message,
        [hashtable]$Data = @{}
    )
    $logPath = Join-Path $script:LogDir ("engram-watchdog-{0}.jsonl" -f (Get-Date -Format "yyyyMMdd"))
    $entry = [ordered]@{
        ts = (Get-Date).ToUniversalTime().ToString("o")
        level = $Level
        message = $Message
        data = $Data
    }
    ($entry | ConvertTo-Json -Depth 8 -Compress) | Add-Content -LiteralPath $logPath -Encoding UTF8
}

function Set-WatchdogState {
    param(
        [string]$Status,
        [string]$Reason,
        [hashtable]$Details = @{}
    )
    $previous = Read-WatchdogState -Path $script:StatePath
    $changed = ($previous["status"] -ne $Status) -or ($previous["reason"] -ne $Reason)
    $state = [ordered]@{
        checked_at = (Get-Date).ToUniversalTime().ToString("o")
        status = $Status
        reason = $Reason
        details = $Details
    }
    ($state | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $script:StatePath -Encoding UTF8
    if ($changed) {
        Write-WatchdogEvent -Level "info" -Message "state_changed" -Data @{
            previous_status = $previous["status"]
            previous_reason = $previous["reason"]
            status = $Status
            reason = $Reason
            details = $Details
        }
    }
}

function Test-LoopbackDaemonHealth {
    param(
        [string]$HostName,
        [int]$Port
    )
    $uri = "http://${HostName}:${Port}/health"
    try {
        $response = Invoke-RestMethod -Method Get -Uri $uri -TimeoutSec 5
        return @{
            healthy = (($response.status -eq "ok") -and ($null -eq $response.error))
            uri = $uri
            error = $null
        }
    } catch {
        return @{
            healthy = $false
            uri = $uri
            error = $_.Exception.Message
        }
    }
}

function Test-LocalListener {
    param(
        [string]$Address,
        [int]$Port
    )
    if ([string]::IsNullOrWhiteSpace($Address)) {
        return @{
            checked = $false
            healthy = $false
            reason = "address_unavailable"
        }
    }
    try {
        $listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
            Where-Object {
                $_.LocalAddress -eq $Address -or
                $_.LocalAddress -eq "0.0.0.0" -or
                $_.LocalAddress -eq "::"
            }
        return @{
            checked = $true
            healthy = [bool]$listeners
            address = $Address
            port = $Port
        }
    } catch {
        return @{
            checked = $true
            healthy = $false
            address = $Address
            port = $Port
            error = $_.Exception.Message
        }
    }
}

function Get-EngramDaemonProcesses {
    param([string]$Root)
    $daemonPath = Join-Path $Root "engramd.py"
    $escapedDaemonPath = [regex]::Escape($daemonPath)
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match $escapedDaemonPath -and
            $_.ProcessId -ne $PID
        }
}

function Stop-EngramDaemonProcesses {
    param([string]$Root)
    $processes = @(Get-EngramDaemonProcesses -Root $Root)
    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        } catch {
            Write-WatchdogEvent -Level "warn" -Message "stop_process_failed" -Data @{
                pid = $process.ProcessId
                error = $_.Exception.Message
            }
        }
    }
    return $processes.Count
}

function Start-EngramDaemon {
    param(
        [string]$Root,
        [string]$Python,
        [string]$RawHost,
        [int]$RawPort,
        [string]$GatewayHost,
        [int]$GatewayPort,
        [string]$SyncAddress,
        [int]$SyncListenPort,
        [int]$BodyLimit
    )
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stdout = Join-Path $script:LogDir "engramd-watchdog-$timestamp-stdout.log"
    $stderr = Join-Path $script:LogDir "engramd-watchdog-$timestamp-stderr.log"
    $daemonArgs = @(
        (Join-Path $Root "engramd.py"),
        "--host", $RawHost,
        "--port", [string]$RawPort
    )
    if (-not [string]::IsNullOrWhiteSpace($GatewayHost)) {
        $daemonArgs += @("--hub-listen", "--hub-host", $GatewayHost, "--hub-port", [string]$GatewayPort)
        $env:ENGRAM_HUB_LISTEN = "1"
        $env:ENGRAM_HUB_PRIVATE_NETWORK_ACK = "1"
    }
    if (-not [string]::IsNullOrWhiteSpace($SyncAddress)) {
        $daemonArgs += @("--sync-listen", "--sync-host", $SyncAddress, "--sync-port", [string]$SyncListenPort)
    }
    $env:ENGRAM_DAEMON_MAX_CONTENT_LENGTH = [string]$BodyLimit
    $process = Start-Process `
        -FilePath $Python `
        -ArgumentList $daemonArgs `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    return @{
        pid = $process.Id
        stdout = $stdout
        stderr = $stderr
        args = $daemonArgs
    }
}

function Get-LastRestartAgeSeconds {
    if (-not (Test-Path -LiteralPath $script:LastRestartPath)) {
        return $null
    }
    try {
        $raw = Get-Content -LiteralPath $script:LastRestartPath -Raw
        $record = $raw | ConvertFrom-Json
        $last = [DateTimeOffset]::Parse([string]$record.restarted_at)
        return [int]((Get-Date).ToUniversalTime() - $last.UtcDateTime).TotalSeconds
    } catch {
        return $null
    }
}

function Set-LastRestart {
    param([hashtable]$Data)
    $record = [ordered]@{
        restarted_at = (Get-Date).ToUniversalTime().ToString("o")
        data = $Data
    }
    ($record | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $script:LastRestartPath -Encoding UTF8
}

$RepoRoot = Resolve-RepoRoot -ConfiguredRoot $RepoRoot
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $RepoRoot "venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Missing Python runtime at $PythonPath"
}

$localAppData = Get-LocalAppDataPath
$script:LogDir = Join-Path $localAppData "Engram\logs"
$stateDir = Join-Path $localAppData "Engram\watchdog"
New-Item -ItemType Directory -Force -Path $script:LogDir, $stateDir | Out-Null
$script:StatePath = Join-Path $stateDir "watchdog-state.json"
$script:LastRestartPath = Join-Path $stateDir "last-restart.json"
$pausePath = Join-Path $stateDir "watchdog.pause"

if (Test-Path -LiteralPath $pausePath) {
    Set-WatchdogState -Status "paused" -Reason "pause_file_present" -Details @{ pause_file = $pausePath }
    exit 0
}

$detectedTailnetAddress = Get-TailscaleIPv4
if ([string]::IsNullOrWhiteSpace($HubHost)) {
    $HubHost = $detectedTailnetAddress
}
if ([string]::IsNullOrWhiteSpace($SyncHost)) {
    $SyncHost = $HubHost
}

$daemon = Test-LoopbackDaemonHealth -HostName $DaemonHost -Port $DaemonPort
$hub = Test-LocalListener -Address $HubHost -Port $HubPort
$sync = Test-LocalListener -Address $SyncHost -Port $SyncPort

$issues = @()
if (-not $daemon.healthy) {
    $issues += "daemon_unhealthy"
}
if ($hub.checked -and -not $hub.healthy) {
    $issues += "hub_listener_missing"
}
if ($sync.checked -and -not $sync.healthy) {
    $issues += "sync_listener_missing"
}
if (-not $hub.checked -or -not $sync.checked) {
    $issues += "tailnet_address_unavailable"
}

$details = @{
    repo_root = $RepoRoot
    daemon = $daemon
    hub = $hub
    sync = $sync
    detected_tailnet_address = $detectedTailnetAddress
    no_remote_probes = $true
}

$restartNeeded = $issues -contains "daemon_unhealthy" -or
    $issues -contains "hub_listener_missing" -or
    $issues -contains "sync_listener_missing"

if (-not $restartNeeded) {
    if ($issues.Count -gt 0) {
        Set-WatchdogState -Status "degraded" -Reason ($issues -join ",") -Details $details
    } else {
        Set-WatchdogState -Status "healthy" -Reason "ok" -Details $details
    }
    exit 0
}

if ($NoRestart) {
    Set-WatchdogState -Status "unhealthy" -Reason ($issues -join ",") -Details $details
    exit 0
}

$restartAge = Get-LastRestartAgeSeconds
if ($null -ne $restartAge -and $restartAge -lt $RestartCooldownSeconds) {
    $details["restart_age_seconds"] = $restartAge
    $details["restart_cooldown_seconds"] = $RestartCooldownSeconds
    Set-WatchdogState -Status "unhealthy_cooldown" -Reason ($issues -join ",") -Details $details
    exit 0
}

$stoppedCount = Stop-EngramDaemonProcesses -Root $RepoRoot
Start-Sleep -Seconds 2
$start = Start-EngramDaemon `
    -Root $RepoRoot `
    -Python $PythonPath `
    -RawHost $DaemonHost `
    -RawPort $DaemonPort `
    -GatewayHost $HubHost `
    -GatewayPort $HubPort `
    -SyncAddress $SyncHost `
    -SyncListenPort $SyncPort `
    -BodyLimit $MaxBodyBytes
Set-LastRestart -Data @{
    issues = $issues
    stopped_process_count = $stoppedCount
    started = $start
}
Write-WatchdogEvent -Level "warn" -Message "daemon_restarted" -Data @{
    issues = $issues
    stopped_process_count = $stoppedCount
    started = $start
}

Start-Sleep -Seconds 8
$postDaemon = Test-LoopbackDaemonHealth -HostName $DaemonHost -Port $DaemonPort
$postHub = Test-LocalListener -Address $HubHost -Port $HubPort
$postSync = Test-LocalListener -Address $SyncHost -Port $SyncPort
Set-WatchdogState -Status "restarted" -Reason ($issues -join ",") -Details @{
    before = $details
    after = @{
        daemon = $postDaemon
        hub = $postHub
        sync = $postSync
    }
    started = $start
}
