$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sandbox = Join-Path $env:RUNNER_TEMP "sklad ozon portable smoke"
if (-not $env:RUNNER_TEMP) { $sandbox = Join-Path $env:TEMP "sklad ozon portable smoke" }
$serverPid = $null
$artifacts = Join-Path $root "test-artifacts\windows-portable"
$currentPhase = "setup"
$failed = $false
$releaseTimeoutSeconds = 20

function Get-SmokeListeners {
    @(Get-NetTCPConnection -LocalPort 17843 -State Listen -ErrorAction SilentlyContinue)
}

function Get-RuntimeProcesses([string]$WorkingDirectory) {
    $runtimePython = [System.IO.Path]::GetFullPath((Join-Path $WorkingDirectory "runtime\python.exe"))
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.ExecutablePath -and [System.IO.Path]::GetFullPath($_.ExecutablePath) -ieq $runtimePython) -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($runtimePython, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
}

function Wait-ServerStopped {
    param(
        [string]$WorkingDirectory,
        [Nullable[int]]$OwningProcessId,
        [int]$TimeoutSeconds = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $listeners = @(Get-SmokeListeners)
        $runtimeProcesses = @(Get-RuntimeProcesses $WorkingDirectory)
        $ownerExists = $false
        if ($null -ne $OwningProcessId) {
            $ownerExists = $null -ne (Get-Process -Id $OwningProcessId -ErrorAction SilentlyContinue)
        }
        if ($listeners.Count -eq 0 -and -not $ownerExists -and $runtimeProcesses.Count -eq 0) { return }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    $listeners = @(Get-SmokeListeners)
    $runtimeProcesses = @(Get-RuntimeProcesses $WorkingDirectory)
    Write-Host "Server shutdown timed out. Remaining listeners:"
    $listeners | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table | Out-String | Write-Host
    Write-Host "Remaining portable-runtime processes:"
    $runtimeProcesses | Select-Object ProcessId, Name, ExecutablePath, CommandLine | Format-List | Out-String | Write-Host
    if ($null -ne $OwningProcessId) {
        Get-Process -Id $OwningProcessId -ErrorAction SilentlyContinue |
            Select-Object Id, ProcessName, Path | Format-List | Out-String | Write-Host
    }
    throw "Portable test server/runtime did not stop within $TimeoutSeconds seconds"
}

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

function Invoke-StartBat {
    param(
        [string]$WorkingDirectory,
        [int]$TimeoutSeconds = 300
    )

    $process = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/d", "/c", "start.bat" `
        -WorkingDirectory $WorkingDirectory `
        -PassThru
    $exited = $process.WaitForExit($TimeoutSeconds * 1000)

    if (-not $exited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "start.bat did not exit within $TimeoutSeconds seconds"
    }
    if ($process.ExitCode -ne 0) {
        throw "start.bat failed with exit code $($process.ExitCode)"
    }

    return $process.ExitCode
}

function Test-RuntimeValid([string]$Runtime) {
    $python = Join-Path $Runtime "python.exe"
    if (-not (Test-Path $python)) { return $false }
    & $python -c "import sys,fastapi,uvicorn,openpyxl,multipart; from importlib.metadata import version; expected={'fastapi':'0.139.2','uvicorn':'0.51.0','openpyxl':'3.1.5','python-multipart':'0.0.32'}; raise SystemExit(sys.version_info[:3] != (3,13,14) or any(version(k)!=v for k,v in expected.items()))"
    return $LASTEXITCODE -eq 0
}

function Assert-RuntimeValid([string]$Runtime) {
    if (-not (Test-RuntimeValid $Runtime)) { throw "Portable runtime validation failed" }
}

function Assert-Sentinel([string]$Path, [string]$Stage) {
    if ((Get-Content $Path -Raw).Trim() -ne "must survive runtime repair") {
        throw "data sentinel changed $Stage"
    }
}

function Assert-LoopbackListener([string]$Stage) {
    $listeners = @(Get-SmokeListeners)
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne "127.0.0.1") {
        $addresses = ($listeners | ForEach-Object { "$($_.LocalAddress) (PID $($_.OwningProcess))" }) -join ", "
        throw "$Stage listener is not exactly 127.0.0.1: $addresses"
    }
    return $listeners[0]
}

function Write-FailureDiagnostics {
    param([string]$WorkingDirectory, [string]$Phase, [string]$Destination)

    try {
        Remove-Item $Destination -Recurse -Force -ErrorAction SilentlyContinue
        New-Item $Destination -ItemType Directory -Force | Out-Null
        foreach ($name in @("startup_status.json", "server_console.log", "launcher.log")) {
            $source = Join-Path $WorkingDirectory "data\$name"
            if (Test-Path $source) { Copy-Item $source $Destination -Force }
        }
        $diagnostic = [ordered]@{
            timestampUtc = (Get-Date).ToUniversalTime().ToString("o")
            phase = $Phase
            runtimePythonExists = Test-Path (Join-Path $WorkingDirectory "runtime\python.exe")
            listeners = @(Get-SmokeListeners | Select-Object LocalAddress, LocalPort, OwningProcess)
            runtimeProcesses = @(Get-RuntimeProcesses $WorkingDirectory |
                Select-Object ProcessId, Name, ExecutablePath, CommandLine)
        }
        $diagnostic | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Destination "diagnostics.json")
    } catch {
        Write-Warning "Failed to preserve smoke diagnostics: $($_.Exception.Message)"
    }
}

try {
    Remove-Item $artifacts -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $sandbox -Recurse -Force -ErrorAction SilentlyContinue
    New-Item $sandbox -ItemType Directory | Out-Null
    Get-ChildItem $root -Force | Where-Object { $_.Name -notin @(".git", "runtime", "data", "test-artifacts") } |
        Copy-Item -Destination $sandbox -Recurse -Force
    New-Item (Join-Path $sandbox "data") -ItemType Directory | Out-Null
    $sentinel = Join-Path $sandbox "data\preserve-me.txt"
    Set-Content $sentinel "must survive runtime repair"
    if (Test-Path (Join-Path $sandbox "runtime\python.exe")) { throw "Smoke must begin without a runtime" }

    $currentPhase = "Phase A: bootstrap missing runtime"
    Write-Host $currentPhase
    $null = Invoke-StartBat -WorkingDirectory $sandbox
    Wait-Health
    $connection = Assert-LoopbackListener "Initial"
    $serverPid = $connection.OwningProcess
    Assert-Sentinel $sentinel "after initial bootstrap"

    $currentPhase = "Phase B: reuse valid runtime"
    Write-Host $currentPhase
    $runtime = Join-Path $sandbox "runtime"
    $before = Get-ChildItem $runtime -Recurse -File | Sort-Object FullName |
        ForEach-Object { "$($_.FullName.Substring($runtime.Length))|$($_.Length)|$($_.LastWriteTimeUtc.Ticks)" }
    $null = Invoke-StartBat -WorkingDirectory $sandbox
    $after = Get-ChildItem $runtime -Recurse -File | Sort-Object FullName |
        ForEach-Object { "$($_.FullName.Substring($runtime.Length))|$($_.Length)|$($_.LastWriteTimeUtc.Ticks)" }
    if (Compare-Object $before $after) { throw "Valid runtime was downloaded, rebuilt, or reinstalled on second launch" }
    if (Get-ChildItem $runtime -Filter "*.part" -Recurse -File) { throw "Incomplete download was retained as complete" }
    Assert-Sentinel $sentinel "after runtime reuse"
    Wait-Health 10

    $currentPhase = "Phase C: stop running server"
    Write-Host $currentPhase
    Stop-Process -Id $serverPid -Force
    Wait-ServerStopped -WorkingDirectory $sandbox -OwningProcessId $serverPid -TimeoutSeconds $releaseTimeoutSeconds
    $serverPid = $null

    $currentPhase = "Phase D: damage runtime"
    Write-Host $currentPhase
    $metadataTargets = @(Get-ChildItem (Join-Path $runtime "Lib\site-packages") -Directory -Filter "fastapi-*.dist-info")
    if ($metadataTargets.Count -ne 1) {
        throw "Expected exactly one fastapi dist-info damage target, found $($metadataTargets.Count)"
    }
    $damagedMetadataName = $metadataTargets[0].Name
    Remove-Item $metadataTargets[0].FullName -Recurse -Force
    if (Test-RuntimeValid $runtime) { throw "Failed to damage runtime deterministically" }

    $currentPhase = "Phase E: recover runtime"
    Write-Host $currentPhase
    $null = Invoke-StartBat -WorkingDirectory $sandbox
    Wait-Health

    $currentPhase = "Phase F: validate recovered runtime"
    Write-Host $currentPhase
    $connection = Assert-LoopbackListener "Recovered"
    $serverPid = $connection.OwningProcess
    Assert-RuntimeValid $runtime
    $restoredMetadata = @(Get-ChildItem (Join-Path $runtime "Lib\site-packages") -Directory -Filter "fastapi-*.dist-info")
    if ($restoredMetadata.Count -ne 1 -or $restoredMetadata[0].Name -ne $damagedMetadataName) {
        throw "Recovery did not restore the damaged fastapi dependency metadata"
    }
    if (Get-ChildItem $runtime -Filter "*.part" -Recurse -File) { throw "Recovery retained an incomplete .part download" }
    Assert-Sentinel $sentinel "after runtime recovery"
    Write-Host "Portable bootstrap, reuse, damaged-runtime recovery, health, data isolation, and loopback checks passed."
} catch {
    $failed = $true
    Write-FailureDiagnostics -WorkingDirectory $sandbox -Phase $currentPhase -Destination $artifacts
    throw
} finally {
    try {
        $listenerPids = @(Get-SmokeListeners | Select-Object -ExpandProperty OwningProcess -Unique)
        foreach ($processId in $listenerPids) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
        foreach ($process in @(Get-RuntimeProcesses $sandbox)) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Wait-ServerStopped -WorkingDirectory $sandbox -OwningProcessId $serverPid -TimeoutSeconds $releaseTimeoutSeconds
    } catch {
        Write-Warning "Smoke cleanup could not fully stop runtime processes: $($_.Exception.Message)"
    }
    try {
        Remove-Item $sandbox -Recurse -Force -ErrorAction Stop
    } catch {
        Write-Warning "Smoke cleanup could not remove sandbox: $($_.Exception.Message)"
    }
    if (-not $failed) { Remove-Item $artifacts -Recurse -Force -ErrorAction SilentlyContinue }
}
