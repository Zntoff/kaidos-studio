# Fetch only signed Microsoft prerequisites. This file is used by the installer and portable package.
param()
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$tools=Join-Path $PSScriptRoot 'tools'
New-Item -ItemType Directory -Force -Path $tools|Out-Null
$bootstrapper=Join-Path $tools 'MicrosoftEdgeWebview2Setup.exe'
if(-not(Test-Path -LiteralPath $bootstrapper)){
    Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $bootstrapper -UseBasicParsing
}
$signature=Get-AuthenticodeSignature -LiteralPath $bootstrapper
if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation'){
    throw 'WebView2 bootstrapper must have a valid Microsoft signature.'
}
