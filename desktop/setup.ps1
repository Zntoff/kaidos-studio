# Downloads the tools the Kairos Studio desktop app uses: FFmpeg (with NVENC and libass) and yt-dlp.
# Usage:  powershell -ExecutionPolicy Bypass -File desktop\setup.ps1
# They go to desktop\tools\ (never committed). Run it again to update them.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$tools = Join-Path $PSScriptRoot 'tools'
New-Item -ItemType Directory -Force $tools | Out-Null

if (-not (Test-Path (Join-Path $tools 'ffmpeg.exe')) -or -not(Test-Path (Join-Path $tools 'ffprobe.exe'))) {
    Write-Host 'Downloading FFmpeg (GPL build by BtbN, with NVENC and libass)...'
    $scratchRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
    $token=[guid]::NewGuid().ToString('N')
    $zip = Join-Path $scratchRoot ('ffmpeg-clipper-'+$token+'.zip')
    $tmp = [IO.Path]::GetFullPath((Join-Path $scratchRoot ('ffmpeg-clipper-'+$token)))
    if(-not $tmp.StartsWith($scratchRoot,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe temporary extraction path.'}
    Invoke-WebRequest 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' -OutFile $zip
    Expand-Archive $zip -DestinationPath $tmp
    Get-ChildItem $tmp -Recurse -Include ffmpeg.exe, ffprobe.exe | Copy-Item -Destination $tools
    Remove-Item -LiteralPath $tmp -Recurse -Force
    Remove-Item -LiteralPath $zip -Force
}
if (-not (Test-Path (Join-Path $tools 'yt-dlp.exe'))) {
    Write-Host 'Downloading yt-dlp...'
    Invoke-WebRequest 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe' -OutFile (Join-Path $tools 'yt-dlp.exe')
}
& (Join-Path $tools 'ffmpeg.exe') -hide_banner -version | Select-Object -First 1
$enc = & (Join-Path $tools 'ffmpeg.exe') -hide_banner -encoders 2>$null | Select-String 'nvenc'
Write-Host ("Available NVIDIA encoders: " + (($enc | ForEach-Object { ($_ -split '\s+')[2] }) -join ', '))
