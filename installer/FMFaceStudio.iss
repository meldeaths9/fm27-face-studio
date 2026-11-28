; FM Face Studio 설치 파일 (Inno Setup 6)
; ISCC /DAppVersion=1.0.0 installer\FMFaceStudio.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7C2B36AA-72AB-4B0B-B274-7EE3EB30EBA6}
AppName=FM Face Studio
AppVersion={#AppVersion}
AppVerName=FM Face Studio {#AppVersion}
AppPublisher=meldeaths9
AppPublisherURL=https://github.com/meldeaths9/fm27-face-studio
DefaultDirName={localappdata}\Programs\FM Face Studio
DefaultGroupName=FM Face Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=FMFaceStudio-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\FMFaceStudio.exe
UninstallDisplayName=FM Face Studio
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
#if FileExists(CompilerPath + "Languages\Korean.isl")
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"
#endif
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist_dir\FMFaceStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\FM Face Studio"; Filename: "{app}\FMFaceStudio.exe"
; 앱 안 업데이트(조용한 설치)나 이미 아이콘이 있을 때는 바탕화면을 건드리지 않는다
Name: "{autodesktop}\FM Face Studio"; Filename: "{app}\FMFaceStudio.exe"; Tasks: desktopicon; Check: NeedDesktopIcon

[Run]
Filename: "{app}\FMFaceStudio.exe"; Description: "{cm:LaunchProgram,FM Face Studio}"; Flags: nowait postinstall skipifsilent
; 앱 안에서 '업데이트'로 조용히 설치했을 때는 끝나고 바로 다시 켠다
Filename: "{app}\FMFaceStudio.exe"; Flags: nowait; Check: WizardSilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function NeedDesktopIcon: Boolean;
begin
  Result := (not WizardSilent) and (not FileExists(ExpandConstant('{autodesktop}\FM Face Studio.lnk')));
end;
