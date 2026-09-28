# VEYRA Phase 0 bootstrap + verification (Windows PowerShell 5.1 or 7).
#
#   Double-click scripts\bootstrap.cmd, or from the repo root:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 [-SkipDocker]
#
# Every step runs real commands. A step is PASS only if every command in it exists
# and exits 0; anything else is FAIL. The script exits 1 if any step fails.
# Log: docs\phase-reports\phase-0-verification.log (UTF-8).

param([switch]$SkipDocker)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$reportDir = Join-Path $root "docs\phase-reports"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$log = Join-Path $reportDir "phase-0-verification.log"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($log, "VEYRA Phase 0 verification - $(Get-Date -Format o)`r`n", $utf8)

function Log([string]$Line) {
  Write-Host $Line
  [IO.File]::AppendAllText($log, "$Line`r`n", $utf8)
}

$env:COREPACK_ENABLE_DOWNLOAD_PROMPT = "0"
$env:NEXT_TELEMETRY_DISABLED = "1"
$env:PYTHONUTF8 = "1"
$compose = @("compose", "-f", "infra/docker-compose.yml")

$results = New-Object System.Collections.Specialized.OrderedDictionary
$script:anyFail = $false

# Run a native command; stream + log its output; throw if missing or exit code != 0.
function Invoke-Native {
  param([Parameter(Mandatory = $true)][string]$Exe, [string[]]$Arguments = @())
  $cmd = Get-Command $Exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $cmd) { throw "command not found: $Exe" }
  Log "> $Exe $($Arguments -join ' ')"
  $global:LASTEXITCODE = 0
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"   # native stderr is not an error by itself
  try {
    & $cmd.Source @Arguments 2>&1 | ForEach-Object { Log "$_" }
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $prev }
  if ($code -ne 0) { throw "'$Exe $($Arguments -join ' ')' exited with code $code" }
}

function Step([string]$Name, [scriptblock]$Body) {
  Log ""
  Log "==> $Name"
  $sw = [Diagnostics.Stopwatch]::StartNew()
  try {
    & $Body
    $results[$Name] = "PASS"
  } catch {
    $results[$Name] = "FAIL - $($_.Exception.Message)"
    $script:anyFail = $true
    Log "!! FAIL: $($_.Exception.Message)"
  }
  Log ("   ({0:N1}s)" -f $sw.Elapsed.TotalSeconds)
}

function InDir([string]$Path, [scriptblock]$Body) {
  Push-Location (Join-Path $root $Path)
  try { & $Body } finally { Pop-Location }
}

function Assert-Http([string]$Url, [string]$MustContain = "") {
  $deadline = (Get-Date).AddSeconds(120)
  $last = "no response"
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
      if ($r.StatusCode -eq 200 -and ($MustContain -eq "" -or $r.Content -like "*$MustContain*")) {
        Log "   200 OK  $Url"
        return
      }
      $last = "status $($r.StatusCode), expected content '$MustContain' not found"
    } catch { $last = $_.Exception.Message }
    Start-Sleep -Seconds 3
  }
  throw "GET $Url failed: $last"
}

# pnpm without admin rights: `corepack enable` writes shims next to node.exe
# (C:\Program Files\nodejs), which fails with EPERM. Install shims into a
# user-writable folder instead and put it on PATH (process + user).
function Ensure-Pnpm {
  $existing = Get-Command pnpm -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($existing) {
    try { Invoke-Native pnpm @("--version"); return } catch { Log "existing pnpm is broken: $($_.Exception.Message)" }
  }
  $shimDir = Join-Path $env:LOCALAPPDATA "veyra\bin"
  New-Item -ItemType Directory -Force -Path $shimDir | Out-Null
  try {
    Invoke-Native corepack @("enable", "pnpm", "--install-directory", $shimDir)
  } catch {
    Log "corepack failed ($($_.Exception.Message)); falling back to npm (user prefix)"
    Invoke-Native npm @("install", "--global", "--prefix", $shimDir, "pnpm@10.28.0")
  }
  $env:Path = "$shimDir;$env:Path"
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  if (-not $userPath -or ($userPath -split ";") -notcontains $shimDir) {
    [Environment]::SetEnvironmentVariable("Path", "$shimDir;$userPath", "User")
    Log "added $shimDir to your user PATH (new terminals will find pnpm)"
  }
  Invoke-Native pnpm @("--version")
}

# ---------------------------------------------------------------- toolchain
Step "toolchain: node >= 22" {
  Invoke-Native node @("--version")
  $major = [int]((node --version).TrimStart("v").Split(".")[0])
  if ($major -lt 22) { throw "Node $major found; VEYRA needs Node >= 22" }
}
Step "toolchain: pnpm" { Ensure-Pnpm }
Step "toolchain: uv" {
  if (-not (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue)) {
    throw "uv not found. Install: powershell -ExecutionPolicy Bypass -c `"irm https://astral.sh/uv/install.ps1 | iex`""
  }
  Invoke-Native uv @("--version")
}

if (-not (Test-Path (Join-Path $root ".env"))) { Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env") }

# ---------------------------------------------------------------- install
Step "pnpm install" { Invoke-Native pnpm @("install") }
Step "pin dependency versions" {
  Invoke-Native node @("scripts/pin-versions.mjs")
  Invoke-Native pnpm @("install")
}
Step "uv sync (python 3.12)" {
  InDir "apps/api" {
    Invoke-Native uv @("python", "install", "3.12")
    Invoke-Native uv @("sync", "--python", "3.12")
  }
}

# ---------------------------------------------------------------- API client generation
Step "export OpenAPI schema" {
  InDir "apps/api" { Invoke-Native uv @("run", "python", "-m", "app.scripts.export_openapi", "../../packages/api-client/openapi.json") }
}
Step "generate @veyra/api-client" { Invoke-Native pnpm @("--filter", "@veyra/api-client", "generate") }
Step "api-client is current (--check)" { Invoke-Native pnpm @("--filter", "@veyra/api-client", "check") }

# ---------------------------------------------------------------- API checks
Step "api: ruff format" {
  InDir "apps/api" {
    Invoke-Native uv @("run", "ruff", "format", ".")
    Invoke-Native uv @("run", "ruff", "format", "--check", ".")
  }
}
Step "api: ruff check" { InDir "apps/api" { Invoke-Native uv @("run", "ruff", "check", ".") } }
Step "api: mypy" { InDir "apps/api" { Invoke-Native uv @("run", "mypy", "app") } }
Step "api: pytest (unit)" { InDir "apps/api" { Invoke-Native uv @("run", "pytest", "-v", "-m", "not integration") } }

# ---------------------------------------------------------------- web + packages
Step "pnpm typecheck" { Invoke-Native pnpm @("run", "typecheck") }
Step "pnpm lint" { Invoke-Native pnpm @("run", "lint") }
Step "pnpm test" { Invoke-Native pnpm @("run", "test") }
Step "pnpm build" { Invoke-Native pnpm @("run", "build") }

# ---------------------------------------------------------------- Docker / services
if ($SkipDocker) {
  $results["docker"] = "FAIL - skipped with -SkipDocker (Phase 0 requires it)"
  $script:anyFail = $true
} else {
  Step "docker: engine running" { Invoke-Native docker @("version", "--format", "{{.Server.Version}}") }
  Step "docker: compose config valid" { Invoke-Native docker ($compose + @("config", "--quiet")) }
  Step "docker: postgres + redis healthy" { Invoke-Native docker ($compose + @("up", "-d", "--wait", "postgres", "redis")) }
  Step "api: alembic upgrade head (real Postgres)" { InDir "apps/api" { Invoke-Native uv @("run", "alembic", "upgrade", "head") } }
  Step "api: pytest (integration, real Postgres + Redis)" {
    $env:VEYRA_REQUIRE_INFRA = "1"
    try { InDir "apps/api" { Invoke-Native uv @("run", "pytest", "-v", "-m", "integration") } }
    finally { Remove-Item Env:VEYRA_REQUIRE_INFRA -ErrorAction SilentlyContinue }
  }
  Step "docker: full stack build + up" { Invoke-Native docker ($compose + @("up", "-d", "--build", "--wait")) }
  Step "e2e: API /healthz" { Assert-Http "http://localhost:8000/healthz" '"ok"' }
  Step "e2e: API /readyz (db + redis)" { Assert-Http "http://localhost:8000/readyz" '"ready"' }
  Step "e2e: web home page" { Assert-Http "http://localhost:3000/" "VEYRA" }
  Step "e2e: web -> API proxy /api/v1/meta" { Assert-Http "http://localhost:3000/api/v1/meta" '"name":"VEYRA"' }
}

# ---------------------------------------------------------------- summary
Log ""
Log "===== SUMMARY ====="
foreach ($k in $results.Keys) { Log ("{0,-48} {1}" -f $k, $results[$k]) }
$passed = @($results.Values | Where-Object { $_ -eq "PASS" }).Count
Log ""
Log ("OVERALL: {0}  ({1}/{2} steps passed)" -f ($(if ($script:anyFail) { "FAIL" } else { "PASS" })), $passed, $results.Count)
if (-not $SkipDocker) { Log "Stack left running: http://localhost:3000  (stop: docker compose -f infra/docker-compose.yml down)" }
Log "Log: $log"
if ($script:anyFail) { exit 1 } else { exit 0 }
