$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sandbox = Join-Path $env:RUNNER_TEMP "sklad ozon portable smoke"
if (-not $env:RUNNER_TEMP) { $sandbox = Join-Path $env:TEMP "sklad ozon portable smoke" }
$serverPid = $null
$artifacts = Join-Path $root "test-artifacts\windows-portable"

function Wait-Health([int]$Seconds = 180) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:17843/api/health" -TimeoutSec 2
            if ($health.status -eq "ok" -and $health.service -eq "sklad_ozon" -and $health.api_version -eq 1) { return }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    throw "Health endpoint did not become ready"
}

function Assert-RuntimeValid([string]$Runtime) {
    $python = Join-Path $Runtime "python.exe"
    if (-not (Test-Path $python)) { throw "Portable Python was not restored" }
    & $python -c "import sys; raise SystemExit(sys.version_info[:3] != (3,13,14))"
    if ($LASTEXITCODE -ne 0) { throw "Restored Python version validation failed" }
    & $python -c "import fastapi,uvicorn,openpyxl,multipart; from importlib.metadata import version; expected={'fastapi':'0.139.2','uvicorn':'0.51.0','openpyxl':'3.1.5','python-multipart':'0.0.32'}; raise SystemExit(any(version(k)!=v for k,v in expected.items()))"
    if ($LASTEXITCODE -ne 0) { throw "Restored dependency validation failed" }
}

try {
    Remove-Item $sandbox -Recurse -Force -ErrorAction SilentlyContinue
    New-Item $sandbox -ItemType Directory | Out-Null
    Get-ChildItem $root -Force | Where-Object { $_.Name -notin @(".git", "runtime", "data") } |
        Copy-Item -Destination $sandbox -Recurse -Force
    New-Item (Join-Path $sandbox "data") -ItemType Directory | Out-Null
    $sentinel = Join-Path $sandbox "data\preserve-me.txt"
    Set-Content $sentinel "must survive runtime repair"
    if (Test-Path (Join-Path $sandbox "runtime\python.exe")) { throw "Smoke must begin without a runtime" }

    $first = Start-Process cmd.exe -ArgumentList "/d", "/c", "start.bat" -WorkingDirectory $sandbox -Wait -PassThru
    if ($first.ExitCode -ne 0) { throw "First bootstrap failed with $($first.ExitCode)" }
    Wait-Health
    $connection = Get-NetTCPConnection -LocalPort 17843 -State Listen
    if ($connection.LocalAddress -ne "127.0.0.1") { throw "Listener is not loopback-only: $($connection.LocalAddress)" }
    $serverPid = $connection.OwningProcess
    if ((Get-Content $sentinel -Raw).Trim() -ne "must survive runtime repair") { throw "data sentinel changed" }

    $runtime = Join-Path $sandbox "runtime"
    $before = Get-ChildItem $runtime -Recurse -File | Sort-Object FullName |
        ForEach-Object { "$($_.FullName.Substring($runtime.Length))|$($_.Length)|$($_.LastWriteTimeUtc.Ticks)" }
    $second = Start-Process cmd.exe -ArgumentList "/d", "/c", "start.bat" -WorkingDirectory $sandbox -Wait -PassThru
    if ($second.ExitCode -ne 0) { throw "Second launch failed with $($second.ExitCode)" }
    $after = Get-ChildItem $runtime -Recurse -File | Sort-Object FullName |
        ForEach-Object { "$($_.FullName.Substring($runtime.Length))|$($_.Length)|$($_.LastWriteTimeUtc.Ticks)" }
    if (Compare-Object $before $after) { throw "Valid runtime was downloaded, rebuilt, or reinstalled on second launch" }
    if (Test-Path (Join-Path $runtime "*.part")) { throw "Incomplete download was retained as complete" }
    if ((Get-Content $sentinel -Raw).Trim() -ne "must survive runtime repair") { throw "data sentinel did not survive reuse" }
    Wait-Health 10

    Stop-Process -Id $serverPid -Force
    Wait-Process -Id $serverPid -ErrorAction SilentlyContinue
    $serverPid = $null
    Remove-Item (Join-Path $runtime "python.exe") -Force
    if (Test-Path (Join-Path $runtime "python.exe")) { throw "Failed to damage runtime deterministically" }

    $recovery = Start-Process cmd.exe -ArgumentList "/d", "/c", "start.bat" -WorkingDirectory $sandbox -Wait -PassThru
    if ($recovery.ExitCode -ne 0) { throw "Damaged runtime recovery failed with $($recovery.ExitCode)" }
    Wait-Health
    $connection = Get-NetTCPConnection -LocalPort 17843 -State Listen
    if ($connection.LocalAddress -ne "127.0.0.1") { throw "Recovered listener is not loopback-only: $($connection.LocalAddress)" }
    $serverPid = $connection.OwningProcess
    Assert-RuntimeValid $runtime
    if (Get-ChildItem $runtime -Filter "*.part" -Recurse -File) { throw "Recovery retained an incomplete .part download" }
    if ((Get-Content $sentinel -Raw).Trim() -ne "must survive runtime repair") { throw "data sentinel did not survive runtime rebuild" }
    Write-Host "Portable bootstrap, reuse, damaged-runtime recovery, health, data isolation, and loopback checks passed."
} finally {
    if (-not $serverPid) {
        $listener = Get-NetTCPConnection -LocalPort 17843 -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalAddress -eq "127.0.0.1" } | Select-Object -First 1
        if ($listener) { $serverPid = $listener.OwningProcess }
    }
    if ($serverPid) { Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue }
    Remove-Item $artifacts -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path (Join-Path $sandbox "data")) {
        New-Item $artifacts -ItemType Directory -Force | Out-Null
        Copy-Item (Join-Path $sandbox "data\*") $artifacts -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $sandbox -Recurse -Force -ErrorAction SilentlyContinue
}
