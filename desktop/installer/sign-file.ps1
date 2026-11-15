param([Parameter(Mandatory=$true)][string]$File)
$ErrorActionPreference='Stop'
$item=Get-Item -LiteralPath $File
& (Join-Path $PSScriptRoot '..\sign.ps1') -Directory $item.DirectoryName -FileNames @($item.Name) `
    -CertificateThumbprint $env:KAIROS_SIGN_CERTIFICATE -SigningMetadata $env:KAIROS_SIGN_METADATA `
    -SigningDlib $env:KAIROS_SIGN_DLIB -SignTool $env:KAIROS_SIGN_TOOL -RequireSignature `
    -ReportName 'installer-signing-report.json'
