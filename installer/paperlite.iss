; Inno Setup script for PaperLite PDF.
; Build:  iscc /DAppVersion=0.1.0 installer\paperlite.iss
; Needs dist\PaperLite\ from "pyinstaller paperlite.spec" first.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "PaperLite PDF"
#define AppExe "PaperLite.exe"

[Setup]
AppId={{6E0F3C59-2B7D-4D7B-9A55-2F1C2C9E7A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=PaperLite
DefaultDirName={autopf}\PaperLite PDF
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=Output
OutputBaseFilename=PaperLite-PDF-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Install for the current user without needing admin rights; can still pick all users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "contextmenu"; Description: "Add ""Compress with PaperLite"" to the right-click menu for PDFs"; GroupDescription: "Explorer:"
Name: "openwith"; Description: "Add PaperLite to ""Open with"" for PDF files"; GroupDescription: "Explorer:"

[Files]
Source: "..\dist\PaperLite\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Right-click > Compress with PaperLite
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PaperLiteCompress"; ValueType: string; ValueName: ""; ValueData: "Compress with PaperLite"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PaperLiteCompress"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"",0"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PaperLiteCompress\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --compress-dialog ""%1"""; Tasks: contextmenu
; Open with
Root: HKA; Subkey: "Software\Classes\PaperLite.PDF"; ValueType: string; ValueName: ""; ValueData: "PDF Document"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PaperLite.PDF\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",0"; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PaperLite.PDF\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PaperLite.PDF"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Flags: uninsdeletekey; Tasks: openwith

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
; after a silent update, reopen the app automatically
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: WizardSilent
