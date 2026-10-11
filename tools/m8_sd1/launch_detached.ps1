# Launches ONE detached M8-sd1 session: python -B -u -X utf8 rl/m8_sd1_session.py run, with stdout / stderr captured under logs\m8_sd1_run\, records the pid and the UTC
# launch time, and exits. It never relaunches: it refuses when a session log already exists under logs\m8_sd1_run\, when runs\m8_rd_sd1 exists, when no sd1 approval record
# exists, or when rd4's recorded decision (runs\m8_rd_rd4\sessions\rd4\rule.json) is missing. Both parameters are mandatory. Run from the repository root:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\m8_sd1\launch_detached.ps1 -Session sd1 -Repo <repo>
param([Parameter(Mandatory=$true)][ValidateSet('sd1')][string]$Session, [Parameter(Mandatory=$true)][string]$Repo)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath (Join-Path $Repo 'rl\m8_sd1_session.py'))) { throw "$Repo is not the BattleShip checkout (no rl\m8_sd1_session.py)" }
$logs = Join-Path $Repo 'logs\m8_sd1_run'
$out = Join-Path $logs 'session_stdout.txt'
$err = Join-Path $logs 'session_stderr.txt'
if ((Test-Path -LiteralPath $out) -or (Test-Path -LiteralPath $err)) { throw "a session log already exists under $logs (never relaunched)" }
$run = Join-Path $Repo 'runs\m8_rd_sd1'
if (Test-Path -LiteralPath $run) { throw "$run exists (never overwritten, never relaunched)" }
$approval = Join-Path $Repo 'docs\rl_m8_sd1_approval.json'
if (-not (Test-Path -LiteralPath $approval)) { throw "no approval record at $approval (the session is not authorised)" }
$pred = Join-Path $Repo 'runs\m8_rd_rd4\sessions\rd4\rule.json'
if (-not (Test-Path -LiteralPath $pred)) { throw "no rd4 decision record at $pred (the predecessor is not recorded)" }
New-Item -ItemType Directory -Force $logs | Out-Null      # created only once every refusal above has passed (a refusal leaves nothing behind)
$env:PYTHONDONTWRITEBYTECODE = '1'
$p = Start-Process -FilePath 'python' -ArgumentList @('-B', '-u', '-X', 'utf8', 'rl/m8_sd1_session.py', 'run') -WorkingDirectory $Repo -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
$stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
"launched pid=$($p.Id) at $stamp session=$Session" | Out-File -Encoding utf8 (Join-Path $logs 'launch_record.txt')
"launched pid=$($p.Id) at $stamp session=$Session"
