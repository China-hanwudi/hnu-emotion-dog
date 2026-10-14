$ErrorActionPreference = 'Stop'
$devProject = $PSScriptRoot
$devRoot = Split-Path (Split-Path $devProject -Parent) -Parent
if ([IO.Path]::GetPathRoot($devRoot) -eq 'C:\') { throw '请在 E 盘的项目代码目录运行，避免把运行环境或缓存写入 C 盘' }
$devPython = Join-Path $devRoot '02_运行环境\venv\Scripts\python.exe'
$devOllama = Join-Path $devRoot '02_运行环境\Ollama\ollama.exe'
$devLogs = Join-Path $devRoot '05_日志'
$env:PYTHONUTF8 = '1'
$env:OLLAMA_MODELS = Join-Path $devRoot '03_模型\ollama'
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_CONTEXT_LENGTH = '4096'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NOPRUNE = '1'
$env:TMP = Join-Path $devRoot '04_下载缓存\temp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
if (-not (Test-Path -LiteralPath $devPython)) { throw 'Python 环境不存在，请先运行 setup.ps1' }
try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null }
catch {
    if (-not (Test-Path -LiteralPath $devOllama)) { throw 'Ollama 尚未下载完成' }
    Start-Process -FilePath $devOllama -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $devLogs 'ollama.stdout.log') -RedirectStandardError (Join-Path $devLogs 'ollama.stderr.log')
}
try {
    Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 2 | Out-Null
    Start-Process 'http://127.0.0.1:8765'
    exit 0
} catch { }
Start-Process -FilePath $devPython -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8765') -WorkingDirectory $devProject -WindowStyle Hidden -RedirectStandardOutput (Join-Path $devLogs 'app.stdout.log') -RedirectStandardError (Join-Path $devLogs 'app.stderr.log')
for ($devAttempt=0; $devAttempt -lt 30; $devAttempt++) {
    try { Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 2 | Out-Null; Start-Process 'http://127.0.0.1:8765'; exit 0 } catch { Start-Sleep -Seconds 1 }
}
throw '服务未启动，请检查 05_日志中的 app.stderr.log'



