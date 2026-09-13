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

# 健康检查（只认容器链路，不认宿主机 8000：本机可能有开发联调服务占着 8000）
# 1) 后端容器运行中 2) 前端首页 200 3) Nginx 反代 /api 200 4) 登录拿 token（种子+全链路）
$backendOk = $false
$frontOk = $false
for ($i = 0; $i -lt 30; $i++) {
  try {
    $st = docker compose -f $compose ps backend --format json 2>$null | ConvertFrom-Json
    if ($st.State -eq 'running') { $backendOk = $true }
  } catch { Start-Sleep -Milliseconds 500 }
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/' -TimeoutSec 3 -UseBasicParsing
    if ($r.StatusCode -eq 200) { $frontOk = $true }
  } catch { Start-Sleep -Milliseconds 500 }
  if ($backendOk -and $frontOk) { break }
  Start-Sleep -Seconds 2
}
Check '后端容器运行中' $backendOk '(reai-backend-1)'
Check '前端首页' $frontOk '(8080)'
if ($frontOk) {
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/api/v1/governance/status' -TimeoutSec 5 -UseBasicParsing
    Check 'Nginx 反代 /api' ($r.StatusCode -eq 200) ''
  } catch { Check 'Nginx 反代 /api' $false $_.Exception.Message }
  try {
    $body = @{ username = 'admin'; password = 'admin123' } | ConvertTo-Json
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/api/v1/auth/login' -Method POST -Body $body -ContentType 'application/json' -TimeoutSec 10 -UseBasicParsing
    $loginOk = ($r.StatusCode -eq 200) -and ($r.Content | ConvertFrom-Json).code -eq 0
    Check '登录拿 token' $loginOk '(admin/admin123)'
  } catch { Check '登录拿 token' $false $_.Exception.Message }
}
Write-Output "RESULT: $passed passed, $failed failed"
if ($failed -gt 0) { exit 1 }
Write-Output '前端地址：http://127.0.0.1:8080（默认账号 admin / admin123，首次启动自动灌种子）'
exit 0
