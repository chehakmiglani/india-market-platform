# Scheduled entry point (Windows Task Scheduler, weekdays 19:30 IST).
#   Exit codes from src.pipeline.daily: 0 ok / skipped (holiday), 1 failed, 2 data-quality FAIL,
#   3 bhavcopy not published yet.
# - Catches up weekdays missed while the PC was off (data only, no digest for old days).
# - Waits and retries only when NSE hasn't published yet; a real failure is reported at once.
param([int]$Retries = 3, [int]$WaitMinutes = 30, [int]$CatchUpDays = 5)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
# Python that has the project's requirements; set PIPELINE_PYTHON to override the one on PATH
$pyExe = if ($env:PIPELINE_PYTHON) { $env:PIPELINE_PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
$py = Split-Path -Parent $pyExe
$env:PATH = "$py;$py\Scripts;$env:PATH"   # dbt.exe lives in Scripts
$env:PYTHONUTF8 = "1"
$today = Get-Date -Format "yyyy-MM-dd"
New-Item -ItemType Directory -Force logs | Out-Null
$log = "logs\daily_$today.log"

function Write-Log($text) { $text | Out-File -Append -Encoding utf8 $log }

function Invoke-Pipeline([string[]]$PipelineArgs) {
    # Pipe through Out-File: '*>>' would append UTF-16 to a UTF-8 file in Windows PowerShell
    & $pyExe -m src.pipeline.daily @PipelineArgs 2>&1 | ForEach-Object { "$_" } |
        Out-File -Append -Encoding utf8 $log
    return $LASTEXITCODE
}

function Send-Failure([string]$why) {
    $tail = (Get-Content $log -Tail 8) -join "`n"
    & $pyExe -c @"
import os, sys
from dotenv import load_dotenv
load_dotenv('.env')
from src.alerts.notify import send_telegram
t, c = os.getenv('TELEGRAM_BOT_TOKEN'), os.getenv('TELEGRAM_CHAT_ID')
if t and c:
    send_telegram('WARNING: NSE pipeline did not finish for ' + sys.argv[1] + '\n' + sys.argv[2]
                  + '\nLog: ' + sys.argv[3] + '\n\n' + sys.argv[4][-1500:], t, c)
"@ $today $why $log.Replace('\', '/') $tail 2>&1 | ForEach-Object { "$_" } | Out-File -Append -Encoding utf8 $log
}

# 1. Catch up: recent weekdays with no bhavcopy on disk (holidays skip themselves in the calendar step)
$bronze = Join-Path $(if ($env:LAKE_ROOT) { $env:LAKE_ROOT } else { "data\lake" }) "bronze\nse_bhavcopy"
for ($back = $CatchUpDays; $back -ge 1; $back--) {
    $d = (Get-Date).AddDays(-$back)
    if ($d.DayOfWeek -in 'Saturday', 'Sunday') { continue }
    $ds = $d.ToString("yyyy-MM-dd")
    if (Test-Path (Join-Path $bronze "dt=$ds")) { continue }
    Write-Log "=== catch-up $ds at $(Get-Date -Format s) ==="
    $code = Invoke-Pipeline @("--date", $ds, "--only", "calendar", "extract", "silver")
    if ($code -ne 0) { Write-Log "catch-up $ds exited $code (continuing)" }
}

# 2. Today
for ($try = 0; $try -le $Retries; $try++) {
    Write-Log "=== attempt $($try + 1) at $(Get-Date -Format s) ==="
    $code = Invoke-Pipeline @("--date", $today)
    if ($code -eq 0 -or $code -eq 2) { exit $code }   # done (2 = DQ issues, already in the digest)
    if ($code -ne 3) { Send-Failure "A step failed (exit $code)."; exit $code }
    if ($try -lt $Retries) { Start-Sleep -Seconds ($WaitMinutes * 60) }
}
Send-Failure "NSE had not published the bhavcopy after $($Retries + 1) attempts."
exit 3
