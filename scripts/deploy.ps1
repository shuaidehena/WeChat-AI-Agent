# WeChat AI Agent — 一键部署（Windows）
#
# 架构：
#   Docker  → LLM Gateway（可选，Linux 容器）
#   宿主机  → 微信 Agent（必须，依赖 Windows UI）
#
# 用法：
#   .\scripts\deploy.ps1              # 启动网关 + Agent
#   .\scripts\deploy.ps1 -GatewayOnly # 只启动 Docker 网关
#   .\scripts\deploy.ps1 -AgentOnly   # 只启动 Agent（直连 DeepSeek）
#   .\scripts\deploy.ps1 -UseGateway  # Agent 通过 localhost:8000 调 LLM

param(
    [switch]$GatewayOnly,
    [switch]$AgentOnly,
    [switch]$UseGateway,
    [int]$Interval = 2
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  WeChat AI Agent 一键部署" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ---------- 检查 .env ----------
if (-not (Test-Path ".env")) {
    Write-Host "⚠️  未找到 .env，从模板复制..." -ForegroundColor Yellow
    Copy-Item "docker\.env.example" ".env"
    Write-Host "请编辑 .env 填入 DEEPSEEK_API_KEY 后重新运行" -ForegroundColor Red
    exit 1
}

# 网关必须使用独立 Bearer Token；缺失时生成并持久化到本地 .env。
$GatewayTokenLine = Get-Content -LiteralPath ".env" | Where-Object {
    $_ -match '^\s*LLM_GATEWAY_TOKEN\s*=\s*(.+)$'
} | Select-Object -First 1
if ($GatewayTokenLine) {
    $env:LLM_GATEWAY_TOKEN = ($GatewayTokenLine -split '=', 2)[1].Trim()
} else {
    $GeneratedGatewayToken = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))
    Add-Content -LiteralPath ".env" -Value "`nLLM_GATEWAY_TOKEN=$GeneratedGatewayToken"
    $env:LLM_GATEWAY_TOKEN = $GeneratedGatewayToken
    Write-Host "🔐 已为本地 LLM Gateway 生成访问令牌" -ForegroundColor Green
}

# ---------- 启动 Docker 网关 ----------
if (-not $AgentOnly) {
    Write-Host "`n[1/3] 检查 Docker..." -ForegroundColor Green
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "❌ 未安装 Docker Desktop，请先安装: https://www.docker.com/products/docker-desktop/" -ForegroundColor Red
        if (-not $GatewayOnly) {
            Write-Host "将跳过网关，Agent 直连 DeepSeek（需在 .env 配置 DEEPSEEK_BASE_URL）" -ForegroundColor Yellow
        } else { exit 1 }
    } else {
        docker info *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ Docker 未运行，请启动 Docker Desktop" -ForegroundColor Red
            exit 1
        }

        Write-Host "`n[2/3] 构建并启动 LLM Gateway 容器..." -ForegroundColor Green
        Push-Location docker
        docker compose up -d --build
        Pop-Location

        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ LLM Gateway: http://localhost:8000/health" -ForegroundColor Green
        } else {
            Write-Host "❌ Docker 启动失败" -ForegroundColor Red
            exit 1
        }
    }
}

if ($GatewayOnly) {
    Write-Host "`n✅ 仅网关模式，已完成。" -ForegroundColor Green
    exit 0
}

# ---------- 启动 Windows Agent ----------
Write-Host "`n[3/3] 启动微信 Agent（Windows 宿主机）..." -ForegroundColor Green

if ($UseGateway) {
    $env:LLM_CHAT_BASE_URL = "http://localhost:8000"
    $env:LLM_MEMORY_BASE_URL = "http://localhost:8000"
    $env:LLM_PROFILE_BASE_URL = "http://localhost:8000"
    Write-Host "   Agent → LLM Gateway → DeepSeek" -ForegroundColor Gray
} else {
    Write-Host "   Agent → DeepSeek（直连）" -ForegroundColor Gray
}

Write-Host "   请确保微信已登录且窗口在屏幕内" -ForegroundColor Yellow
Write-Host "   按 Ctrl+C 停止`n" -ForegroundColor Gray

python main.py --send --interval $Interval
