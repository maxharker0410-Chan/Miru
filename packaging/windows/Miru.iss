#define MyAppName "S. Chat"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "S. Chat"
#define MyAppExeName "S.Chat.exe"

[Setup]
AppId={{F1D50D2C-1D0F-4A9F-89CB-CC0E68E59107}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\S.Chat
DefaultGroupName=S. Chat
DisableProgramGroupPage=yes
OutputDir=..\..\dist\windows-installer
OutputBaseFilename=S.Chat-Windows-x64-Setup
SetupIconFile=..\..\assets\brand\schat.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\..\dist\S.Chat\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\S. Chat"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\S. Chat"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch S. Chat"; Flags: nowait postinstall skipifsilent
