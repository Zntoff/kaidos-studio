param([switch]$Gpu)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Force -Path data,input|Out-Null
$arguments=@('compose','-f','compose.yaml')
if($Gpu){$arguments+=@('-f','compose.gpu.yaml')}
& docker @arguments up -d --build
if($LASTEXITCODE){throw 'Docker startup failed. Check that Docker Desktop is running.'}
Write-Host 'Kairos Studio: http://localhost:8000'
