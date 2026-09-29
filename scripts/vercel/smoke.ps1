# VEYRA deployed smoke test (public demo deployment). Run by the account owner:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\vercel\smoke.ps1 [-Base https://<site>]
#
# Walks the full journey through the PUBLIC website's same-origin /api proxy:
# login -> dashboard -> camp -> registration -> attendance -> donation -> bag -> QR ->
# compatibility -> hospital request -> confirmed dispatch -> shipment -> cold chain ->
# arrival -> receipt -> trace, plus RBAC/scope/CSRF/privacy spot checks.
# The demo staff password is typed at the prompt (never stored). The donor it registers is
# fictional ("Smoke Test Donor", example.in address). Log: .deploy-logs\smoke-<time>.log

param([string]$Base = "https://veyra-web-sigma.vercel.app")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$logDir = Join-Path $root ".deploy-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
function Log([string]$Line) { Write-Host $Line; Add-Content -Path $log -Value $Line -Encoding UTF8 }

$api = "$Base/api/v1"
$script:passed = 0
$script:failed = 0
function Check([string]$Name, [scriptblock]$Body) {
  try { & $Body; $script:passed++; Log "PASS  $Name" }
  catch { $script:failed++; Log "FAIL  $Name :: $($_.Exception.Message)" }
}

function Invoke-Api {
  param([string]$Method, [string]$Uri, $Body = $null, $Session, [hashtable]$Headers = @{})
  $a = @{ Uri = $Uri; Method = $Method; WebSession = $Session; Headers = $Headers; UseBasicParsing = $true }
  if ($null -ne $Body) { $a.Body = ($Body | ConvertTo-Json -Compress -Depth 6); $a.ContentType = "application/json" }
  try {
    $r = Invoke-WebRequest @a
    if ($r.Content) { return ($r.Content | ConvertFrom-Json) } else { return $null }
  } catch {
    $resp = $_.Exception.Response
    if ($resp) {
      $detail = ""
      try { $detail = (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd() } catch { }
      throw "$Method $Uri -> $([int]$resp.StatusCode): $detail"
    }
    throw
  }
}
function Status-Of([scriptblock]$Call) {
  try { & $Call | Out-Null; return 200 } catch { if ("$_" -match "-> (\d{3})") { return [int]$Matches[1] } else { throw } }
}
function Csrf($s) { ($s.Cookies.GetCookies($Base) | Where-Object Name -eq "veyra_csrf").Value }
function H($s) { @{ "X-CSRF-Token" = (Csrf $s) } }

Log "VEYRA deployed smoke test - $(Get-Date -Format o) - $Base"
$secure = Read-Host "Demo staff password for bank@veyra.demo / hospital@veyra.demo / admin@veyra.demo" -AsSecureString
$pw = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

$bank = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$hosp = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$adm = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$anon = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$d = New-Object Microsoft.PowerShell.Commands.WebRequestSession

Check "public pages (landing, sign-in, register, disclosures, compatibility, camps, scan)" {
  foreach ($p in @("/", "/sign-in", "/register", "/disclosures", "/compatibility", "/camps", "/scan")) {
    $r = Invoke-WebRequest -Uri "$Base$p" -UseBasicParsing
    if ($r.StatusCode -ne 200) { throw "$p -> $($r.StatusCode)" }
    if ($r.Content -match "localhost:8000") { throw "$p references localhost" }
  }
}
Check "security headers + API meta via proxy" {
  $r = Invoke-WebRequest -Uri "$Base/" -UseBasicParsing
  foreach ($h in @("Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options", "Strict-Transport-Security")) {
    if (-not $r.Headers[$h]) { throw "missing $h" }
  }
  if ((Invoke-Api Get "$api/meta" $null $anon).name -ne "VEYRA") { throw "meta" }
}
Check "anonymous is refused (401) and API docs are hidden" {
  foreach ($p in @("/auth/me", "/camps/public", "/compatibility/matrix", "/bags/scan?payload=veyra:bag:VYR-0000-0000")) {
    if ((Status-Of { Invoke-Api Get "$api$p" $null $anon }) -ne 401) { throw "$p not 401" }
  }
  if ((Status-Of { Invoke-Api Get "https://veyra-api-five.vercel.app/docs" $null $anon }) -ne 404) { throw "docs exposed" }
}
Check "staff sign in (bank, hospital, admin) + dashboards" {
  Invoke-Api Post "$api/auth/login" @{ email = "bank@veyra.demo"; password = $pw } $bank | Out-Null
  Invoke-Api Post "$api/auth/login" @{ email = "hospital@veyra.demo"; password = $pw } $hosp | Out-Null
  Invoke-Api Post "$api/auth/login" @{ email = "admin@veyra.demo"; password = $pw } $adm | Out-Null
  Invoke-Api Get "$api/dashboard/facility" $null $bank | Out-Null
  Invoke-Api Get "$api/dashboard/facility" $null $hosp | Out-Null
  Invoke-Api Get "$api/dashboard/admin" $null $adm | Out-Null
}
$pw = $null
$bf = Invoke-Api Get "$api/facilities/me" $null $bank
$tag = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$mobile = "9" + ([UInt64]("0x" + [Guid]::NewGuid().ToString("N").Substring(0, 15)) % 1000000000).ToString("000000000")
$script:ctx = @{}

Check "camp created, published, registration opened (invalid transition refused)" {
  $start = (Get-Date).ToUniversalTime().AddDays(1)
  $c = Invoke-Api Post "$api/camps" @{ title = "Smoke Test Camp $tag"; venue = "Demo Hall"; city = "Kolkata"; state = "West Bengal";
    starts_at = $start.ToString("yyyy-MM-ddTHH:mm:ssZ"); ends_at = $start.AddHours(6).ToString("yyyy-MM-ddTHH:mm:ssZ"); capacity = 20;
    contact_name = "Camp Desk (demo)"; description = "Fictional smoke-test camp." } $bank (H $bank)
  if ((Status-Of { Invoke-Api Post "$api/camps/$($c.id)/actions/start" $null $bank (H $bank) }) -ne 409) { throw "invalid transition allowed" }
  Invoke-Api Post "$api/camps/$($c.id)/actions/publish" $null $bank (H $bank) | Out-Null
  Invoke-Api Post "$api/camps/$($c.id)/actions/open-registration" $null $bank (H $bank) | Out-Null
  $script:ctx.camp = $c
}
Check "fictional donor registers (demo verification) and joins the camp; duplicate refused" {
  $reg = Invoke-Api Post "$api/auth/register" @{ full_name = "Smoke Test Donor"; email = "smoke-$tag@example.in"; mobile = $mobile;
    blood_group = "A+"; address = "1 Demo Street"; city = "Kolkata"; state = "West Bengal"; pin_code = "700001";
    password = "smoke-test-passphrase-$tag" } $d
  Invoke-Api Post "$api/auth/verify" @{ challenge_id = $reg.verification.challenge_id; code = $mobile.Substring(6) } $d | Out-Null
  $found = @((Invoke-Api Get "$api/camps/public?q=$tag" $null $d).camps)
  if ($found.Count -ne 1) { throw "camp not visible to donor" }
  $my = Invoke-Api Post "$api/camps/$($script:ctx.camp.id)/register" $null $d (H $d)
  if ((Status-Of { Invoke-Api Post "$api/camps/$($script:ctx.camp.id)/register" $null $d (H $d) }) -ne 409) { throw "duplicate registration" }
  if ((Status-Of { Invoke-Api Get "$api/camps/$($script:ctx.camp.id)" $null $d }) -ne 403) { throw "donor saw camp management" }
  $script:ctx.reg = $my
}
Check "attendance confirmed; donation recorded at the desk; bag created with public QR" {
  $cid = $script:ctx.camp.id
  Invoke-Api Post "$api/camps/$cid/actions/start" $null $bank (H $bank) | Out-Null
  Invoke-Api Post "$api/camps/$cid/registrations/$($script:ctx.reg.id)/attend" $null $bank (H $bank) | Out-Null
  $donor = Invoke-Api Post "$api/donors/lookup" @{ mobile = $mobile } $bank (H $bank)
  $don = Invoke-Api Post "$api/donations" @{ donor_id = $donor.donor_id; blood_group = "A+"; volume_ml = 450; components = @("PRBC");
    camp_registration_id = $script:ctx.reg.id } $bank (H $bank)
  $bag = @($don.bags)[0]
  if ($bag.qr_payload -ne "veyra:bag:$($bag.public_id)") { throw "QR payload" }
  $st = (Invoke-Api Get "$api/camps/$cid" $null $bank).stats
  if ($st.donations_recorded -ne 1 -or $st.bags_collected -ne 1) { throw "camp stats" }
  $script:ctx.bag = $bag.public_id
}
Check "QR: label matrix, scoped scan, no identity, not a credential" {
  $bag = $script:ctx.bag
  $qr = Invoke-Api Get "$api/bags/$bag/qr" $null $bank
  if ($qr.size -ne 25 -or $qr.payload -ne "veyra:bag:$bag") { throw "QR matrix" }
  $scan = Invoke-Api Get "$api/bags/scan?payload=veyra:bag:$bag" $null $bank
  if (-not $scan.chain.valid) { throw "chain" }
  if ((Invoke-WebRequest -Uri "$api/bags/scan?payload=$bag" -WebSession $bank -UseBasicParsing).Content -match "Smoke Test Donor|example\.in") { throw "identity leak" }
  if ((Status-Of { Invoke-Api Get "$api/bags/scan?payload=veyra:bag:$bag" $null $anon }) -ne 401) { throw "anonymous scan" }
  if ((Status-Of { Invoke-Api Get "$api/bags/scan?payload=veyra:bag:$bag" $null $d }) -ne 403) { throw "donor scan" }
  if ((Status-Of { Invoke-Api Get "$api/bags/scan?payload=veyra:bag:$bag" $null $hosp }) -ne 404) { throw "hospital saw an unrelated bag" }
  if ((Status-Of { Invoke-Api Get "$api/bags/scan?payload=not-a-bag" $null $bank }) -ne 422) { throw "malformed QR" }
}
Check "compatibility reference (A+ -> AB+ PRBC compatible; AB+ -> O- not)" {
  $ok = Invoke-Api Get "$api/compatibility/check?donor_group=A%2B&recipient_group=AB%2B&component=PRBC" $null $hosp
  $no = Invoke-Api Get "$api/compatibility/check?donor_group=AB%2B&recipient_group=O-&component=PRBC" $null $hosp
  if (-not $ok.compatible -or $no.compatible -or -not $ok.requires_clinical_confirmation) { throw "verdicts" }
}
Check "CSRF enforced on a cookie-authenticated mutation" {
  if ((Status-Of { Invoke-Api Post "$api/camps/$($script:ctx.camp.id)/actions/complete" $null $bank @{} }) -ne 403) { throw "no CSRF" }
}
Check "hospital emergency request -> confirmed dispatch -> shipment" {
  $req = Invoke-Api Post "$api/requests" @{ provider = "internal"; target_ref = $bf.id; blood_group = "A+"; component = "PRBC"; units = 1;
    urgency = "emergency"; needed_by = (Get-Date).ToUniversalTime().AddHours(2).ToString("yyyy-MM-ddTHH:mm:ssZ") } $hosp (H $hosp)
  $ful = Invoke-Api Post "$api/requests/$($req.id)/fulfil" @{ bag_public_ids = @($script:ctx.bag) } $bank (H $bank)
  if ($ful.status -ne "dispatched") { throw "dispatch" }
  $s = (Invoke-Api Get "$api/bags/scan?payload=$($script:ctx.bag)" $null $hosp).shipment
  if ($s.status -ne "pickup_pending") { throw "shipment" }
  $script:ctx.req = $req; $script:ctx.sid = $s.id
}
Check "simulated transit + cold-chain warning + delay/resume + arrival (no auto receipt)" {
  $sid = $script:ctx.sid; $bag = $script:ctx.bag
  Invoke-Api Post "$api/simulator/bags/$bag/attach" $null $bank (H $bank) | Out-Null
  Invoke-Api Post "$api/simulator/bags/$bag/tick" @{ count = 1 } $bank (H $bank) | Out-Null
  Invoke-Api Post "$api/simulator/shipments/$sid/advance" $null $bank (H $bank) | Out-Null
  Invoke-Api Post "$api/simulator/shipments/$sid/advance" $null $bank (H $bank) | Out-Null
  Invoke-Api Post "$api/simulator/bags/$bag/excursion" $null $bank (H $bank) | Out-Null
  Invoke-Api Post "$api/simulator/bags/$bag/tick" @{ count = 1 } $bank (H $bank) | Out-Null
  $t = Invoke-Api Get "$api/shipments/$sid/telemetry" $null $hosp
  if (@("warning", "critical") -notcontains $t.cold_chain_alert) { throw "cold chain alert" }
  Invoke-Api Post "$api/simulator/bags/$bag/recover" $null $bank (H $bank) | Out-Null
  Invoke-Api Post "$api/simulator/shipments/$sid/delay" @{ minutes = 18 } $bank (H $bank) | Out-Null
  Invoke-Api Post "$api/simulator/shipments/$sid/resume" $null $bank (H $bank) | Out-Null
  Invoke-Api Post "$api/simulator/shipments/$sid/advance" $null $bank (H $bank) | Out-Null
  Invoke-Api Post "$api/simulator/shipments/$sid/advance" $null $bank (H $bank) | Out-Null
  $a = Invoke-Api Post "$api/simulator/shipments/$sid/arrive" $null $bank (H $bank)
  if ($a.shipment.status -ne "arrived") { throw "arrive" }
  if ((Invoke-Api Get "$api/requests/$($script:ctx.req.id)" $null $hosp).status -ne "dispatched") { throw "auto receipt" }
}
Check "hospital receipt -> final trace valid (shipment received, request fulfilled)" {
  $r = Invoke-Api Post "$api/shipments/$($script:ctx.sid)/receive" $null $hosp (H $hosp)
  if ($r.status -ne "received" -or $r.request_status -ne "fulfilled") { throw "receipt" }
  $trace = Invoke-Api Get "$api/bags/$($script:ctx.bag)" $null $hosp
  $types = @($trace.events | ForEach-Object { $_.event_type })
  foreach ($t in @("COLLECTED", "DEVICE_ATTACHED", "DISPATCHED", "SHIPMENT_CREATED", "TEMP_EXCURSION", "SHIPMENT_DELAYED", "SHIPMENT_ARRIVED", "RECEIVED", "SHIPMENT_RECEIVED")) {
    if ($types -notcontains $t) { throw "trace missing $t" }
  }
  if (-not $trace.chain.valid) { throw "chain invalid" }
  Invoke-Api Post "$api/camps/$($script:ctx.camp.id)/actions/complete" $null $bank (H $bank) | Out-Null
}
Check "live events (SSE replay) reach the bank, operations/forecast/network views load" {
  $sse = (Invoke-WebRequest -Uri "$api/stream?once=true" -Headers @{ "Last-Event-ID" = "0" } -WebSession $bank -UseBasicParsing).Content
  if ($sse -notlike "*event: *") { throw "no SSE events" }
  Invoke-Api Get "$api/operations/requests" $null $bank | Out-Null
  Invoke-Api Get "$api/forecast/summary" $null $bank | Out-Null
  Invoke-Api Get "$api/network/graph" $null $adm | Out-Null
  Invoke-Api Get "$api/shipments" $null $adm | Out-Null
}

Log ""
Log ("SMOKE RESULT: {0}  ({1} passed, {2} failed)" -f ($(if ($script:failed -eq 0) { "PASS" } else { "FAIL" })), $script:passed, $script:failed)
Log "Log: $log"
if ($script:failed -ne 0) { exit 1 } else { exit 0 }
