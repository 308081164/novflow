; NovFlow Image Engine DLC installer (stub engine + EULA)

#define MyAppName "NovFlow Image Engine DLC"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "NovFlow"
#define MyAppURL "https://github.com/308081164/novflow"

[Setup]
AppId={{A3F8C2E1-9D4B-4F6A-8E2C-1B5D7E9F0A3C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\NovFlow\ImageEngine
DefaultGroupName=NovFlow
OutputDir=..\dist
OutputBaseFilename=NovFlowImageEngineDLCSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=LICENSE-DLC.txt
PrivilegesRequired=lowest

[Files]
Source: "..\image-engine\*"; DestDir: "{app}"; Excludes: "__pycache__\*,*.pyc,.pytest_cache\*"; Flags: ignoreversion recursesubdirs
Source: "..\shared\*"; DestDir: "{app}\shared"; Flags: ignoreversion recursesubdirs
Source: "..\desktop\license_dialog.py"; DestDir: "{app}\desktop"; Flags: ignoreversion

[Icons]
Name: "{group}\Image Engine (Stub)"; Filename: "{app}\start-dlc.cmd"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\start-dlc.cmd"; Description: "启动 Image Engine 服务"; Flags: postinstall nowait skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
