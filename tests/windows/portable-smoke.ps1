$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sandbox = Join-Path $(if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }) "sklad ozon portable smoke"
$artifacts = Join-Path $root "test-artifacts\windows-portable"
$currentPhase = "setup"
$serverPid = $null
$failed = $false
$cleanupFailure = $null
$stopTimeoutSeconds = 20

function Get-SmokeListeners { @(Get-NetTCPConnection -LocalPort 17843 -State Listen -ErrorAction SilentlyContinue) }
function Get-RuntimeProcesses([string]$WorkingDirectory) {
    $python = [IO.Path]::GetFullPath((Join-Path $WorkingDirectory "runtime\python.exe"))
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath) -ieq $python) -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($python, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
}
function Wait-ServerStopped([string]$WorkingDirectory, [int]$TimeoutSeconds = 20) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $runtimeProcesses = @(Get-RuntimeProcesses $WorkingDirectory)
        $runtimeProcessIds = @($runtimeProcesses | Select-Object -ExpandProperty ProcessId)
        $sandboxListeners = @(Get-SmokeListeners | Where-Object { $runtimeProcessIds -contains $_.OwningProcess })
        if ($runtimeProcesses.Count -eq 0 -and $sandboxListeners.Count -eq 0) { return }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "Sandbox listener/runtime processes did not stop within $TimeoutSeconds seconds"
}
function Stop-SmokeServer([string]$WorkingDirectory) {
    $listeners = @(Get-SmokeListeners)
    $runtimeProcesses = @(Get-RuntimeProcesses $WorkingDirectory)
    $runtimeProcessIds = @($runtimeProcesses | Select-Object -ExpandProperty ProcessId)
    $foreignListeners = @($listeners | Where-Object { $runtimeProcessIds -notcontains $_.OwningProcess })
    $ownershipError = $null
    if ($foreignListeners.Count) {
        $foreignProcessIds = @($foreignListeners | Select-Object -ExpandProperty OwningProcess -Unique)
        $ownershipError = "Port 17843 has a listener not owned by the sandbox runtime (PID: $($foreignProcessIds -join ', ')); it was not stopped"
    }

    foreach ($runtimeProcessId in @($runtimeProcessIds | Select-Object -Unique)) {
        $confirmedProcessIds = @(Get-RuntimeProcesses $WorkingDirectory | Select-Object -ExpandProperty ProcessId)
        if ($confirmedProcessIds -contains $runtimeProcessId) {
            Stop-Process -Id $runtimeProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    Wait-ServerStopped $WorkingDirectory $stopTimeoutSeconds
    $script:serverPid = $null
    if ($ownershipError) { throw $ownershipError }
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
function Assert-WebApplication {
    $health = Invoke-WebRequest "http://127.0.0.1:17843/api/health" -TimeoutSec 5 -UseBasicParsing
    if ($health.StatusCode -ne 200) { throw "Health HTTP status was $($health.StatusCode)" }
    $index = Invoke-WebRequest "http://127.0.0.1:17843/" -TimeoutSec 5 -UseBasicParsing
    $expectedTitle = "Sklad Ozon"
    $expectedSection = -join @([char]0x041F, [char]0x043B, [char]0x0430, [char]0x043D)
    if ($index.StatusCode -ne 200 -or $index.Content -notmatch [regex]::Escape($expectedTitle) -or $index.Content -notmatch [regex]::Escape($expectedSection)) { throw "Application UI identity was not served" }
    foreach ($asset in @("/assets/css/app.css", "/assets/js/core.js", "/assets/js/components.js", "/assets/js/app.js")) {
        $response = Invoke-WebRequest "http://127.0.0.1:17843$asset" -TimeoutSec 5 -UseBasicParsing
        if ($response.StatusCode -ne 200) { throw "Asset $asset was not served" }
    }
}
function Invoke-StartBat([string]$WorkingDirectory, [int]$TimeoutSeconds = 300, [switch]$Offline) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = "$env:SystemRoot\System32\cmd.exe"
    $info.Arguments = "/d /c start.bat"
    $info.WorkingDirectory = $WorkingDirectory
    $info.UseShellExecute = $false
    if ($Offline) {
        $info.EnvironmentVariables["HTTP_PROXY"] = "http://127.0.0.1:9"
        $info.EnvironmentVariables["HTTPS_PROXY"] = "http://127.0.0.1:9"
        $info.EnvironmentVariables["ALL_PROXY"] = "http://127.0.0.1:9"
        $info.EnvironmentVariables["NO_PROXY"] = "127.0.0.1,localhost"
        $info.EnvironmentVariables["PIP_NO_INDEX"] = "1"
        $info.EnvironmentVariables["PATH"] = "$env:SystemRoot\System32"
    }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $process = [Diagnostics.Process]::Start($info)
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $process.Kill()
        throw "start.bat did not exit within $TimeoutSeconds seconds"
    }
    $watch.Stop()
    [pscustomobject]@{ ExitCode = $process.ExitCode; ElapsedSeconds = $watch.Elapsed.TotalSeconds }
}
function Test-RuntimeValid([string]$Runtime) {
    $python = Join-Path $Runtime "python.exe"
    if (-not (Test-Path $python)) { return $false }
    & $python -c "import sys,fastapi,uvicorn,openpyxl,multipart; from importlib.metadata import version; expected={'fastapi':'0.139.2','uvicorn':'0.51.0','openpyxl':'3.1.5','python-multipart':'0.0.32'}; raise SystemExit(sys.version_info[:3] != (3,13,14) or any(version(k)!=v for k,v in expected.items()))"
    return $LASTEXITCODE -eq 0
}
function Assert-Sentinel([string]$Path, [string]$Stage) {
    if ([IO.File]::ReadAllText($Path) -ne "must survive runtime repair") { throw "Seller data sentinel changed $Stage" }
}
function Assert-LoopbackListener([string]$Stage) {
    $listeners = @(Get-SmokeListeners)
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne "127.0.0.1") {
        throw "$Stage listener is not exactly loopback-only: $($listeners.LocalAddress -join ', ')"
    }
    $runtimeProcessIds = @(Get-RuntimeProcesses $sandbox | Select-Object -ExpandProperty ProcessId)
    if ($runtimeProcessIds -notcontains $listeners[0].OwningProcess) {
        throw "$Stage listener PID $($listeners[0].OwningProcess) is not owned by the sandbox runtime"
    }
    $script:serverPid = $listeners[0].OwningProcess
}
function Assert-NoPart([string]$Runtime) {
    if (@(Get-ChildItem $Runtime -Filter "*.part" -Recurse -File -ErrorAction SilentlyContinue).Count) { throw "Runtime contains a leftover .part file" }
}
function Get-RuntimeFingerprint([string]$Runtime) {
    @((Get-ChildItem $Runtime -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($Runtime.Length).TrimStart('\')
        "$relative|$($_.Length)|$($_.LastWriteTimeUtc.Ticks)"
    } | Sort-Object))
}
function Write-FailureDiagnostics([string]$WorkingDirectory, [string]$Phase, [string]$Destination) {
    try {
        Remove-Item $Destination -Recurse -Force -ErrorAction SilentlyContinue
        New-Item $Destination -ItemType Directory -Force | Out-Null
        foreach ($name in @("startup_status.json", "server_console.log", "launcher.log")) {
            $source = Join-Path $WorkingDirectory "data\$name"
            if (Test-Path $source) { Copy-Item $source $Destination -Force }
        }
        [ordered]@{
            phase = $Phase
            runtimePythonExists = Test-Path (Join-Path $WorkingDirectory "runtime\python.exe")
            listeners = @(Get-SmokeListeners | Select-Object LocalAddress, LocalPort, OwningProcess)
            runtimeProcesses = @(Get-RuntimeProcesses $WorkingDirectory | Select-Object ProcessId, Name, ExecutablePath, CommandLine)
        } | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Destination "diagnostics.json")
    } catch { Write-Warning "Failed to preserve diagnostics: $($_.Exception.Message)" }
}

try {
    Remove-Item $artifacts -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $sandbox -Recurse -Force -ErrorAction SilentlyContinue
    New-Item $sandbox -ItemType Directory | Out-Null
    Get-ChildItem $root -Force | Where-Object { $_.Name -notin @(".git", "runtime", "data", "test-artifacts") } | Copy-Item -Destination $sandbox -Recurse -Force
    New-Item (Join-Path $sandbox "data") -ItemType Directory | Out-Null
    $sentinel = Join-Path $sandbox "data\seller-data-sentinel.txt"
    [IO.File]::WriteAllText($sentinel, "must survive runtime repair")
    $runtime = Join-Path $sandbox "runtime"
    if (Test-Path $runtime) { throw "Smoke must begin without runtime/" }
    if (@(Get-SmokeListeners).Count) { throw "Port 17843 is already occupied before the portable smoke started." }

    $currentPhase = "Phase A: fresh online bootstrap"
    Write-Host $currentPhase
    $result = Invoke-StartBat $sandbox
    if ($result.ExitCode -ne 0) { throw "Fresh start.bat exited $($result.ExitCode)" }
    Wait-Health; Assert-WebApplication; Assert-LoopbackListener "Fresh bootstrap"
    if (-not (Test-RuntimeValid $runtime)) { throw "Fresh runtime validation failed" }
    Assert-Sentinel $sentinel "after fresh bootstrap"; Assert-NoPart $runtime

    $currentPhase = "Phase B: stop fresh server"
    Write-Host $currentPhase
    Stop-SmokeServer $sandbox

    $currentPhase = "Phase C: offline valid-runtime reuse"
    Write-Host $currentPhase
    $before = Get-RuntimeFingerprint $runtime
    $result = Invoke-StartBat $sandbox -Offline
    if ($result.ExitCode -ne 0) { throw "Offline reuse exited $($result.ExitCode)" }
    Wait-Health 30; Assert-WebApplication; Assert-LoopbackListener "Offline reuse"
    $after = Get-RuntimeFingerprint $runtime
    if (Compare-Object $before $after) { throw "Offline reuse changed the runtime fingerprint" }
    Assert-NoPart $runtime; Assert-Sentinel $sentinel "after offline reuse"

    $currentPhase = "Phase D: stop offline-reused server"
    Write-Host $currentPhase
    Stop-SmokeServer $sandbox

    $currentPhase = "Phase E: corrupt required runtime package"
    Write-Host $currentPhase
    $fastapi = Join-Path $runtime "Lib\site-packages\fastapi"
    if (-not (Test-Path $fastapi)) { throw "Required fastapi package directory is missing before corruption" }
    Remove-Item $fastapi -Recurse -Force
    if (Test-RuntimeValid $runtime) { throw "Damaged runtime unexpectedly validates" }

    $currentPhase = "Phase F: corrupt runtime offline rejection"
    Write-Host $currentPhase
    $result = Invoke-StartBat $sandbox -TimeoutSeconds 30 -Offline
    if ($result.ExitCode -eq 0) { throw "Corrupt offline launch unexpectedly succeeded" }
    if ($result.ElapsedSeconds -gt 30) { throw "Corrupt offline rejection exceeded 30 seconds" }
    if (@(Get-SmokeListeners).Count -or @(Get-RuntimeProcesses $sandbox).Count) { throw "Corrupt runtime started a service/process" }
    Assert-Sentinel $sentinel "after failed offline repair"
    $statusPath = Join-Path $sandbox "data\startup_status.json"
    if (-not (Test-Path $statusPath)) { throw "Repair status was not written" }
    $status = Get-Content $statusPath -Raw | ConvertFrom-Json
    if ($status.status -ne "error" -or $status.code -ne "RUNTIME_REPAIR_REQUIRED") { throw "Repair status contract is invalid" }
    if ($status.message -notmatch "(?i)connect to the internet" -or $status.message -notmatch "(?i)run start\.bat again" -or $status.message -notmatch "(?i)preserved") { throw "Repair guidance is not actionable" }
    Write-Host "Offline rejection exit=$($result.ExitCode), elapsed=$([Math]::Round($result.ElapsedSeconds, 2))s"

    $currentPhase = "Phase G: online recovery"
    Write-Host $currentPhase
    $result = Invoke-StartBat $sandbox
    if ($result.ExitCode -ne 0) { throw "Online recovery exited $($result.ExitCode)" }
    Wait-Health; Assert-WebApplication; Assert-LoopbackListener "Online recovery"
    if (-not (Test-RuntimeValid $runtime)) { throw "Recovered runtime validation failed" }
    Assert-NoPart $runtime; Assert-Sentinel $sentinel "after online recovery"

    $currentPhase = "Phase H: final cleanup"
    Write-Host $currentPhase
    Stop-SmokeServer $sandbox
    Write-Host "Offline portable release acceptance passed."
} catch {
    $failed = $true
    Write-FailureDiagnostics $sandbox $currentPhase $artifacts
    throw
} finally {
    try { Stop-SmokeServer $sandbox } catch { $cleanupFailure = $_.Exception.Message }
    try {
        Remove-Item $sandbox -Recurse -Force -ErrorAction Stop
        if (Test-Path $sandbox) { throw "Sandbox still exists after removal" }
    } catch { $cleanupFailure = "${cleanupFailure}; sandbox removal failed: $($_.Exception.Message)" }
    if (-not $failed -and -not $cleanupFailure) { Remove-Item $artifacts -Recurse -Force -ErrorAction SilentlyContinue }
    if ($cleanupFailure) { throw "Final cleanup failed: $cleanupFailure" }
}
