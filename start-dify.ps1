$ErrorActionPreference = 'Stop'
$devRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$devDocker = Join-Path $devRoot '02_运行环境\DockerDesktop\resources\bin\docker.exe'
$devDify = Join-Path $devRoot '01_项目代码\dify\docker'
$devProfile = Join-Path $devRoot '02_运行环境\dd'
$env:LOCALAPPDATA = Join-Path $devProfile 'local'
$env:APPDATA = Join-Path $devProfile 'roaming'
$env:PATH = (Join-Path $devRoot '02_运行环境\DockerDesktop\resources\bin') + ';' + $env:PATH
$env:DOCKER_CONFIG = Join-Path $devRoot '02_运行环境\docker-cli'
New-Item -ItemType Directory -Path $env:DOCKER_CONFIG -Force | Out-Null
if (-not (Get-Process -Name 'com.docker.backend' -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath (Join-Path $devRoot '02_运行环境\DockerDesktop\Docker Desktop.exe') -WindowStyle Hidden
}
Set-Location -LiteralPath $devDify
& $devDocker --config $env:DOCKER_CONFIG compose -f docker-compose.yaml -f (Join-Path $PSScriptRoot 'deploy\compose.local.yaml') up -d
if ($LASTEXITCODE -ne 0) { throw 'Dify 容器启动失败' }
Start-Process 'http://127.0.0.1:8080'

