param(
    [string]$RepoRoot,
    [string]$TaskName = "Engram Hub Watchdog",
    [int]$IntervalMinutes = 1
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$watchdogScript = Join-Path $RepoRoot "scripts\watch_engram_hub.ps1"
if (-not (Test-Path -LiteralPath $watchdogScript)) {
    throw "Missing watchdog script at $watchdogScript"
}

$hiddenLauncher = Join-Path $RepoRoot "scripts\run_engram_watchdog_hidden.vbs"
if (-not (Test-Path -LiteralPath $hiddenLauncher)) {
    throw "Missing hidden watchdog launcher at $hiddenLauncher"
}

$wscriptExe = Join-Path $env:SystemRoot "System32\wscript.exe"
$taskRun = "`"$wscriptExe`" //B //Nologo `"$hiddenLauncher`" `"$watchdogScript`""
$startTime = (Get-Date).AddMinutes(1).ToString("HH:mm")
$arguments = @(
    "/Create",
    "/F",
    "/TN", $TaskName,
    "/SC", "MINUTE",
    "/MO", [string]$IntervalMinutes,
    "/ST", $startTime,
    "/TR", $taskRun,
    "/RL", "LIMITED"
)

& schtasks.exe @arguments | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "schtasks.exe failed with exit code $LASTEXITCODE"
}

try {
    $registeredTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $registeredTask.Settings.DisallowStartIfOnBatteries = $false
    $registeredTask.Settings.StopIfGoingOnBatteries = $false
    Set-ScheduledTask -InputObject $registeredTask | Out-Null
} catch {
    Write-Warning "Installed task, but could not relax battery power settings: $($_.Exception.Message)"
}

[pscustomobject]@{
    task_name = $TaskName
    repo_root = $RepoRoot
    watchdog_script = $watchdogScript
    hidden_launcher = $hiddenLauncher
    interval_minutes = $IntervalMinutes
    status = "installed"
} | ConvertTo-Json -Depth 5
