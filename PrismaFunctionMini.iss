#define AppInternalName "PrismaFunctionMini"
#define AppDisplayName "Prisma Function Mini"
#define AppPublisher "ValeriySolod"
#define AppExeName "PrismaFunctionMini.exe"
#define AppSourceDir "dist\PrismaFunctionMini"
#define AppVersion GetFileVersion(AppSourceDir + "\" + AppExeName)

[Setup]
AppId={{118861B7-7FAB-4B85-B88A-F557D89A6986}
AppName={#AppDisplayName}
AppVersion={#AppVersion}
AppVerName={#AppDisplayName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppInternalName}
DefaultGroupName={#AppDisplayName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename={#AppInternalName}-Setup-{#AppVersion}-windows-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName={#AppDisplayName}
UninstallDisplayIcon={app}\{#AppExeName}
CloseApplications=yes
RestartApplications=no
ChangesAssociations=no
ChangesEnvironment=no
SignedUninstaller=yes
#ifdef SignToolName
SignTool={#SignToolName}
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppDisplayName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppDisplayName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppDisplayName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Intentionally empty. Application runtime data lives below
; {localappdata}\PrismaFunctionMini and must survive uninstall/upgrade.
