# Independent re-hash of a runs/ increment (no Python, no repository tool): every file under -Source is hashed with Get-FileHash and compared
# with the same relative path under <Dest>\runs. Reports the number of source files, backup files and mismatches. Reads only.
#   powershell -File independent_increment_check.ps1 -Source C:\...\BattleShip\runs\m8_rd -Dest D:\BattleShip_runs_backup\2026-10-02_incr_m8_rd1
param([Parameter(Mandatory=$true)][string]$Source, [Parameter(Mandatory=$true)][string]$Dest)
$ErrorActionPreference = 'Stop'
$src = (Resolve-Path -LiteralPath $Source).Path.TrimEnd('\')
$bak = Join-Path (Resolve-Path -LiteralPath $Dest).Path 'runs'
$srcFiles = Get-ChildItem -LiteralPath $src -Recurse -File -Force
$bakFiles = Get-ChildItem -LiteralPath $bak -Recurse -File -Force
$bad = 0; $n = 0; $missing = 0
foreach ($f in $srcFiles) {
  $rel = $f.FullName.Substring($src.Length + 1)
  $b = Join-Path $bak $rel
  $n++
  if (-not (Test-Path -LiteralPath $b)) { $missing++; "MISSING in backup: $rel"; continue }
  $hs = (Get-FileHash -Algorithm SHA256 -LiteralPath $f.FullName).Hash
  $hb = (Get-FileHash -Algorithm SHA256 -LiteralPath $b).Hash
  if ($hs -ne $hb) { $bad++; "MISMATCH: $rel" }
}
$extra = ($bakFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $src $_.FullName.Substring($bak.Length + 1))) } | Measure-Object).Count
"checked=$n source_files=$($srcFiles.Count) backup_files=$($bakFiles.Count) missing=$missing extra_in_backup=$extra bad=$bad result=$(if ($bad -eq 0 -and $missing -eq 0 -and $extra -eq 0) { 'PASS' } else { 'FAIL' })"
