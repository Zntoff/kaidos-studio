# Build dependency only; never included in Kairos packages. Verify publisher before executing.
param()
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$version='7.1.1'
$destination=Join-Path $env:LOCALAPPDATA "KairosBuildTools\InnoSetup-$version"
$compiler=Join-Path $destination 'ISCC.exe'
if(Test-Path -LiteralPath $compiler){return $compiler}
$download=Join-Path $env:TEMP ('kairos-inno-'+[guid]::NewGuid().ToString('N')+'.exe')
Invoke-WebRequest "https://github.com/jrsoftware/issrc/releases/download/is-7_1_1/innosetup-$version-x64.exe" -OutFile $download -UseBasicParsing
$signature=Get-AuthenticodeSignature -LiteralPath $download
if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys B\.V\.') {throw 'Untrusted Inno Setup download.'}
$process=Start-Process -FilePath $download -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/CURRENTUSER',('/DIR="'+$destination+'"')) -WindowStyle Hidden -Wait -PassThru
if($process.ExitCode -ne 0 -or -not(Test-Path -LiteralPath $compiler)){throw 'Inno Setup installation failed.'}
Remove-Item -LiteralPath $download
return $compiler
