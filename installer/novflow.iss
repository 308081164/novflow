; NovFlow Windows installer (Inno Setup 6)
; One-click pack from novflow root: .\package-desktop.ps1
#define MyAppName "NovFlow"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "NovFlow"
#define MyAppURL "https://github.com/novflow/novflow"
#define MyAppExeName "NovFlow.exe"
#define MyAppMutex "Global\\NovFlowDesktopElectron"
#define MyUninstallRegKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\A7B3C9D1-4E2F-4A8B-9C1D-202607010001_is1"

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
SetupIconFile=..\assets\brand\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
CloseApplications=force
CloseApplicationsFilter=*.exe
AppMutex={#MyAppMutex}
; Prefer system UI language; Chinese listed first as fallback default
LanguageDetectionMethod=uilanguage
ShowLanguageDialog=auto

[Languages]
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
chinesesimplified.AppComment=AI 长篇写作工作台
chinesesimplified.LaunchApp=启动 {#MyAppName}
chinesesimplified.StageMissing=未找到 dist\novflow-installer-stage\，请先运行 desktop\build.ps1 生成安装包内容。
english.AppComment=AI long-form writing workbench
english.LaunchApp=Launch {#MyAppName}
english.StageMissing=dist\novflow-installer-stage\ not found. Run desktop\build.ps1 first to build installer contents.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\novflow-installer-stage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "{cm:AppComment}"; IconFilename: "{app}\icon.ico"; IconIndex: 0
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; IconIndex: 0; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\NovFlow"

[Code]
function GetDefaultInstallDir(): String;
begin
  Result := ExpandConstant('{autopf}\{#MyAppName}');
end;

function GetExistingInstallDir(): String;
var
  Dir: String;
begin
  if RegQueryStringValue(HKCU, '{#MyUninstallRegKey}',
    'InstallLocation', Dir) then
  begin
    if DirExists(Dir) then
    begin
      Result := Dir;
      Exit;
    end;
  end;
  if RegQueryStringValue(HKLM, '{#MyUninstallRegKey}',
    'InstallLocation', Dir) then
  begin
    if DirExists(Dir) then
    begin
      Result := Dir;
      Exit;
    end;
  end;
  Result := GetDefaultInstallDir();
end;

procedure KillNovFlowProcesses(InstallDir: String);
var
  ResultCode: Integer;
  DataDir: String;
  PsCmd: String;
  RuntimeNeedle: String;
begin
  Exec('taskkill.exe', '/F /IM {#MyAppExeName} /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  if InstallDir <> '' then
  begin
    RuntimeNeedle := LowerCase(InstallDir + '\runtime');
    PsCmd := 'Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq ''python.exe'' -or $_.Name -eq ''uvicorn.exe'') -and $_.CommandLine -and $_.CommandLine.ToLower().Contains(''' + RuntimeNeedle + ''') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }';
    Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "' + PsCmd + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;

  DataDir := ExpandConstant('{localappdata}\NovFlow\data');
  if FileExists(DataDir + '\server.json') then
  begin
    PsCmd := '$s=Get-Content -Raw ''' + DataDir + '\server.json'' | ConvertFrom-Json; if($s.pid){taskkill /F /T /PID $s.pid}';
    Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "' + PsCmd + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
  if FileExists(DataDir + '\launcher.pid') then
  begin
    PsCmd := '$p=Get-Content -Raw ''' + DataDir + '\launcher.pid''; if($p){taskkill /F /T /PID $p}';
    Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "' + PsCmd + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;

  Sleep(800);
end;

function InitializeSetup(): Boolean;
begin
  if not DirExists(ExpandConstant('{src}\..\dist\novflow-installer-stage')) then
  begin
    MsgBox(CustomMessage('StageMissing'), mbError, MB_OK);
    Result := False;
    Exit;
  end;
  KillNovFlowProcesses(GetExistingInstallDir());
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    KillNovFlowProcesses(ExpandConstant('{app}'));
end;
