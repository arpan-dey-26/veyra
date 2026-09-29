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

# JSON call that surfaces the API's RFC 9457 problem body on failure (code, detail, request id).
function Invoke-Api {
  param([string]$Method, [string]$Uri, $Body = $null, $Session, [hashtable]$Headers = @{})
  $args2 = @{ Uri = $Uri; Method = $Method; WebSession = $Session; Headers = $Headers; UseBasicParsing = $true }
  if ($null -ne $Body) { $args2.Body = ($Body | ConvertTo-Json -Compress); $args2.ContentType = "application/json" }
  try {
    $r = Invoke-WebRequest @args2
    if ($r.Content) { return ($r.Content | ConvertFrom-Json) } else { return $null }
  } catch {
    $detail = ""
    $resp = $_.Exception.Response
    if ($resp) {
      try { $detail = (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd() } catch { }
      throw "$Method $Uri -> $([int]$resp.StatusCode): $detail"
    }
    throw
  }
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
Step "ml: forecast model reproducible (retrain == committed artifact)" {
  InDir "apps/api" { Invoke-Native uv @("run", "python", "-m", "app.scripts.train_forecast", "--check") }
}

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
  Step "api: alembic check (models == migrations)" { InDir "apps/api" { Invoke-Native uv @("run", "alembic", "check") } }
  Step "api: pytest (integration, real Postgres + Redis)" {
    $env:VEYRA_REQUIRE_INFRA = "1"
    try { InDir "apps/api" { Invoke-Native uv @("run", "pytest", "-v", "-m", "integration") } }
    finally { Remove-Item Env:VEYRA_REQUIRE_INFRA -ErrorAction SilentlyContinue }
  }
  Step "docker: full stack build + up" {
    try { Invoke-Native docker ($compose + @("up", "-d", "--build", "--wait")) }
    catch {
      Log "---- api container logs (last 80 lines) ----"
      try { Invoke-Native docker ($compose + @("logs", "--no-color", "--tail", "80", "api")) } catch { }
      throw
    }
  }
  Step "docker: seed demo admin + demo facilities" {
    $env:VEYRA_DEMO_ADMIN_PASSWORD = "veyra-demo-console-2026"
    Invoke-Native docker ($compose + @("exec", "-T", "-e", "VEYRA_DEMO_ADMIN_PASSWORD", "api", "uv", "run", "--no-sync", "python", "-m", "app.scripts.seed_demo"))
    Log "   demo admin:    admin@veyra.demo    / veyra-demo-console-2026  (DEMO ONLY)"
    Log "   demo bank:     bank@veyra.demo     / veyra-demo-console-2026  (DEMO ONLY)"
    Log "   demo hospital: hospital@veyra.demo / veyra-demo-console-2026  (DEMO ONLY)"
  }
  Step "e2e: API /healthz" { Assert-Http "http://localhost:8000/healthz" '"ok"' }
  Step "e2e: API /readyz (db + redis)" { Assert-Http "http://localhost:8000/readyz" '"ready"' }
  Step "e2e: web home page" { Assert-Http "http://localhost:3000/" "VEYRA" }
  Step "e2e: web -> API proxy /api/v1/meta" { Assert-Http "http://localhost:3000/api/v1/meta" '"name":"VEYRA"' }
  Step "e2e: web pages render (register, sign-in, verify)" {
    Assert-Http "http://localhost:3000/register" "Become a donor"
    Assert-Http "http://localhost:3000/sign-in" "Sign in"
    Assert-Http "http://localhost:3000/verify" "Verify your mobile"
  }
  Step "e2e: donor register -> demo verify -> me -> update -> logout (via web proxy)" {
    $base = "http://localhost:3000/api/v1"
    $s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $tag = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $mobile = "9" + ([UInt64]("0x" + [Guid]::NewGuid().ToString("N").Substring(0, 15)) % 1000000000).ToString("000000000")
    $reg = Invoke-Api Post "$base/auth/register" @{ full_name = "Smoke Test"; email = "smoke-$tag@example.in"; mobile = $mobile;
      blood_group = "B+"; address = "1 Smoke Street"; city = "Kolkata"; state = "West Bengal"; pin_code = "700001";
      password = "smoke-test-passphrase" } $s
    if ($reg.verification.mode -ne "demo" -or -not $reg.verification.disclaimer) { throw "demo verification not labelled" }
    $me = Invoke-Api Post "$base/auth/verify" @{ challenge_id = $reg.verification.challenge_id; code = $mobile.Substring(6) } $s
    if ($me.user.status -ne "active") { throw "verify did not activate the account" }
    $csrf = ($s.Cookies.GetCookies("http://localhost:3000") | Where-Object Name -eq "veyra_csrf").Value
    $upd = Invoke-Api Patch "$base/donors/me" @{ city = "Durgapur" } $s @{ "X-CSRF-Token" = $csrf }
    if ($upd.city -ne "Durgapur") { throw "profile update failed" }
    Invoke-Api Post "$base/auth/logout" $null $s @{ "X-CSRF-Token" = $csrf } | Out-Null
    $stillIn = $true
    try { Invoke-Api Get "$base/auth/me" $null $s | Out-Null } catch { if ("$_" -like "*-> 401*") { $stillIn = $false } else { throw } }
    if ($stillIn) { throw "session still valid after logout" }
    Log "   donor journey OK ($($me.user.email))"
  }
  Step "e2e: demo admin can sign in" {
    $s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $me = Invoke-Api Post "http://localhost:3000/api/v1/auth/login" @{ email = "admin@veyra.demo"; password = "veyra-demo-console-2026" } $s
    if ($me.user.role -ne "ADMIN") { throw "admin login failed" }
  }
  Step "e2e: phase 2 donation -> request -> FEFO dispatch -> receive -> trace -> SSE" {
    $base = "http://localhost:3000/api/v1"
    $pw = "veyra-demo-console-2026"
    function Csrf($sess) { ($sess.Cookies.GetCookies("http://localhost:3000") | Where-Object Name -eq "veyra_csrf").Value }
    # A fresh donor for this run (unique mobile), verified with the DEMO last-4 check.
    $d = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $tag = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $mobile = "9" + ([UInt64]("0x" + [Guid]::NewGuid().ToString("N").Substring(0, 15)) % 1000000000).ToString("000000000")
    $reg = Invoke-Api Post "$base/auth/register" @{ full_name = "Network Smoke"; email = "net-$tag@example.in"; mobile = $mobile;
      blood_group = "O+"; address = "1 Smoke Street"; city = "Kolkata"; state = "West Bengal"; pin_code = "700001";
      password = "smoke-test-passphrase" } $d
    Invoke-Api Post "$base/auth/verify" @{ challenge_id = $reg.verification.challenge_id; code = $mobile.Substring(6) } $d | Out-Null
    $bank = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $hosp = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    Invoke-Api Post "$base/auth/login" @{ email = "bank@veyra.demo"; password = $pw } $bank | Out-Null
    $bankFacility = Invoke-Api Get "$base/facilities/me" $null $bank
    Invoke-Api Post "$base/auth/login" @{ email = "hospital@veyra.demo"; password = $pw } $hosp | Out-Null
    # Blood bank: find the donor, record a donation (2 labelled bags).
    $found = Invoke-Api Post "$base/donors/lookup" @{ mobile = $mobile } $bank @{ "X-CSRF-Token" = (Csrf $bank) }
    $don = Invoke-Api Post "$base/donations" @{ donor_id = $found.donor_id; blood_group = "O+"; volume_ml = 450; components = @("PRBC", "FFP") } $bank @{ "X-CSRF-Token" = (Csrf $bank) }
    if (@($don.bags).Count -ne 2) { throw "donation did not create 2 bags" }
    # Hospital: banded availability (internal + SIMULATED partners), then an idempotent request.
    $avail = Invoke-Api Get "$base/network/availability?blood_group=O%2B&component=PRBC&units=1" $null $hosp
    if (-not (@($avail.results) | Where-Object { $_.target_ref -eq $bankFacility.id })) { throw "demo bank missing from availability" }
    if (-not (@($avail.results) | Where-Object { $_.source.simulated -eq $true })) { throw "simulated partners not labelled" }
    $key = "e2e-$tag"
    $body = @{ provider = "internal"; target_ref = $bankFacility.id; blood_group = "O+"; component = "PRBC"; units = 1; urgency = "urgent";
      needed_by = (Get-Date).ToUniversalTime().AddHours(6).ToString("yyyy-MM-ddTHH:mm:ssZ") }
    $req = Invoke-Api Post "$base/requests" $body $hosp @{ "X-CSRF-Token" = (Csrf $hosp); "Idempotency-Key" = $key }
    $again = Invoke-Api Post "$base/requests" $body $hosp @{ "X-CSRF-Token" = (Csrf $hosp); "Idempotency-Key" = $key }
    if ($again.id -ne $req.id) { throw "Idempotency-Key replay created a second request" }
    # Blood bank dispatches (FEFO), hospital confirms receipt.
    $ful = Invoke-Api Post "$base/requests/$($req.id)/fulfil" @{} $bank @{ "X-CSRF-Token" = (Csrf $bank) }
    if ($ful.status -ne "dispatched" -or @($ful.bags).Count -ne 1) { throw "fulfil failed" }
    $rec = Invoke-Api Post "$base/requests/$($req.id)/receive" $null $hosp @{ "X-CSRF-Token" = (Csrf $hosp) }
    if ($rec.status -ne "fulfilled") { throw "receive failed" }
    # Trace: 3 chained events, verified.
    $bagId = @($ful.bags)[0].public_id
    $trace = Invoke-Api Get "$base/bags/$bagId" $null $hosp
    if (@($trace.events).Count -ne 3 -or -not $trace.chain.valid) { throw "trace chain not valid" }
    # SSE replay (once=true) through the web proxy carries the request lifecycle.
    $sse = Invoke-WebRequest -Uri "$base/stream?once=true&after=0" -WebSession $hosp -UseBasicParsing
    if ($sse.Content -notlike "*event: request.fulfilled*" -or $sse.Content -notlike "*$($req.id)*") { throw "SSE replay missing events" }
    Log "   network journey OK (request $($req.reference), bag $bagId)"
  }
  Step "e2e: phase 3 dashboards + live network graph (scoped, via web proxy)" {
    $base = "http://localhost:3000/api/v1"
    $pw = "veyra-demo-console-2026"
    $bank = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $hosp = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $adm = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    Invoke-Api Post "$base/auth/login" @{ email = "bank@veyra.demo"; password = $pw } $bank | Out-Null
    Invoke-Api Post "$base/auth/login" @{ email = "hospital@veyra.demo"; password = $pw } $hosp | Out-Null
    Invoke-Api Post "$base/auth/login" @{ email = "admin@veyra.demo"; password = $pw } $adm | Out-Null
    $bd = Invoke-Api Get "$base/dashboard/facility" $null $bank
    if ($bd.kind -ne "BLOOD_BANK" -or @($bd.expiry).Count -ne 6 -or @($bd.movements).Count -ne 14) { throw "blood bank dashboard shape" }
    $hd = Invoke-Api Get "$base/dashboard/facility" $null $hosp
    if ($hd.kind -ne "HOSPITAL" -or $hd.donations.applicable) { throw "hospital dashboard shape" }
    $ad = Invoke-Api Get "$base/dashboard/admin" $null $adm
    if ($ad.users_total -lt 3) { throw "admin dashboard counts" }
    foreach ($row in @($ad.audit.recent)) { if ($row.PSObject.Properties.Name -contains "ip") { throw "audit summary leaks ip" } }
    $g = Invoke-Api Get "$base/network/graph" $null $hosp
    if ($g.note -notlike "*not a geographic map*") { throw "network graph not labelled" }
    if (@($g.nodes | Where-Object { $_.kind -eq "HOSPITAL" -and -not $_.is_self }).Count -ne 0) { throw "hospital sees other hospitals" }
    $denied = $false
    try { Invoke-Api Get "$base/dashboard/admin" $null $hosp | Out-Null } catch { if ("$_" -like "*-> 403*") { $denied = $true } else { throw } }
    if (-not $denied) { throw "hospital could read the admin dashboard" }
    Assert-Http "http://localhost:3000/" "What is real, and what is simulated"
    Log "   dashboards OK (bank on hand $($bd.on_hand), hospital open $($hd.requests.open), graph $(@($g.nodes).Count) nodes)"
  }
  Step "e2e: phase 4 synthetic ML forecast (scoped, disclaimer, RBAC, via web proxy)" {
    $base = "http://localhost:3000/api/v1"
    $pw = "veyra-demo-console-2026"
    $hosp = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $bank = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $adm = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    Invoke-Api Post "$base/auth/login" @{ email = "hospital@veyra.demo"; password = $pw } $hosp | Out-Null
    Invoke-Api Post "$base/auth/login" @{ email = "bank@veyra.demo"; password = $pw } $bank | Out-Null
    Invoke-Api Post "$base/auth/login" @{ email = "admin@veyra.demo"; password = $pw } $adm | Out-Null
    $hf = Invoke-Api Get "$base/facilities/me" $null $hosp
    $bf = Invoke-Api Get "$base/facilities/me" $null $bank
    # Hospital: open the dashboard page, request a forecast, check chart/table data + labelling.
    Assert-Http "http://localhost:3000/hospital" ""
    $f = Invoke-Api Get "$base/forecast/demand?blood_group=O%2B&component=PRBC&horizon=7" $null $hosp
    if ($f.scope -ne "facility" -or $f.facility_id -ne $hf.id) { throw "hospital forecast not scoped to its facility" }
    if (@($f.history).Count -ne 28 -or @($f.forecast).Count -ne 7) { throw "forecast series shape" }
    foreach ($p in @($f.forecast)) { if ($p.lower -gt $p.predicted -or $p.predicted -gt $p.upper) { throw "interval does not contain the forecast" } }
    if ($f.source.kind -ne "synthetic" -or -not $f.source.simulated) { throw "forecast not labelled synthetic" }
    if ($f.disclaimer -notlike "*not clinical guidance*") { throw "forecast disclaimer missing" }
    if (@("normal", "elevated", "high") -notcontains $f.signal.status) { throw "unexpected signal status" }
    $again = Invoke-Api Get "$base/forecast/demand?blood_group=O%2B&component=PRBC&horizon=7" $null $hosp
    if (($again.forecast | ConvertTo-Json -Compress) -ne ($f.forecast | ConvertTo-Json -Compress)) { throw "forecast not deterministic" }
    # Scope: a hospital cannot read the bank's forecast; horizon is bounded.
    $blocked = $false
    try { Invoke-Api Get "$base/forecast/demand?blood_group=O%2B&facility_id=$($bf.id)" $null $hosp | Out-Null } catch { if ("$_" -like "*-> 404*") { $blocked = $true } else { throw } }
    if (-not $blocked) { throw "hospital read another facility's forecast" }
    $bounded = $false
    try { Invoke-Api Get "$base/forecast/demand?blood_group=O%2B&horizon=15" $null $hosp | Out-Null } catch { if ("$_" -like "*-> 422*") { $bounded = $true } else { throw } }
    if (-not $bounded) { throw "horizon > 14 accepted" }
    # Blood bank: supply vs forecast uses its own real stock.
    Assert-Http "http://localhost:3000/blood-bank" ""
    $bs = Invoke-Api Get "$base/forecast/summary?horizon=7" $null $bank
    if ($bs.facility_id -ne $bf.id -or @($bs.rows).Count -ne 24) { throw "bank summary shape/scope" }
    if (@($bs.rows | Where-Object { $null -eq $_.stock_available }).Count -ne 0) { throw "bank summary lacks stock" }
    # Admin: network aggregate + model card.
    $as = Invoke-Api Get "$base/forecast/summary?horizon=7" $null $adm
    if ($as.scope -ne "network") { throw "admin summary is not network-level" }
    $card = Invoke-Api Get "$base/forecast/model" $null $adm
    if ($card.fingerprint -ne $f.model.fingerprint -or $card.disclaimer -notlike "*not a certified medical prediction system*") { throw "model card mismatch" }
    if ($card.one_step.gbm.mae -ge $card.one_step.baseline.mae) { throw "GBM does not beat the baseline" }
    # Donor: denied.
    $d = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $tag = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $mobile = "9" + ([UInt64]("0x" + [Guid]::NewGuid().ToString("N").Substring(0, 15)) % 1000000000).ToString("000000000")
    $reg = Invoke-Api Post "$base/auth/register" @{ full_name = "Forecast Smoke"; email = "fc-$tag@example.in"; mobile = $mobile;
      blood_group = "A+"; address = "1 Smoke Street"; city = "Kolkata"; state = "West Bengal"; pin_code = "700001";
      password = "smoke-test-passphrase" } $d
    Invoke-Api Post "$base/auth/verify" @{ challenge_id = $reg.verification.challenge_id; code = $mobile.Substring(6) } $d | Out-Null
    $denied = $false
    try { Invoke-Api Get "$base/forecast/summary" $null $d | Out-Null } catch { if ("$_" -like "*-> 403*") { $denied = $true } else { throw } }
    if (-not $denied) { throw "donor could read operational forecasts" }
    Log "   forecast OK (model $($card.name) v$($card.version) $($card.fingerprint); O+ PRBC 7d = $($f.forecast_total) units, signal $($f.signal.status))"
  }
  Step "e2e: phase 5 simulated IoT cold chain (excursion -> trace -> SSE, scoped)" {
    $base = "http://localhost:3000/api/v1"
    $pw = "veyra-demo-console-2026"
    function Csrf($sess) { ($sess.Cookies.GetCookies("http://localhost:3000") | Where-Object Name -eq "veyra_csrf").Value }
    $bank = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $hosp = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $adm = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    Invoke-Api Post "$base/auth/login" @{ email = "bank@veyra.demo"; password = $pw } $bank | Out-Null
    Invoke-Api Post "$base/auth/login" @{ email = "hospital@veyra.demo"; password = $pw } $hosp | Out-Null
    Invoke-Api Post "$base/auth/login" @{ email = "admin@veyra.demo"; password = $pw } $adm | Out-Null
    # Current head of the outbox (admin sees every event), so the SSE replay below covers only this run.
    $head = 0
    while ($true) {
      $page = (Invoke-WebRequest -Uri "$base/stream?once=true&after=$head" -WebSession $adm -UseBasicParsing).Content
      $ids = @([regex]::Matches($page, "(?m)^id: (\d+)") | ForEach-Object { [int64]$_.Groups[1].Value })
      if ($ids.Count -eq 0) { break }
      $head = ($ids | Measure-Object -Maximum).Maximum
    }
    # A fresh donor + donation gives the bank a bag it holds (the donor is reused for the 403 check).
    $d = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $tag = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $mobile = "9" + ([UInt64]("0x" + [Guid]::NewGuid().ToString("N").Substring(0, 15)) % 1000000000).ToString("000000000")
    $reg = Invoke-Api Post "$base/auth/register" @{ full_name = "Cold Chain Smoke"; email = "cc-$tag@example.in"; mobile = $mobile;
      blood_group = "B+"; address = "1 Smoke Street"; city = "Kolkata"; state = "West Bengal"; pin_code = "700001";
      password = "smoke-test-passphrase" } $d
    Invoke-Api Post "$base/auth/verify" @{ challenge_id = $reg.verification.challenge_id; code = $mobile.Substring(6) } $d | Out-Null
    $found = Invoke-Api Post "$base/donors/lookup" @{ mobile = $mobile } $bank @{ "X-CSRF-Token" = (Csrf $bank) }
    $don = Invoke-Api Post "$base/donations" @{ donor_id = $found.donor_id; blood_group = "B+"; volume_ml = 450; components = @("PRBC") } $bank @{ "X-CSRF-Token" = (Csrf $bank) }
    $bagId = @($don.bags)[0].public_id
    # Blood bank: smart-bag monitoring page, then select the bag and drive the DEMO simulator.
    Assert-Http "http://localhost:3000/blood-bank" ""
    $mon = Invoke-Api Get "$base/telemetry/monitored" $null $bank
    if (-not $mon.simulator_enabled -or $mon.scope -ne "facility") { throw "telemetry simulator not enabled for the demo bank" }
    if ($mon.disclaimer -notlike "*not a certified medical monitoring system*") { throw "monitor disclaimer missing" }
    Assert-Http "http://localhost:3000/bags/$bagId" ""
    $h = @{ "X-CSRF-Token" = (Csrf $bank) }
    $att = Invoke-Api Post "$base/simulator/bags/$bagId/attach" $null $bank $h
    if (-not $att.device.simulated -or $att.device.device_id -notlike "SIM-*") { throw "device not labelled simulated" }
    $r = Invoke-Api Post "$base/simulator/bags/$bagId/tick" @{ count = 3 } $bank $h
    if ($r.summary.cold_chain_status -ne "normal") { throw "baseline readings not normal" }
    Invoke-Api Post "$base/simulator/bags/$bagId/excursion" $null $bank $h | Out-Null
    $w = Invoke-Api Post "$base/simulator/bags/$bagId/tick" @{ count = 1 } $bank $h
    if (@($w.transitions) -notcontains "temperature.warning") { throw "no warning after excursion" }
    $c = Invoke-Api Post "$base/simulator/bags/$bagId/tick" @{ count = 2 } $bank $h
    if (@($c.transitions) -notcontains "temperature.critical" -or -not $c.summary.excursion_active) { throw "no critical after excursion" }
    Invoke-Api Post "$base/simulator/bags/$bagId/recover" $null $bank $h | Out-Null
    $rec = Invoke-Api Post "$base/simulator/bags/$bagId/tick" @{ count = 2 } $bank $h
    if (@($rec.transitions) -notcontains "temperature.recovered" -or $rec.summary.cold_chain_status -ne "normal") { throw "no recovery" }
    # Reads: telemetry, summary, cold-chain report, device; trace stays hash-chained and valid.
    $series = Invoke-Api Get "$base/bags/$bagId/telemetry" $null $bank
    if (@($series.readings).Count -ne 8 -or $series.disclaimer -notlike "*student engineering prototype*") { throw "telemetry series" }
    $sum = Invoke-Api Get "$base/bags/$bagId/telemetry/summary" $null $bank
    if ($sum.max_c -le $sum.thresholds.critical_high) { throw "summary max did not record the excursion" }
    $cc = Invoke-Api Get "$base/bags/$bagId/cold-chain" $null $bank
    $types = (@($cc.trace_events) | ForEach-Object { $_.event_type }) -join ","
    if ($types -ne "DEVICE_ATTACHED,TEMP_EXCURSION,TEMP_EXCURSION,TEMP_RECOVERED" -or -not $cc.chain_valid) { throw "cold-chain trace: $types" }
    if (@($cc.excursions).Count -ne 1 -or @($cc.excursions)[0].severity -ne "critical") { throw "excursion report" }
    $dev = Invoke-Api Get "$base/bags/$bagId/device" $null $bank
    if ($dev.readings_count -ne 8) { throw "device reading count" }
    $trace = Invoke-Api Get "$base/bags/$bagId" $null $bank
    if (@($trace.events).Count -ne 5 -or -not $trace.chain.valid -or $trace.bag.status -ne "available") { throw "bag trace after telemetry" }
    # SSE: Last-Event-ID replay through the web proxy carries the cold-chain alerts for this bag.
    $sse = (Invoke-WebRequest -Uri "$base/stream?once=true" -Headers @{ "Last-Event-ID" = "$head" } -WebSession $bank -UseBasicParsing).Content
    foreach ($t in @("telemetry.updated", "temperature.warning", "temperature.critical", "temperature.recovered")) {
      if ($sse -notlike "*event: $t*") { throw "SSE replay missing $t" }
    }
    if ($sse -notlike "*$bagId*") { throw "SSE replay missing the bag" }
    # Another facility: no telemetry, no simulator, no events for this bag.
    foreach ($path in @("bags/$bagId/telemetry", "bags/$bagId/telemetry/summary", "bags/$bagId/cold-chain", "bags/$bagId/device")) {
      $hidden = $false
      try { Invoke-Api Get "$base/$path" $null $hosp | Out-Null } catch { if ("$_" -like "*-> 404*") { $hidden = $true } else { throw } }
      if (-not $hidden) { throw "hospital could read $path" }
    }
    $blocked = $false
    try { Invoke-Api Post "$base/simulator/bags/$bagId/tick" @{ count = 1 } $hosp @{ "X-CSRF-Token" = (Csrf $hosp) } | Out-Null } catch { if ("$_" -like "*-> 404*") { $blocked = $true } else { throw } }
    if (-not $blocked) { throw "hospital could drive another facility's simulator" }
    $hsse = (Invoke-WebRequest -Uri "$base/stream?once=true&after=$head" -WebSession $hosp -UseBasicParsing).Content
    if ($hsse -like "*$bagId*") { throw "hospital received another facility's telemetry events" }
    # Admin: network-level view. Donor: denied.
    $net = Invoke-Api Get "$base/telemetry/monitored" $null $adm
    if ($net.scope -ne "network" -or -not (@($net.bags) | Where-Object { $_.public_id -eq $bagId })) { throw "admin network view" }
    $denied = $false
    try { Invoke-Api Get "$base/bags/$bagId/telemetry" $null $d | Out-Null } catch { if ("$_" -like "*-> 403*") { $denied = $true } else { throw } }
    if (-not $denied) { throw "donor could read bag telemetry" }
    Log "   cold chain OK (bag $bagId, device $($dev.device_id), peak $($sum.max_c) C, $(@($series.readings).Count) simulated readings)"
  }
  Step "e2e: phase 6 emergency operations (priority, recommendation, confirmed dispatch, scoped)" {
    $base = "http://localhost:3000/api/v1"
    $pw = "veyra-demo-console-2026"
    function Csrf($sess) { ($sess.Cookies.GetCookies("http://localhost:3000") | Where-Object Name -eq "veyra_csrf").Value }
    function Status-Of([scriptblock]$Call) {
      try { & $Call | Out-Null; return 200 } catch { if ("$_" -match "-> (\d{3})") { return [int]$Matches[1] } else { throw } }
    }
    $bank = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $hosp = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $adm = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    Invoke-Api Post "$base/auth/login" @{ email = "bank@veyra.demo"; password = $pw } $bank | Out-Null
    Invoke-Api Post "$base/auth/login" @{ email = "hospital@veyra.demo"; password = $pw } $hosp | Out-Null
    Invoke-Api Post "$base/auth/login" @{ email = "admin@veyra.demo"; password = $pw } $adm | Out-Null
    $bf = Invoke-Api Get "$base/facilities/me" $null $bank
    $hf = Invoke-Api Get "$base/facilities/me" $null $hosp
    $head = 0
    while ($true) {
      $page = (Invoke-WebRequest -Uri "$base/stream?once=true&after=$head" -WebSession $adm -UseBasicParsing).Content
      $ids = @([regex]::Matches($page, "(?m)^id: (\d+)") | ForEach-Object { [int64]$_.Groups[1].Value })
      if ($ids.Count -eq 0) { break }
      $head = ($ids | Measure-Object -Maximum).Maximum
    }
    # An unrelated hospital (onboarded once through the normal admin + invite flow, then reused).
    $other = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $otherEmail = "ops-e2e-unrelated@example.in"
    $otherPw = "unrelated-hospital-smoke-2026"
    try { Invoke-Api Post "$base/auth/login" @{ email = $otherEmail; password = $otherPw } $other | Out-Null } catch {
      $tag0 = [Guid]::NewGuid().ToString("N").Substring(0, 6)
      $fac = Invoke-Api Post "$base/admin/facilities" @{ type = "HOSPITAL"; name = "E2E Unrelated Hospital $tag0"; registration_number = "E2E-OPS-$tag0";
        address = "9 Smoke Lane"; city = "Howrah"; state = "West Bengal"; pin_code = "711101" } $adm @{ "X-CSRF-Token" = (Csrf $adm) }
      $inv = Invoke-Api Post "$base/admin/facilities/$($fac.id)/invites" @{ email = $otherEmail } $adm @{ "X-CSRF-Token" = (Csrf $adm) }
      $token = $inv.accept_path.Split("/")[-1]
      Invoke-Api Post "$base/auth/invites/accept" @{ token = $token; full_name = "Ops Smoke Coordinator"; mobile = "9123400099"; password = $otherPw } $other | Out-Null
    }
    # Two fresh donations of AB- PRBC; the first bag gets a SIMULATED critical excursion.
    $bags = @()
    foreach ($n in 1..2) {
      $d = New-Object Microsoft.PowerShell.Commands.WebRequestSession
      $tag = [Guid]::NewGuid().ToString("N").Substring(0, 8)
      $mobile = "9" + ([UInt64]("0x" + [Guid]::NewGuid().ToString("N").Substring(0, 15)) % 1000000000).ToString("000000000")
      $reg = Invoke-Api Post "$base/auth/register" @{ full_name = "Ops Smoke"; email = "ops-$tag@example.in"; mobile = $mobile;
        blood_group = "AB-"; address = "1 Smoke Street"; city = "Kolkata"; state = "West Bengal"; pin_code = "700001";
        password = "smoke-test-passphrase" } $d
      Invoke-Api Post "$base/auth/verify" @{ challenge_id = $reg.verification.challenge_id; code = $mobile.Substring(6) } $d | Out-Null
      $found = Invoke-Api Post "$base/donors/lookup" @{ mobile = $mobile } $bank @{ "X-CSRF-Token" = (Csrf $bank) }
      $don = Invoke-Api Post "$base/donations" @{ donor_id = $found.donor_id; blood_group = "AB-"; volume_ml = 450; components = @("PRBC") } $bank @{ "X-CSRF-Token" = (Csrf $bank) }
      $bags += @($don.bags)[0].public_id
      $donor = $d
    }
    $hot = $bags[0]
    $h = @{ "X-CSRF-Token" = (Csrf $bank) }
    Invoke-Api Post "$base/simulator/bags/$hot/attach" $null $bank $h | Out-Null
    Invoke-Api Post "$base/simulator/bags/$hot/excursion" $null $bank $h | Out-Null
    Invoke-Api Post "$base/simulator/bags/$hot/tick" @{ count = 3 } $bank $h | Out-Null
    # Hospital: an emergency request.
    $req = Invoke-Api Post "$base/requests" @{ provider = "internal"; target_ref = $bf.id; blood_group = "AB-"; component = "PRBC"; units = 1;
      urgency = "emergency"; needed_by = (Get-Date).ToUniversalTime().AddHours(2).ToString("yyyy-MM-ddTHH:mm:ssZ") } $hosp @{ "X-CSRF-Token" = (Csrf $hosp) }
    # Blood bank: operations view -> emergency request, priority reasons.
    Assert-Http "http://localhost:3000/blood-bank" ""
    $queue = Invoke-Api Get "$base/operations/requests" $null $bank
    $item = @($queue.requests) | Where-Object { $_.id -eq $req.id }
    if (-not $item -or $item.urgency -ne "emergency") { throw "emergency request missing from the operations queue" }
    if (@($item.priority.reasons | ForEach-Object { $_.text }) -notcontains "Emergency request") { throw "priority reasons missing" }
    if ($queue.disclaimer -notlike "*Recommendations are not clinical decisions or medical advice*") { throw "ops disclaimer missing" }
    $prio = Invoke-Api Get "$base/operations/requests/$($req.id)/priority" $null $bank
    if (@("immediate", "high") -notcontains $prio.band -or $prio.label -notlike "Operational recommendation*prototype") { throw "priority band/label: $($prio.band) $($prio.label)" }
    # Recommendation: candidates, ranking reasons, cold-chain state; nothing dispatched yet.
    $rec = Invoke-Api Get "$base/operations/requests/$($req.id)/recommendations" $null $bank
    $hotCand = @($rec.candidates) | Where-Object { $_.public_id -eq $hot }
    if (-not $hotCand -or $hotCand.cold_chain_state -ne "critical" -or -not $hotCand.deprioritized) { throw "critical bag not deprioritised" }
    if (@($hotCand.reasons | ForEach-Object { $_.code }) -notcontains "cold_chain_critical") { throw "deprioritisation not explained" }
    if (@($rec.recommended_bag_ids).Count -ne 1 -or @($rec.recommended_bag_ids) -contains $hot) { throw "unexpected recommendation: $($rec.recommended_bag_ids)" }
    foreach ($c in @($rec.candidates)) { if ($c.current_facility_id -ne $bf.id -or -not $c.reasons) { throw "candidate scope/reasons" } }
    if ($rec.human_confirmation -notlike "*Nothing is dispatched automatically*") { throw "human confirmation note missing" }
    if ((Invoke-Api Get "$base/requests/$($req.id)" $null $bank).status -ne "pending") { throw "recommendation dispatched something" }
    # Forecast pressure + simulated routing.
    $pressure = Invoke-Api Get "$base/operations/facilities/$($bf.id)/pressure" $null $bank
    $row = @($pressure.rows) | Where-Object { $_.blood_group -eq "AB-" -and $_.component -eq "PRBC" }
    if (-not $row -or $row.open_units -lt 1 -or $pressure.source.kind -ne "synthetic") { throw "pressure row" }
    if (@("normal", "watch", "elevated") -notcontains $row.level) { throw "pressure level" }
    if (-not $rec.route -or $rec.route.source.kind -ne "simulated" -or $rec.route.eta_minutes -le 0) { throw "simulated route" }
    $est = Invoke-Api Get "$base/operations/routing/estimate?source_facility_id=$($bf.id)&destination_facility_id=$($hf.id)&urgency=emergency" $null $bank
    if ($est.distance_km -ne $rec.route.distance_km) { throw "routing not deterministic" }
    # Explicit, human-confirmed dispatch through the existing workflow.
    $ful = Invoke-Api Post "$base/requests/$($req.id)/fulfil" @{ bag_public_ids = @($rec.recommended_bag_ids) } $bank @{ "X-CSRF-Token" = (Csrf $bank) }
    if ($ful.status -ne "dispatched" -or (@($ful.bags)[0].public_id) -ne @($rec.recommended_bag_ids)[0]) { throw "confirmed dispatch" }
    # SSE (Last-Event-ID replay through the web proxy), scoped.
    $sse = (Invoke-WebRequest -Uri "$base/stream?once=true" -Headers @{ "Last-Event-ID" = "$head" } -WebSession $bank -UseBasicParsing).Content
    foreach ($t in @("request.operational_alert", "allocation.recommendation_updated", "routing.updated", "cold_chain.operational_alert")) {
      if ($sse -notlike "*event: $t*") { throw "bank SSE missing $t" }
    }
    $hsse = (Invoke-WebRequest -Uri "$base/stream?once=true" -Headers @{ "Last-Event-ID" = "$head" } -WebSession $hosp -UseBasicParsing).Content
    if ($hsse -notlike "*event: routing.updated*" -or $hsse -like "*allocation.recommendation_updated*") { throw "hospital SSE scope" }
    $osse = (Invoke-WebRequest -Uri "$base/stream?once=true&after=$head" -WebSession $other -UseBasicParsing).Content
    if ($osse -like "*$($req.id)*") { throw "unrelated hospital received the request's events" }
    # Audit: the state changes are recorded (summary has no ip/meta).
    $ad = Invoke-Api Get "$base/dashboard/admin" $null $adm
    $actions = @($ad.audit.recent | ForEach-Object { $_.action })
    foreach ($a in @("blood_request.created", "blood_request.dispatched", "telemetry.readings_generated")) { if ($actions -notcontains $a) { throw "audit missing $a" } }
    # Hospital sees its own result (with a simulated ETA), then confirms receipt.
    $mine = Invoke-Api Get "$base/operations/requests" $null $hosp
    $own = @($mine.requests) | Where-Object { $_.id -eq $req.id }
    if (-not $own -or $own.status -ne "dispatched" -or $own.route.eta_minutes -le 0) { throw "hospital view of its request" }
    if (@($own.priority.reasons | ForEach-Object { $_.text }) -match "\d+ units without") { throw "exact bank stock leaked to hospital" }
    Invoke-Api Post "$base/requests/$($req.id)/receive" $null $hosp @{ "X-CSRF-Token" = (Csrf $hosp) } | Out-Null
    # Unrelated facility: 404. Donor: 403.
    foreach ($path in @("operations/requests/$($req.id)/priority", "requests/$($req.id)", "operations/facilities/$($bf.id)/pressure")) {
      $code = Status-Of { Invoke-Api Get "$base/$path" $null $other }
      if ($code -ne 404) { throw "unrelated hospital got $code for $path" }
    }
    if ((Status-Of { Invoke-Api Get "$base/operations/requests/$($req.id)/recommendations" $null $hosp }) -ne 403) { throw "hospital read bag recommendations" }
    if ((Status-Of { Invoke-Api Get "$base/operations/requests" $null $donor }) -ne 403) { throw "donor read operations" }
    if ((Status-Of { Invoke-Api Get "$base/operations/alerts" $null $donor }) -ne 403) { throw "donor read alerts" }
    # Cleanup by a person, not the engine: the bank discards the simulated-excursion bag.
    Invoke-Api Post "$base/bags/$hot/discard" @{ reason = "other"; note = "E2E cleanup after simulated cold-chain excursion" } $bank @{ "X-CSRF-Token" = (Csrf $bank) } | Out-Null
    Log "   operations OK (request $($req.reference) band $($prio.band) score $($prio.score); dispatched $(@($rec.recommended_bag_ids)[0]), skipped critical $hot; ETA $($rec.route.eta_minutes) min simulated)"
  }
}

# ---------------------------------------------------------------- summary
Log ""
Log "===== SUMMARY ====="
foreach ($k in $results.Keys) { Log ("{0,-48} {1}" -f $k, $results[$k]) }
$passed = @($results.Values | Where-Object { $_ -eq "PASS" }).Count
Log ""
Log ("OVERALL: {0}  ({1}/{2} steps passed)" -f ($(if ($script:anyFail) { "FAIL" } else { "PASS" })), $passed, $results.Count)
if (-not $SkipDocker) { Log "Stack left running: http://localhost:3000  (stop: docker compose -f infra/docker-compose.yml down)"
  Log "Demo logins (DEMO ONLY, password veyra-demo-console-2026): admin@veyra.demo, bank@veyra.demo, hospital@veyra.demo" }
Log "Log: $log"
if ($script:anyFail) { exit 1 } else { exit 0 }
