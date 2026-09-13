# 一键部署（对齐部署工程化.md §五/§十三）：拉 GHCR 镜像 → compose 起前后端 → 健康检查
# 用法：powershell -File deploy/deploy.ps1 [-Tag v0.1.0] [-Down]
# 输出 PASS/FAIL 明细 + RESULT，退出码反映成败（对齐 smoke 脚本风格）
param(
  [string]$Tag = 'latest',
  [switch]$Down
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$compose = Join-Path $root 'docker-compose.yml'
$passed = 0
$failed = 0

function Check($name, $ok, $detail) {
  if ($ok) {
    $script:passed += 1
    Write-Output "PASS: $name $detail"
  } else {
    $script:failed += 1
    Write-Output "FAIL: $name $detail"
  }
}

if ($Down) {
  docker compose -f $compose down
  exit $LASTEXITCODE
}

$env:REAI_TAG = $Tag
docker compose -f $compose pull
if ($LASTEXITCODE -ne 0) { Write-Output 'FAIL: 镜像拉取失败'; exit 1 }
docker compose -f $compose up -d
if ($LASTEXITCODE -ne 0) { Write-Output 'FAIL: 容器启动失败'; exit 1 }

# 健康检查：后端 /health + 前端 200，最多等 60 秒
$backendOk = $false
$frontOk = $false
for ($i = 0; $i -lt 30; $i++) {
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 3 -UseBasicParsing
    if ($r.StatusCode -eq 200) { $backendOk = $true }
  } catch { Start-Sleep -Milliseconds 500 }
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/' -TimeoutSec 3 -UseBasicParsing
    if ($r.StatusCode -eq 200) { $frontOk = $true }
  } catch { Start-Sleep -Milliseconds 500 }
  if ($backendOk -and $frontOk) { break }
  Start-Sleep -Seconds 2
}
Check '后端 /health' $backendOk '(8000)'
Check '前端首页' $frontOk '(8080)'
if ($frontOk) {
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/api/v1/governance/status' -TimeoutSec 5 -UseBasicParsing
    Check 'Nginx 反代 /api' ($r.StatusCode -eq 200) ''
  } catch { Check 'Nginx 反代 /api' $false $_.Exception.Message }
}
Write-Output "RESULT: $passed passed, $failed failed"
if ($failed -gt 0) { exit 1 }
Write-Output '前端地址：http://127.0.0.1:8080（默认账号 admin / admin123，首次启动自动灌种子）'
exit 0
