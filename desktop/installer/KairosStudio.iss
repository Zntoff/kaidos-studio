; Compile via release.ps1. A stable AppId keeps upgrades in one installation.
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required
#endif
[Setup]
AppId={{7AAFBFBF-6B62-4DC3-B559-25CB927CFF44}
AppName=Kairos Studio
AppVersion={#AppVersion}
AppPublisher=ZNTOff
AppPublisherURL=https://github.com/Zntoff/kairos-studio
AppSupportURL=https://github.com/Zntoff/kairos-studio/issues
AppUpdatesURL=https://github.com/Zntoff/kairos-studio/releases/latest
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Kairos Studio
DefaultGroupName=Kairos Studio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
OutputDir={#ReleaseDir}
OutputBaseFilename=KairosStudio-{#AppVersion}-Setup-win-x64
SetupIconFile=..\ClipperStudio\app.ico
UninstallDisplayIcon={app}\KairosStudio.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
LicenseFile=..\..\LICENSE
#ifdef SignedBuild
SignTool=kairos
SignedUninstaller=yes
#else
SignedUninstaller=no
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "portable.flag,data\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Kairos Studio"; Filename: "{app}\KairosStudio.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Kairos Studio"; Filename: "{app}\KairosStudio.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\KairosStudio.exe"; Description: "{cm:LaunchProgram,Kairos Studio}"; Flags: nowait postinstall skipifsilent; Check: HasWebView2

[Code]
function HasWebView2: Boolean;
var Version: String;
begin
  Result := (RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)) and
    (Version <> '') and (Version <> '0.0.0.0');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var ExitCode: Integer;
begin
  Result := '';
  if not HasWebView2 then begin
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or not HasWebView2 then
      Result := CustomMessage('WebViewFailed');
  end;
end;

[Files]
Source: "{#SourceDir}\tools\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[CustomMessages]
english.WebViewFailed=Microsoft WebView2 could not be installed. Check your internet connection and try again. Your videos and settings have not been removed.
spanish.WebViewFailed=No se pudo instalar Microsoft WebView2. Revisa tu conexión a internet e inténtalo de nuevo. Tus videos y ajustes se conservan.
portuguese.WebViewFailed=Não foi possível instalar o Microsoft WebView2. Verifique sua conexão e tente novamente. Seus vídeos e configurações foram preservados.
french.WebViewFailed=Impossible d'installer Microsoft WebView2. Vérifiez votre connexion et réessayez. Vos vidéos et paramètres sont conservés.
german.WebViewFailed=Microsoft WebView2 konnte nicht installiert werden. Prüfe die Internetverbindung und versuche es erneut. Videos und Einstellungen bleiben erhalten.
