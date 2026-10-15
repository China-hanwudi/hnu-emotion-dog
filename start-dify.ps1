$ErrorActionPreference = 'Stop'
$devRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if ([IO.Path]::GetPathRoot($devRoot) -eq 'C:\') { throw '请在 E 盘的项目代码目录运行，避免把运行环境或缓存写入 C 盘' }
$devPython = Join-Path $devRoot '02_运行环境\venv\Scripts\python.exe'
$devDify = Join-Path $devRoot '01_项目代码\dify\docker'
$devLogs = Join-Path $devRoot '05_日志'
$devDistro = 'EmotionDogUbuntu'
$devDistroLine = Get-Content -LiteralPath (Join-Path $PSScriptRoot '.env') | Where-Object { $_ -match '^WSL_DISTRO=' } | Select-Object -Last 1
if ($devDistroLine) { $devDistro = ($devDistroLine -split '=',2)[1].Trim() }
$env:PYTHONUTF8 = '1'
$env:TMP = Join-Path $devRoot '04_下载缓存\temp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Path $env:TEMP,$devLogs -Force | Out-Null
if (-not (Test-Path -LiteralPath $devPython)) { throw '请先完成 setup.ps1 中的 Python 环境安装' }
$devDistros = (& wsl --list --quiet | Out-String).Replace([string][char]0,'')
if ($devDistros -notmatch [regex]::Escape($devDistro)) {
    & $devPython (Join-Path $PSScriptRoot 'scripts\setup_wsl_runtime.py')
    if ($LASTEXITCODE -ne 0) { throw '比赛专用 Ubuntu 安装失败，请检查下载日志' }
}
$devBridge = Join-Path $PSScriptRoot 'scripts\wsl_pipe_bridge.py'
$devBridgeRunning = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like ('*' + $devBridge + '*windows*' + $devDistro + '*') }
if (-not $devBridgeRunning) {
    Start-Process -FilePath $devPython -ArgumentList ('-u "' + $devBridge + '" windows ' + $devDistro) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $devLogs 'wsl-pipe.stdout.log') -RedirectStandardError (Join-Path $devLogs 'wsl-pipe.stderr.log')
}
$devLinuxProject = (& wsl -d $devDistro -u root --exec wslpath -a $PSScriptRoot | Out-String).Trim()
$devLinuxDify = (& wsl -d $devDistro -u root --exec wslpath -a $devDify | Out-String).Trim()
& wsl -d $devDistro -u root --exec docker compose version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    & wsl -d $devDistro -u root --exec sh ($devLinuxProject + '/scripts/setup_wsl_docker.sh') '127.0.0.1'
    if ($LASTEXITCODE -ne 0) { throw 'Docker 安装未完成；可重新启动继续安装' }
}
$devDockerReady = $false
for ($devAttempt = 0; $devAttempt -lt 30; $devAttempt++) {
    & wsl -d $devDistro -u root --exec docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $devDockerReady = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $devDockerReady) { throw 'Docker 引擎未启动，请检查 05_日志中的 wsl-pipe 日志' }
& $devPython (Join-Path $PSScriptRoot 'scripts\install_dify_images.py')
if ($LASTEXITCODE -ne 0) { throw 'Dify 镜像尚未完成，可重新启动继续下载' }
& wsl -d $devDistro -u root --cd $devLinuxDify --exec docker compose -f docker-compose.yaml -f ($devLinuxProject + '/deploy/compose.local.yaml') up -d
if ($LASTEXITCODE -ne 0) { throw 'Dify 容器启动失败' }
Start-Process 'http://127.0.0.1:8080'
