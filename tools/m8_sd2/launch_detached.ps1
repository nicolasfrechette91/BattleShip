# Launches ONE detached M8-sd2 session: python -B -u -X utf8 rl/m8_sd2_session.py run, with stdout / stderr captured under logs\m8_sd2_run\, records the pid and the UTC
# launch time, and exits. It never relaunches: it refuses when a session log already exists under logs\m8_sd2_run\, when runs\m8_rd_sd2 exists, when no sd2 approval record
# exists, when sd1's recorded decision (runs\m8_rd_sd1\sessions\sd1\rule.json) is missing, or when the repository's HEAD differs from the approval's git_head (the S2 rule:
# no commit between the approval and the launch). Both parameters are mandatory. A refusal leaves nothing behind. Run from the repository root (Git Bash form):
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools/m8_sd2/launch_detached.ps1 -Session sd2 -Repo <repo>
param([Parameter(Mandatory=$true)][ValidateSet('sd2')][string]$Session, [Parameter(Mandatory=$true)][string]$Repo)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath (Join-Path $Repo 'rl\m8_sd2_session.py'))) { throw "$Repo is not the BattleShip checkout (no rl\m8_sd2_session.py)" }
$logs = Join-Path $Repo 'logs\m8_sd2_run'
$out = Join-Path $logs 'session_stdout.txt'
$err = Join-Path $logs 'session_stderr.txt'
if ((Test-Path -LiteralPath $out) -or (Test-Path -LiteralPath $err)) { throw "a session log already exists under $logs (never relaunched)" }
$run = Join-Path $Repo 'runs\m8_rd_sd2'
if (Test-Path -LiteralPath $run) { throw "$run exists (never overwritten, never relaunched)" }
$approval = Join-Path $Repo 'docs\rl_m8_sd2_approval.json'
if (-not (Test-Path -LiteralPath $approval)) { throw "no approval record at $approval (the session is not authorised)" }
$pred = Join-Path $Repo 'runs\m8_rd_sd1\sessions\sd1\rule.json'
if (-not (Test-Path -LiteralPath $pred)) { throw "no sd1 decision record at $pred (the predecessor is not recorded)" }
$approvedHead = (Get-Content -LiteralPath $approval -Raw -Encoding UTF8 | ConvertFrom-Json).git_head
$head = (& git -C $Repo rev-parse HEAD 2>$null | Out-String).Trim()
if (-not $approvedHead) { throw "the approval record carries no git_head" }
if ($head -ne $approvedHead) { throw "HEAD $head differs from the approval's git_head $approvedHead (no commit between the approval and the launch: the approval is void)" }
New-Item -ItemType Directory -Force $logs | Out-Null      # created only once every refusal above has passed (a refusal leaves nothing behind)
$env:PYTHONDONTWRITEBYTECODE = '1'
$p = Start-Process -FilePath 'python' -ArgumentList @('-B', '-u', '-X', 'utf8', 'rl/m8_sd2_session.py', 'run') -WorkingDirectory $Repo -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
$stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
"launched pid=$($p.Id) at $stamp session=$Session head=$head" | Out-File -Encoding utf8 (Join-Path $logs 'launch_record.txt')
"launched pid=$($p.Id) at $stamp session=$Session head=$head"
