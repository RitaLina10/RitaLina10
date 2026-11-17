; PB Tecnologia - PB Gas Control — instalador Windows (Inno Setup 6)
; Compilar (a partir de gascontrol/):  ISCC.exe /DAppVersion=1.4.0 packaging\windows\installer.iss
; Requer antes: pyinstaller packaging/windows/pbgas-server.spec  (gera dist\pbgas-server)

#ifndef AppVersion
  #error "Informe a versão: ISCC /DAppVersion=x.y.z"
#endif
#define AppName "PB Gas Control"
#define AppFullName "PB Tecnologia - PB Gas Control"
#define AppPublisher "PB Tecnologia"
#define AppExe "pbgas-server.exe"

[Setup]
AppId={{6B1E2C4A-8F3D-4E7B-9A61-2D5C7F0B9E14}
AppName={#AppFullName}
AppVersion={#AppVersion}
AppVerName={#AppFullName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppFullName}
DefaultDirName={autopf}\PB Tecnologia\PB Gas Control
DefaultGroupName=PB Gas Control
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\..\dist\installer
OutputBaseFilename=PBGasControl-Setup-{#AppVersion}
SetupIconFile=pbgas.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppFullName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no
SetupLogging=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "firewall"; Description: "Liberar acesso pela rede local (celulares Android e outros computadores)"; GroupDescription: "Rede:"
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\..\dist\pbgas-server\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "install-service.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "uninstall-service.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "pbgas.ico"; DestDir: "{app}"; Flags: ignoreversion

[INI]
Filename: "{app}\PB Gas Control.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://localhost:{code:GetPort}/"
Filename: "{app}\PB Gas Control.url"; Section: "InternetShortcut"; Key: "IconFile"; String: "{app}\pbgas.ico"
Filename: "{app}\PB Gas Control.url"; Section: "InternetShortcut"; Key: "IconIndex"; String: "0"

[Icons]
Name: "{group}\PB Gas Control"; Filename: "{app}\PB Gas Control.url"; IconFilename: "{app}\pbgas.ico"
Name: "{group}\Desinstalar PB Gas Control"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PB Gas Control"; Filename: "{app}\PB Gas Control.url"; IconFilename: "{app}\pbgas.ico"; Tasks: desktopicon

[Run]
Filename: "notepad.exe"; Parameters: """{commonappdata}\PB Gas Control\PRIMEIRO-ACESSO.txt"""; Description: "Ver usuário e senha do primeiro acesso"; Flags: postinstall skipifsilent nowait; Check: FirstAccessExists
Filename: "{app}\PB Gas Control.url"; Description: "Abrir o PB Gas Control no navegador"; Flags: postinstall skipifsilent shellexec nowait

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\scripts\uninstall-service.ps1"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveTask"

[UninstallDelete]
Type: files; Name: "{app}\PB Gas Control.url"

[Code]
var
  SetupPage: TInputQueryWizardPage;

function ConfigFile: String;
begin
  Result := ExpandConstant('{commonappdata}\PB Gas Control\config.env');
end;

function ExistingPort: String;
var
  Lines: TArrayOfString;
  I: Integer;
  L: String;
begin
  Result := '';
  if LoadStringsFromFile(ConfigFile, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
    begin
      L := Trim(Lines[I]);
      if Pos('PORT=', Uppercase(L)) = 1 then
        Result := Trim(Copy(L, 6, Length(L)));
    end;
end;

function IsUpgrade: Boolean;
begin
  Result := FileExists(ConfigFile);
end;

function OnlyChars(const S, Allowed: String): Boolean;
var
  I: Integer;
begin
  Result := Length(S) > 0;
  for I := 1 to Length(S) do
    if Pos(S[I], Allowed) = 0 then
    begin
      Result := False;
      Exit;
    end;
end;

function ValidEmail(const S: String): Boolean;
var
  At: Integer;
  Domain: String;
begin
  At := Pos('@', S);
  Domain := Copy(S, At + 1, Length(S));
  Result := (Length(S) <= 254) and (At > 1) and (Pos('@', Domain) = 0) and (Pos('.', Domain) > 1)
    and (Domain[Length(Domain)] <> '.')
    and OnlyChars(S, 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-@');
end;

function GetPort(Param: String): String;
begin
  if IsUpgrade and (ExistingPort <> '') then
    Result := ExistingPort
  else if SetupPage <> nil then
    Result := Trim(SetupPage.Values[1])
  else
    Result := '8000';
end;

function FirstAccessExists: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonappdata}\PB Gas Control\PRIMEIRO-ACESSO.txt'));
end;

procedure InitializeWizard;
begin
  SetupPage := CreateInputQueryPage(wpSelectTasks, 'Configuração do servidor',
    'Dados usados na primeira instalação',
    'Informe o e-mail do administrador. A senha inicial será gerada automaticamente e mostrada ao final.');
  SetupPage.Add('E-mail do administrador:', False);
  SetupPage.Add('Porta do servidor (1024-65535):', False);
  // Instalação automatizada: setup.exe /VERYSILENT /ADMINEMAIL=ti@empresa.com.br /PORT=8000
  SetupPage.Values[0] := ExpandConstant('{param:ADMINEMAIL|}');
  SetupPage.Values[1] := ExpandConstant('{param:PORT|8000}');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (SetupPage <> nil) and (PageID = SetupPage.ID) and IsUpgrade;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  P: Integer;
begin
  Result := True;
  if (SetupPage <> nil) and (CurPageID = SetupPage.ID) then
  begin
    SetupPage.Values[0] := Trim(SetupPage.Values[0]);
    // Modo silencioso: não há quem corrija o campo; usa o padrão em vez de repetir a página para sempre.
    if WizardSilent then
    begin
      if not ValidEmail(SetupPage.Values[0]) then
      begin
        Log('ADMINEMAIL ausente ou inválido; usando o padrão');
        SetupPage.Values[0] := 'admin@pbgascontrol.com.br';
      end;
      P := StrToIntDef(Trim(SetupPage.Values[1]), 0);
      if (P < 1024) or (P > 65535) then
      begin
        Log('PORT inválida; usando 8000');
        SetupPage.Values[1] := '8000';
      end;
      Exit;
    end;
    if not ValidEmail(SetupPage.Values[0]) then
    begin
      MsgBox('Informe um e-mail válido (ex.: admin@suaempresa.com.br).', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    P := StrToIntDef(Trim(SetupPage.Values[1]), 0);
    if (P < 1024) or (P > 65535) then
    begin
      MsgBox('Porta inválida. Use um número entre 1024 e 65535 (padrão 8000).', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  // Atualização: para o servidor em execução antes de substituir os arquivos.
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/End /TN "PB Gas Control"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM pbgas-server.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Params, Email: String;
begin
  if CurStep <> ssPostInstall then Exit;
  Email := 'admin@pbgascontrol.com.br';
  if (SetupPage <> nil) and ValidEmail(SetupPage.Values[0]) then Email := SetupPage.Values[0];
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\scripts\install-service.ps1') +
            '" -InstallDir "' + ExpandConstant('{app}') + '" -Port ' + GetPort('') + ' -AdminEmail "' + Email + '"';
  if WizardIsTaskSelected('firewall') then Params := Params + ' -OpenFirewall';
  WizardForm.StatusLabel.Caption := 'Registrando e iniciando o servidor...';
  if not Exec('powershell.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
    MsgBox('O servidor foi instalado, mas não iniciou automaticamente (código ' + IntToStr(Code) + ').' + #13#10 +
           'Veja o log em ' + ExpandConstant('{commonappdata}') + '\PB Gas Control\logs\pbgas.log', mbError, MB_OK);
end;
