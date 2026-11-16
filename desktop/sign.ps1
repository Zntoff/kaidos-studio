[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Directory,
    [string]$CertificateThumbprint,
    [string]$SigningMetadata,
    [string]$SigningDlib,
    [string]$SignTool,
    [string[]]$FileNames = @('KairosStudio.exe','KairosStudio.dll'),
    [string]$ReportName = 'signing-report.json',
    [string]$TimestampUrl = 'https://timestamp.digicert.com',
    [switch]$RequireSignature
)
$ErrorActionPreference='Stop'
$packageRoot=(Resolve-Path -LiteralPath $Directory).Path
$targets=@($FileNames | ForEach-Object {
    if([IO.Path]::GetFileName($_) -ne $_ -or [IO.Path]::GetExtension($_) -notin @('.exe','.dll')){throw 'Sign only explicitly named EXE/DLL files in the package directory.'}
    Join-Path $packageRoot $_
})
if([IO.Path]::GetFileName($ReportName) -ne $ReportName -or -not $targets.Count){throw 'Invalid signing report or empty target list.'}
foreach($target in $targets){if(-not(Test-Path -LiteralPath $target -PathType Leaf)){throw "Missing application binary: $target"}}
if($CertificateThumbprint -and $SigningMetadata){throw 'Select a certificate OR Artifact Signing.'}
$configured=$CertificateThumbprint -or $SigningMetadata
if($RequireSignature -and -not $configured){throw 'Public release requires a trusted code-signing certificate or Artifact Signing profile. No self-signed fallback is permitted.'}
if($configured){
    if(-not $SignTool){$command=Get-Command signtool.exe -ErrorAction SilentlyContinue;if($command){$SignTool=$command.Source}}
    if(-not $SignTool){
        $sdkRoot=Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
        if(Test-Path -LiteralPath $sdkRoot){$SignTool=Get-ChildItem -LiteralPath $sdkRoot -Directory|Sort-Object Name -Descending|ForEach-Object {Join-Path $_.FullName 'x64\signtool.exe'}|Where-Object {Test-Path -LiteralPath $_}|Select-Object -First 1}
    }
    if(-not $SignTool -or -not(Test-Path -LiteralPath $SignTool)){throw 'Install the Windows SDK or Artifact Signing Client Tools and provide -SignTool.'}
    $arguments=@('sign','/fd','SHA256','/td','SHA256','/d','Kairos Studio')
    if($CertificateThumbprint){
        $thumbprint=$CertificateThumbprint.Replace(' ','')
        if($thumbprint -notmatch '^[0-9A-Fa-f]{40}$'){throw 'Invalid certificate thumbprint.'}
        $certificate=Get-Item -LiteralPath "Cert:\CurrentUser\My\$thumbprint" -ErrorAction SilentlyContinue
        if(-not $certificate){$certificate=Get-Item -LiteralPath "Cert:\LocalMachine\My\$thumbprint" -ErrorAction SilentlyContinue;$arguments+='/sm'}
        if(-not $certificate -or -not $certificate.HasPrivateKey -or $certificate.NotAfter -le (Get-Date)){throw 'A current code-signing certificate with a private key must be available in the certificate store.'}
        if($certificate.Subject -eq $certificate.Issuer){throw 'Self-signed certificates are not accepted for public releases.'}
        $codeSigningUsage=$certificate.Extensions|Where-Object {$_ -is [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]}|ForEach-Object {$_.EnhancedKeyUsages}|Where-Object {$_.Value -eq '1.3.6.1.5.5.7.3.3'}
        if(-not $codeSigningUsage){throw 'The certificate must permit code signing.'}
        $arguments+=@('/sha1',$thumbprint)
    }else{
        if(-not $SigningDlib -or -not(Test-Path -LiteralPath $SigningDlib)){throw 'Provide the Microsoft Artifact Signing dlib path with -SigningDlib.'}
        $metadata=Get-Content -LiteralPath $SigningMetadata -Raw|ConvertFrom-Json
        if(-not $metadata.Endpoint -or -not $metadata.CodeSigningAccountName -or -not $metadata.CertificateProfileName){throw 'Artifact Signing metadata must include Endpoint, CodeSigningAccountName and CertificateProfileName.'}
        $endpoint=[uri]$metadata.Endpoint
        if($endpoint.Scheme -ne 'https' -or -not $endpoint.Host.EndsWith('.codesigning.azure.net')){throw 'Artifact Signing requires an official HTTPS codesigning.azure.net endpoint.'}
        $arguments+=@('/dlib',(Resolve-Path -LiteralPath $SigningDlib).Path,'/dmdf',(Resolve-Path -LiteralPath $SigningMetadata).Path)
        $TimestampUrl='https://timestamp.acs.microsoft.com'
    }
    $arguments+=@('/tr',$TimestampUrl)
    foreach($target in $targets){
        & $SignTool @arguments $target
        if($LASTEXITCODE -ne 0){throw "Code signing failed: $target"}
        & $SignTool verify /pa /all /tw $target
        if($LASTEXITCODE -ne 0){throw "Signature verification failed: $target"}
    }
}
$report=@($targets|ForEach-Object {
    $signature=Get-AuthenticodeSignature -LiteralPath $_
    if($configured -and ($signature.Status -ne 'Valid' -or -not $signature.TimeStamperCertificate)){throw "A trusted, timestamped signature is required: $_"}
    [ordered]@{file=[IO.Path]::GetFileName($_);status=[string]$signature.Status;publisher=if($signature.SignerCertificate){$signature.SignerCertificate.Subject}else{$null};timestamped=[bool]$signature.TimeStamperCertificate}
})
[ordered]@{publicReleaseReady=[bool]$configured;files=$report}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $packageRoot $ReportName) -Encoding UTF8
if(-not $configured){Write-Warning 'Local build is unsigned. Signing integration is ready; obtain a verified publisher identity before public distribution.'}
