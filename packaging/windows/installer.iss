; Inno Setup script for the DeckForge desktop application.
;
;   iscc packaging\windows\installer.iss
;
; Installs per-user by default, so no administrator prompt appears and the
; application data directory belongs to the person who installed it.

#define AppName        "DeckForge"
#define AppVersion     "0.1.0"
#define AppPublisher   "DeckForge"
#define AppExeName     "DeckForge.exe"
#define AppId          "{{9C1B3B84-2F4E-4E64-9E01-5A0E5B7C1D22}"
#define SourceDir      "..\..\dist\DeckForge"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppSupportURL=https://github.com/deckforge/deckforge
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
; Per-user install: no UAC prompt, and the data folder is the installer's own.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist\installer
OutputBaseFilename=DeckForge-{#AppVersion}-windows-x64-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The install tree only; conversations, decks and settings live in
; %LOCALAPPDATA%\DeckForge and are deliberately left behind.
Type: filesandordirs; Name: "{app}\_internal\deckforge\web"

[Code]
function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  GetWindowsVersionEx(Version);
  Result := True;
  { WebView2 ships with Windows 11 and with current Windows 10; older builds
    may need the Evergreen runtime, so say so rather than failing silently at
    first launch. }
  if (Version.Major = 10) and (Version.Build < 17763) then
  begin
    MsgBox('DeckForge needs the Microsoft Edge WebView2 runtime.' + #13#10 +
           'If the window does not appear after install, install it from:' + #13#10 +
           'https://developer.microsoft.com/microsoft-edge/webview2/',
           mbInformation, MB_OK);
  end;
end;
