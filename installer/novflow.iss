; NovFlow Windows installer (Inno Setup 6)
; 一键打包：在 novflow 根目录运行 .\package-desktop.ps1
#define MyAppName "NovFlow"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "NovFlow"
#define MyAppURL "https://github.com/novflow/novflow"
#define MyAppExeName "NovFlow.exe"

[Setup]
AppId={{A7B3C9D1-4E2F-4A8B-9C1D-202607010001}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=
OutputDir=..\dist
OutputBaseFilename=NovFlowSetup
SetupIconFile=
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\novflow-installer-stage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "AI 长篇网文工作台"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\NovFlow"

[Code]
function InitializeSetup(): Boolean;
begin
  if not DirExists(ExpandConstant('{src}\..\dist\novflow-installer-stage')) then
  begin
    MsgBox('未找到 dist\novflow-installer-stage\。请先运行 desktop\build.ps1 生成安装包内容。', mbError, MB_OK);
    Result := False;
  end
  else
    Result := True;
end;
