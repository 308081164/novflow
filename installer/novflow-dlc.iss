; NovFlow 本地生图引擎 (Image Engine DLC) installer — distinct from main NovFlow app
; Product identity must NOT share AppName / Start Menu / DefaultDir / AppId with novflow.iss
; Package contents are staged by package-dlc.ps1 (includes portable Python runtime).

#define MyAppName "NovFlow 本地生图引擎"
#define MyAppNameEn "NovFlow Image Engine"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "NovFlow"
#define MyAppURL "https://github.com/308081164/novflow"
#define MyAppMutex "Global\\NovFlowImageEngineDLC"

[Setup]
; Unique AppId — must never match main NovFlow (A7B3C9D1-4E2F-4A8B-9C1D-202607010001)
AppId={{B8E4D3F2-0A5C-4B7E-9F1D-2C6E8A0B4D5F}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\NovFlowImageEngine
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
OutputDir=..\dist
OutputBaseFilename=NovFlowImageEngineDLCSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=LICENSE-DLC.txt
PrivilegesRequired=lowest
AppMutex={#MyAppMutex}
UninstallDisplayName={#MyAppName}
; Prefer system UI language; Chinese listed first as fallback default
LanguageDetectionMethod=uilanguage
ShowLanguageDialog=auto

[Languages]
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
chinesesimplified.UninstallApp=卸载 {#MyAppName}
chinesesimplified.LaunchEngine=启动 {#MyAppName}
chinesesimplified.AppComment=NovFlow 可选本地生图扩展（独立于主程序）
english.UninstallApp=Uninstall {#MyAppNameEn}
english.LaunchEngine=Start {#MyAppNameEn}
english.AppComment=Optional local image engine for NovFlow (separate from main app)

[Files]
; Full stage from package-dlc.ps1: runtime\ (portable Python + deps), image_engine\, shared\, desktop\, launchers
Source: "..\dist\novflow-dlc-stage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\start-dlc.cmd"; Comment: "{cm:AppComment}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallApp}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\start-dlc.cmd"; Description: "{cm:LaunchEngine}"; Flags: postinstall nowait skipifsilent; WorkingDir: "{app}"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
