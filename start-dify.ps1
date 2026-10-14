$ErrorActionPreference = 'Stop'
$devRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$devPython = Join-Path $devRoot '02_运行环境\venv\Scripts\python.exe'
$devDify = Join-Path $devRoot '01_项目代码\dify\docker'
$devLogs = Join-Path $devRoot '05_日志'
$devBridge = Join-Path $PSScriptRoot 'scripts\wsl_bridge.py'
$env:PYTHONUTF8 = '1'
$route = (& wsl -d Ubuntu-24.04 -u root --exec ip -4 route show default | Out-String)
if ($LASTEXITCODE -ne 0 -or $route -notmatch 'default via ([0-9.]+)') { throw 'Ubuntu WSL 网络未就绪' }
$devGateway = $Matches[1]
$bridgeListener = Get-NetTCPConnection -LocalAddress $devGateway -LocalPort 17897 -State Listen -ErrorAction SilentlyContinue
if (-not $bridgeListener) {
    Start-Process -FilePath $devPython -ArgumentList ('"' + $devBridge + '" windows-server ' + $devGateway) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $devLogs 'wsl-windows.stdout.log') -RedirectStandardError (Join-Path $devLogs 'wsl-windows.stderr.log')
}
$devLinuxProject = (& wsl -d Ubuntu-24.04 -u root --exec wslpath -a $PSScriptRoot | Out-String).Trim()
$devLinuxDify = (& wsl -d Ubuntu-24.04 -u root --exec wslpath -a $devDify | Out-String).Trim()
$devLinuxBridge = $devLinuxProject + '/scripts/wsl_bridge.py'
& wsl -d Ubuntu-24.04 -u root --exec sh -c 'ss -ltn | grep -q 127.0.0.1:17897'
if ($LASTEXITCODE -ne 0) {
    Start-Process -FilePath 'wsl.exe' -ArgumentList ('-d Ubuntu-24.04 -u root --exec python3 -u "' + $devLinuxBridge + '" linux ' + $devGateway) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $devLogs 'wsl-linux.stdout.log') -RedirectStandardError (Join-Path $devLogs 'wsl-linux.stderr.log')
}
$devDockerReady = $false
for ($devAttempt = 0; $devAttempt -lt 60; $devAttempt++) {
    & wsl -d Ubuntu-24.04 -u root --exec docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $devDockerReady = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $devDockerReady) { throw 'Docker 引擎未启动，请检查 05_日志中的 wsl-linux.stderr.log' }
& $devPython (Join-Path $PSScriptRoot 'scripts\install_dify_images.py')
if ($LASTEXITCODE -ne 0) { throw 'Dify 镜像下载未完成，可以重新运行启动脚本继续下载' }
& wsl -d Ubuntu-24.04 -u root --cd $devLinuxDify --exec docker compose -f docker-compose.yaml -f ($devLinuxProject + '/deploy/compose.local.yaml') up -d
if ($LASTEXITCODE -ne 0) { throw 'Dify 容器启动失败' }
Start-Process 'http://127.0.0.1:8080'


