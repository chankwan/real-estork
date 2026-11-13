# RealEstork — kiem tra bot dang chay truoc khi start tay.
# Goi tu bot-start.bat va bot-start-headless.bat:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\bot-guard.ps1 -Mode <visible|headless>
# Exit code: 0 = duoc phep start (khong co bot, hoac da tat bot cu theo y user)
#            1 = user chon khong chay de -> script start phai dung lai.
#
# Vi sao khong chi dua vao lock file: 13/11/2026 lock bi doc sai (bot cu dang
# chay ma bi coi la da chet) -> 2 bot chay song song 14 tieng. Day la lop chan
# thu hai: tim thang process theo dong lenh, khong phu thuoc lock.
param([string]$Mode = "headless")

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $PSScriptRoot

$all = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'cli\.main\s+start'
})
# Moi bot chay 2 tang (cha + con cung dong lenh). Chi lay tang tren cung.
$ids = $all | ForEach-Object { $_.ProcessId }
$bots = @($all | Where-Object { $ids -notcontains $_.ParentProcessId })

if ($bots.Count -eq 0) { exit 0 }

Write-Host ""
Write-Host "[!] Dang co $($bots.Count) bot chay:" -ForegroundColor Yellow
foreach ($b in $bots) {
    $kieu = if ($b.Name -ieq 'pythonw.exe') { 'headless (chay ngam)' } else { 'co cua so' }
    $nguon = if ($b.CommandLine -match '--source\s+(\S+)') { $Matches[1] } else { '?' }
    $tu = $b.CreationDate.ToString('dd/MM HH:mm')
    Write-Host ("    PID {0}  {1}  nguon={2}  chay tu {3}" -f $b.ProcessId, $kieu, $nguon, $tu)
}
Write-Host ""
$kieuMoi = if ($Mode -eq 'visible') { 'bot CO CUA SO' } else { 'bot headless moi' }
Write-Host "Chay de len bang ${kieuMoi}? Bot cu se bi tat."
$ans = Read-Host "Go Y de tat bot cu va chay moi, N de giu nguyen [Y/N]"
if ($ans -notmatch '^[Yy]') {
    Write-Host "[OK] Giu nguyen bot dang chay, khong start them."
    exit 1
}

foreach ($b in $bots) {
    & taskkill /PID $b.ProcessId /F /T *> $null
}
Start-Sleep -Seconds 2
$con = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'cli\.main\s+start'
})
if ($con.Count -gt 0) {
    Write-Host "[X] Van con $($con.Count) process bot, khong tat duoc. Dung lai." -ForegroundColor Red
    exit 1
}
Remove-Item (Join-Path $here '.orchestrator.lock') -ErrorAction SilentlyContinue
Write-Host "[OK] Da tat bot cu."
exit 0
