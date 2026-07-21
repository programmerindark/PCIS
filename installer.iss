; ===================================================================
; PCIS - Inno Setup installer script  (Step 5)
;
; Compile:  ISCC.exe installer.iss   (run build.bat first)
; Output:   installer_output\PCIS_Setup.exe
;
; Download Inno Setup 6: https://jrsoftware.org/isdl.php
; ===================================================================

#define AppName        "PCIS"
#define AppFullName    "PCIS - Poultry Climate Intelligence System"
#define AppVersion     "1.0.0"
#define AppPublisher   "OpenAI-assisted Development"
#define AppURL         "https://github.com/programmerindark/PCIS"
#define AppExeName     "PCIS.exe"

[Setup]
AppId={{8F3B2A41-6C7D-4E92-9A15-3D8C7E4B1F60}
AppName={#AppFullName}
AppVersion={#AppVersion}
AppVerName={#AppFullName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppFullName}
VersionInfoProductName={#AppName}

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE
OutputDir=installer_output
OutputBaseFilename=PCIS_Setup
SetupIconFile=assets\pcis.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppFullName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; Installing to Program Files needs elevation. Declared explicitly so
; the UAC prompt appears once, up front, rather than the install failing
; part-way through with a permissions error.
PrivilegesRequired=admin

; Qt ships 64-bit only, so refuse a 32-bit host rather than installing
; something that cannot start.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"

[Files]
; The whole one-folder build. PCIS.exe loads Qt and the Python runtime
; from the files beside it, so this must be installed intact.
Source: "dist\PCIS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md";      DestDir: "{app}\manual"; Flags: ignoreversion skipifsourcedoesntexist
Source: "PROGRESS.md";    DestDir: "{app}\manual"; Flags: ignoreversion skipifsourcedoesntexist
Source: "CHANGELOG.md";   DestDir: "{app}\manual"; Flags: ignoreversion skipifsourcedoesntexist
Source: "BUILD_WINDOWS.md"; DestDir: "{app}\manual"; Flags: ignoreversion skipifsourcedoesntexist
Source: "docs\*.pdf";     DestDir: "{app}\manual"; Flags: ignoreversion skipifsourcedoesntexist

[Dirs]
; Read-only application content. User data does NOT live here: an app
; under Program Files cannot write to its own folder for a standard
; user, so settings, logs, exports and the database go to
; %LOCALAPPDATA%\PCIS instead (see pcis\paths.py). Creating writable
; folders under {app} would invite exactly the bug that avoids.
Name: "{app}\manual"

[Icons]
Name: "{group}\{#AppName}";              Filename: "{app}\{#AppExeName}"
Name: "{group}\PCIS Data Folder";        Filename: "{localappdata}\PCIS"
Name: "{group}\Uninstall {#AppName}";    Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";        Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove only what the installer created. User data under
; %LOCALAPPDATA%\PCIS is deliberately left behind -- it holds the
; operator's logged recommendation history, which is the dataset the
; ML export depends on. Uninstalling an application should never
; destroy the data it produced; see the [Code] prompt below.
Type: filesandordirs; Name: "{app}\manual"
Type: dirifempty;     Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\PCIS');
    if DirExists(DataDir) then
    begin
      if MsgBox('Also delete your PCIS data?' + #13#10#13#10 +
                'This removes your logged recommendation history, saved ' +
                'settings, exports and logs from:' + #13#10 + DataDir +
                #13#10#13#10 +
                'Choose No to keep them for a future reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
