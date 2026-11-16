# Packages Kairos Studio as a ready-to-use folder: a self-contained KairosStudio.exe
# (no .NET install needed) with FFmpeg, yt-dlp, fonts and sounds beside it.
# Usage:  powershell -ExecutionPolicy Bypass -File desktop\publish.ps1
param([string]$CertificateThumbprint,[string]$SigningMetadata,[string]$SigningDlib,[string]$SignTool,[switch]$RequireSignature)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$dotnet = (Get-Command dotnet -ErrorAction SilentlyContinue).Source
if (-not $dotnet) { $dotnet = Join-Path $env:LOCALAPPDATA 'Microsoft\dotnet\dotnet.exe' }
if (@('ffmpeg.exe','ffprobe.exe','yt-dlp.exe')|Where-Object {-not(Test-Path -LiteralPath (Join-Path $PSScriptRoot ('tools\'+$_)))}) { & (Join-Path $PSScriptRoot 'setup.ps1') }
& (Join-Path $PSScriptRoot 'prepare-distribution.ps1')

# Keep earlier versions and never delete the folder of a running app.
$project = Join-Path $PSScriptRoot 'ClipperStudio\ClipperStudio.csproj'
$version = ([xml](Get-Content -LiteralPath $project -Raw)).Project.PropertyGroup.Version
$out = Join-Path $PSScriptRoot ('dist\KairosStudio-' + $version)
$staging = Join-Path $env:TEMP ('KairosStudio-publish-' + [guid]::NewGuid().ToString('N'))
& $dotnet publish (Join-Path $PSScriptRoot 'ClipperStudio\ClipperStudio.csproj') -c Release -r win-x64 --self-contained true `
    -p:PublishSingleFile=false -p:DebugType=None -p:DebugSymbols=false -o $staging
if ($LASTEXITCODE -ne 0) { throw 'dotnet publish failed.' }
foreach($required in @('KairosStudio.exe','KairosStudio.dll','tools\ffmpeg.exe','tools\ffprobe.exe','tools\yt-dlp.exe','tools\MicrosoftEdgeWebview2Setup.exe','web\locales.tsv')){
    if(-not(Test-Path -LiteralPath (Join-Path $staging $required))){throw "Required distribution file missing: $required"}
}
Copy-Item -LiteralPath (Join-Path $root 'LICENSE'),(Join-Path $root 'NOTICE') -Destination $staging
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'PORTABLE-README.txt') -Destination $staging
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'licenses') -Destination $staging -Recurse
& (Join-Path $PSScriptRoot 'sign.ps1') -Directory $staging -CertificateThumbprint $CertificateThumbprint -SigningMetadata $SigningMetadata -SigningDlib $SigningDlib -SignTool $SignTool -RequireSignature:$RequireSignature
# Never ship private configuration, certificates or user libraries.
$forbidden=Get-ChildItem -LiteralPath $staging -File -Recurse|Where-Object {($_.Name -like '.env*' -and $_.Name -ne '.env.example') -or $_.Name -in @('settings.ai.json','usage.jsonl','ui-language.json') -or ($_.Name -eq 'library.json' -and $_.FullName -ne (Join-Path $staging 'assets\sfx\library.json')) -or $_.Extension -in @('.pfx','.p12','.key','.pem','.db','.sqlite','.sqlite3')}
if($forbidden){throw 'Private files detected in the package; publishing stopped.'}
$hashes=Get-ChildItem -LiteralPath $staging -File -Recurse|Sort-Object FullName|ForEach-Object {((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower()+'  '+$_.FullName.Substring($staging.Length+1).Replace('\','/'))}
$hashes|Set-Content -LiteralPath (Join-Path $staging 'SHA256SUMS.txt') -Encoding ASCII
# Build outputs must never inherit stale files from an earlier build of the same version.
New-Item -ItemType Directory -Path (Split-Path $out -Parent) -Force|Out-Null
if(Test-Path -LiteralPath $out){$out=Join-Path $PSScriptRoot ('dist\KairosStudio-'+$version+'-'+[guid]::NewGuid().ToString('N').Substring(0,8))}
Move-Item -LiteralPath $staging -Destination $out

$ffmpeg = Test-Path (Join-Path $out 'tools\ffmpeg.exe')
$mb = [math]::Round((Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "Done: $out  ($mb MB, FFmpeg included: $ffmpeg)"
Write-Host "Open KairosStudio.exe. For a shortcut: right-click > Send to > Desktop."
return $out
