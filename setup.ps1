$ErrorActionPreference = 'Stop'
$devRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$devPythonRoot = Join-Path $devRoot '02_运行环境\python'
$devVenv = Join-Path $devRoot '02_运行环境\venv'
$devCache = Join-Path $devRoot '04_下载缓存\uv'
uv python install 3.11 --install-dir $devPythonRoot --no-bin --no-registry --cache-dir $devCache --system-certs
if ($LASTEXITCODE -ne 0) { throw 'Python 下载失败' }
$devPython = (Get-ChildItem -LiteralPath $devPythonRoot -Recurse -Filter python.exe | Select-Object -First 1).FullName
uv venv $devVenv --python $devPython --cache-dir $devCache --allow-existing
uv pip install --python (Join-Path $devVenv 'Scripts\python.exe') -r (Join-Path $PSScriptRoot 'requirements.lock.txt') --cache-dir $devCache --link-mode copy --system-certs
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env'))) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.env.example') -Destination (Join-Path $PSScriptRoot '.env') }
& (Join-Path $devVenv 'Scripts\python.exe') (Join-Path $PSScriptRoot 'download_assets.py') speech
if ($LASTEXITCODE -ne 0) { throw '语音模型下载未完成' }
& (Join-Path $devVenv 'Scripts\python.exe') (Join-Path $PSScriptRoot 'download_assets.py') ollama
if ($LASTEXITCODE -ne 0) { throw 'Ollama 下载未完成' }
& (Join-Path $devVenv 'Scripts\python.exe') (Join-Path $PSScriptRoot 'download_assets.py') aria2
if ($LASTEXITCODE -ne 0) { throw '分段下载工具安装未完成' }
& (Join-Path $devVenv 'Scripts\python.exe') (Join-Path $PSScriptRoot 'download_assets.py') model
if ($LASTEXITCODE -ne 0) { throw '本地多模态模型下载未完成' }



