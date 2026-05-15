; =============================================================================
;  ZapDin — Instalador Inteligente v4
;  Inno Setup 6.3+  |  Task Scheduler  |  WebView2  |  Velopack
;
;  NOVIDADE v4: Tela de configuração completa com:
;    - Auto-detecção do PostgreSQL
;    - Teste de conexão com banco (botão "Testar")
;    - Criação automática do banco zapdin_app
;    - Coleta de porta e token do Monitor
;    - Geração do .env final antes de subir o serviço
;
;  Pipeline CI esperado (GitHub Actions):
;    1. nuitka --onefile --output-filename=ZapDin-App.exe    app/launcher_service.py
;    2. nuitka --onefile --output-filename=ZapDin-Worker.exe app/worker_main.py
;    3. nuitka --onefile --output-filename=ZapDin-Launcher.exe app/launcher_gui.py
;    4. playwright install chromium --with-deps
;       resultado copiado para payload/playwright-browsers/
;    5. Inno Setup compila este .iss → output/ZapDin-Setup-{VER}.exe
; =============================================================================

#include "version.iss"
#define AppName           "ZapDin"
#define AppPublisher      "ZapDin Sistemas"
#define AppURL            "https://zapdin.com.br"
#define ServiceApp        "ZapDinApp"
#define ServiceWorker     "ZapDinWorker"
#define DefaultPort       "4000"
#define MonitorURL        "http://zapdin.gruposgapetro.com.br:5000"

; =============================================================================
[Setup]
AppId={{B5F2C9D1-7A4E-4F8B-9C12-2D5E8A1F3B47}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/suporte
VersionInfoVersion={#AppVersion}

DefaultDirName=C:\ZapDinApp
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes

OutputBaseFilename=ZapDin-Setup-{#AppVersion}
OutputDir=..\output
SetupIconFile=..\payload\branding\zapdin.ico

Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=force
RestartApplications=no

; =============================================================================
[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

; =============================================================================
[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; \
  GroupDescription: "Atalhos:"; Flags: checkedonce

; =============================================================================
[Files]
Source: "..\payload\ZapDin-App.exe";      DestDir: "{app}"; Flags: ignoreversion
Source: "..\payload\ZapDin-Worker.exe";   DestDir: "{app}"; Flags: ignoreversion
Source: "..\payload\ZapDin-Launcher.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\payload\Update.exe";          DestDir: "{app}"; Flags: ignoreversion

Source: "..\payload\playwright-browsers\*"; DestDir: "{app}\playwright-browsers"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

Source: "..\payload\static\*"; DestDir: "{app}\static"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

Source: "..\payload\branding\zapdin.ico"; DestDir: "{app}\branding"; Flags: ignoreversion

Source: "..\payload\deps\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall; Check: not IsWebView2Installed
Source: "..\payload\deps\vc_redist.x64.exe"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall; Check: not IsVCRedistInstalled

; =============================================================================
[Dirs]
Name: "{app}\data";  Permissions: authusers-modify
Name: "{app}\logs";  Permissions: authusers-modify
Name: "{app}\tools"; Permissions: authusers-modify

; =============================================================================
[Icons]
Name: "{group}\{#AppName}"; \
  Filename: "{app}\ZapDin-Launcher.exe"; \
  IconFilename: "{app}\branding\zapdin.ico"
Name: "{userdesktop}\{#AppName}"; \
  Filename: "{app}\ZapDin-Launcher.exe"; \
  IconFilename: "{app}\branding\zapdin.ico"; \
  Tasks: desktopicon
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"

; =============================================================================
[Run]
; Pré-requisitos silenciosos
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; \
  Parameters: "/silent /install"; \
  StatusMsg: "Instalando Microsoft Edge WebView2 Runtime..."; \
  Flags: waituntilterminated; Check: not IsWebView2Installed

Filename: "{tmp}\vc_redist.x64.exe"; \
  Parameters: "/install /quiet /norestart"; \
  StatusMsg: "Instalando Visual C++ 2022 Redistributable..."; \
  Flags: waituntilterminated; Check: not IsVCRedistInstalled

; Registrar tarefas + criar banco + iniciar app
Filename: "powershell.exe"; \
  Parameters: "-ExecutionPolicy Bypass -NoProfile -File ""{app}\tools\setup_final.ps1"""; \
  StatusMsg: "Configurando banco de dados e servicos..."; \
  Flags: runhidden waituntilterminated

; Iniciar imediatamente
Filename: "schtasks.exe"; Parameters: "/run /tn ZapDinApp"; \
  StatusMsg: "Iniciando ZapDin..."; Flags: runhidden

; Abre launcher ao final (opcional)
Filename: "{app}\ZapDin-Launcher.exe"; \
  Description: "Abrir ZapDin agora"; \
  Flags: nowait postinstall skipifsilent unchecked

; =============================================================================
[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/end /tn ZapDinApp";          Flags: runhidden
Filename: "schtasks.exe"; Parameters: "/end /tn ZapDinWorker";        Flags: runhidden
Filename: "schtasks.exe"; Parameters: "/delete /tn ZapDinApp    /f";  Flags: runhidden
Filename: "schtasks.exe"; Parameters: "/delete /tn ZapDinWorker /f";  Flags: runhidden
Filename: "taskkill.exe"; Parameters: "/IM ZapDin-App.exe /F";        Flags: runhidden
Filename: "taskkill.exe"; Parameters: "/IM ZapDin-Worker.exe /F";     Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\logs"
Type: files;          Name: "{app}\.env"

; =============================================================================
;  [Code] — Tela de configuração inteligente
; =============================================================================
[Code]

// ── Constantes de registro ────────────────────────────────────────────────────
const
  WV2_KEY_WOW  = 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WV2_KEY      = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  VCREDIST_KEY = 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';

// ── Variáveis globais da página de configuração ───────────────────────────────
var
  CfgPage: TWizardPage;

  // PostgreSQL
  LblPgBin:    TLabel;
  PgBinEdit:   TEdit;
  BtnDetect:   TButton;
  BtnBrowse:   TButton;
  LblPgPass:   TLabel;
  PgPassEdit:  TEdit;
  BtnTestConn: TButton;
  LblPgStatus: TLabel;

  // Porta
  LblPort:  TLabel;
  PortEdit: TEdit;

  // Token do Monitor
  LblToken:    TLabel;
  TokenEdit:   TEdit;
  LblTokenHint: TLabel;

  // Estado
  _PgTestPassed: Boolean;

// ── Detecção de deps ──────────────────────────────────────────────────────────
function IsWebView2Installed: Boolean;
var V: string;
begin
  Result := RegQueryStringValue(HKLM, WV2_KEY_WOW, 'pv', V) or
            RegQueryStringValue(HKLM, WV2_KEY,     'pv', V) or
            RegQueryStringValue(HKCU, WV2_KEY,     'pv', V);
end;

function IsVCRedistInstalled: Boolean;
var Installed: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM, VCREDIST_KEY, 'Installed', Installed)
            and (Installed = 1);
end;

// ── Gera SECRET_KEY aleatória ────────────────────────────────────────────────
function GenerateSecretKey: string;
var i: Integer; chars: string;
begin
  chars  := 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  Result := '';
  Randomize;
  for i := 1 to 48 do
    Result := Result + chars[Random(62) + 1];
end;

// ── Percorre caminhos comuns procurando psql.exe ─────────────────────────────
function FindPostgresPath: string;
var
  Candidates: TArrayOfString;
  i: Integer;
  Drive, Base, Full: string;
begin
  Result := '';
  // Drives e raízes comuns
  SetArrayLength(Candidates, 24);
  // SGAPetro (cliente mais comum)
  Candidates[0]  := 'C:\SGAPetro\PostgreSQL\bin';
  Candidates[1]  := 'D:\SGAPetro\PostgreSQL\bin';
  // PostgreSQL padrão
  Candidates[2]  := 'C:\Program Files\PostgreSQL\17\bin';
  Candidates[3]  := 'C:\Program Files\PostgreSQL\16\bin';
  Candidates[4]  := 'C:\Program Files\PostgreSQL\15\bin';
  Candidates[5]  := 'C:\Program Files\PostgreSQL\14\bin';
  Candidates[6]  := 'C:\Program Files\PostgreSQL\13\bin';
  Candidates[7]  := 'C:\Program Files\PostgreSQL\12\bin';
  Candidates[8]  := 'C:\Program Files (x86)\PostgreSQL\17\bin';
  Candidates[9]  := 'C:\Program Files (x86)\PostgreSQL\16\bin';
  Candidates[10] := 'C:\Program Files (x86)\PostgreSQL\15\bin';
  Candidates[11] := 'C:\Program Files (x86)\PostgreSQL\14\bin';
  Candidates[12] := 'C:\PostgreSQL\17\bin';
  Candidates[13] := 'C:\PostgreSQL\16\bin';
  Candidates[14] := 'C:\PostgreSQL\15\bin';
  Candidates[15] := 'C:\PostgreSQL\14\bin';
  Candidates[16] := 'C:\pgsql\bin';
  Candidates[17] := 'D:\PostgreSQL\16\bin';
  Candidates[18] := 'D:\PostgreSQL\15\bin';
  Candidates[19] := 'D:\PostgreSQL\14\bin';
  Candidates[20] := 'C:\PostgreSQL\bin';
  Candidates[21] := 'C:\Program Files\PostgreSQL\bin';
  Candidates[22] := 'D:\pgsql\bin';
  Candidates[23] := 'C:\apps\PostgreSQL\bin';

  for i := 0 to GetArrayLength(Candidates) - 1 do
  begin
    if FileExists(Candidates[i] + '\psql.exe') then
    begin
      Result := Candidates[i];
      Log('[ZapDin] PostgreSQL encontrado em: ' + Result);
      Exit;
    end;
  end;
  Log('[ZapDin] PostgreSQL não encontrado nos caminhos padrão.');
end;

// ── Escapa string para uso em PowerShell entre aspas simples ─────────────────
// (substitui ' por '' — único caractere especial em single-quoted PS strings)
function EscapeForPS(const S: string): string;
var i: Integer; C: Char;
begin
  Result := '';
  for i := 1 to Length(S) do
  begin
    C := S[i];
    if C = '''' then
      Result := Result + ''''''  // '' dentro de single-quote PS
    else
      Result := Result + C;
  end;
end;

// ── Executa psql via PowerShell com PGPASSWORD definido ──────────────────────
// Retorna True se ExitCode = 0
function RunPsql(PgBin, Password, DbName, Sql: string): Boolean;
var
  PsFile, PsContent, DbArg: string;
  RC: Integer;
begin
  PsFile := ExpandConstant('{tmp}\zapdin_pg.ps1');
  if DbName <> '' then
    DbArg := '-d ''' + DbName + ''''
  else
    DbArg := '-d postgres';

  PsContent :=
    '$env:PGPASSWORD = ''' + EscapeForPS(Password) + '''' + #13#10 +
    '& ''' + EscapeForPS(PgBin) + '\psql.exe'' -U postgres -h localhost ' +
    DbArg + ' -c ''' + EscapeForPS(Sql) + ''' 2>&1' + #13#10;

  DeleteFile(PsFile);
  SaveStringToFile(PsFile, PsContent, False);

  Exec('powershell.exe',
       '-ExecutionPolicy Bypass -NoProfile -File "' + PsFile + '"',
       '', SW_HIDE, ewWaitUntilTerminated, RC);

  DeleteFile(PsFile);
  Result := (RC = 0);
end;

// ── Handler: botão "Detectar PostgreSQL" ─────────────────────────────────────
procedure OnDetectClick(Sender: TObject);
var Found: string;
begin
  Found := FindPostgresPath;
  if Found <> '' then
  begin
    PgBinEdit.Text    := Found;
    LblPgStatus.Caption  := '';
    _PgTestPassed     := False;
    MsgBox('PostgreSQL encontrado em:' + #13#10 + Found + #13#10#13#10 +
           'Agora informe a senha e clique em "Testar Conexão".',
           mbInformation, MB_OK);
  end else
    MsgBox('PostgreSQL não encontrado nos caminhos padrão.' + #13#10 +
           'Use o botão "Procurar..." para localizar manualmente a pasta "bin" do PostgreSQL.',
           mbError, MB_OK);
end;

// ── Handler: botão "Testar Conexão" ──────────────────────────────────────────
procedure OnTestConnClick(Sender: TObject);
var PgBin, Password: string;
begin
  PgBin    := Trim(PgBinEdit.Text);
  Password := Trim(PgPassEdit.Text);

  if PgBin = '' then
  begin
    LblPgStatus.Caption   := '❌ Informe o caminho do PostgreSQL primeiro.';
    LblPgStatus.Font.Color := clRed;
    _PgTestPassed          := False;
    Exit;
  end;

  if not FileExists(PgBin + '\psql.exe') then
  begin
    LblPgStatus.Caption   := '❌ psql.exe não encontrado nesta pasta.';
    LblPgStatus.Font.Color := clRed;
    _PgTestPassed          := False;
    Exit;
  end;

  LblPgStatus.Caption   := '⏳ Testando conexão...';
  LblPgStatus.Font.Color := $008080; // teal
  CfgPage.Surface.Repaint;

  if RunPsql(PgBin, Password, '', 'SELECT 1') then
  begin
    LblPgStatus.Caption   := '✅ Conexão estabelecida com sucesso!';
    LblPgStatus.Font.Color := clGreen;
    _PgTestPassed          := True;
    Log('[ZapDin] Conexão PostgreSQL OK.');
  end else
  begin
    LblPgStatus.Caption   :=
      '❌ Falha na conexão. Verifique o caminho e a senha.';
    LblPgStatus.Font.Color := clRed;
    _PgTestPassed          := False;
    Log('[ZapDin] Falha na conexão PostgreSQL.');
  end;
end;

// ── Handler: botão "Procurar..." (browse manual) ─────────────────────────────
procedure OnBrowseClick(Sender: TObject);
var Dir: string;
begin
  Dir := PgBinEdit.Text;
  if BrowseForFolder('Selecione a pasta "bin" do PostgreSQL' + #13#10 +
                     '(deve conter psql.exe)', Dir, False) then
  begin
    PgBinEdit.Text   := Dir;
    _PgTestPassed    := False;
    LblPgStatus.Caption := '';
  end;
end;

// ── Cria a página de configuração personalizada ──────────────────────────────
procedure CreateConfigPage;
var
  Top: Integer;
  LblSep1, LblSep2: TLabel;
begin
  CfgPage := CreateCustomPage(
    wpSelectDir,
    'Configuração do ZapDin',
    'Preencha as informações abaixo. O instalador irá configurar tudo automaticamente.'
  );

  Top := 4;

  // ── Seção: PostgreSQL ──────────────────────────────────────────────────────
  LblPgBin        := TLabel.Create(CfgPage);
  LblPgBin.Parent := CfgPage.Surface;
  LblPgBin.Caption := 'Pasta bin do PostgreSQL (onde está o psql.exe):';
  LblPgBin.Left   := 0; LblPgBin.Top := Top; LblPgBin.AutoSize := True;
  Top := Top + 18;

  PgBinEdit        := TEdit.Create(CfgPage);
  PgBinEdit.Parent := CfgPage.Surface;
  PgBinEdit.Left   := 0; PgBinEdit.Top := Top;
  PgBinEdit.Width  := CfgPage.SurfaceWidth - 180;
  PgBinEdit.Text   := FindPostgresPath;
  Top := Top + 24;

  BtnDetect        := TButton.Create(CfgPage);
  BtnDetect.Parent := CfgPage.Surface;
  BtnDetect.Caption := 'Detectar';
  BtnDetect.Left   := CfgPage.SurfaceWidth - 174;
  BtnDetect.Top    := Top - 24;
  BtnDetect.Width  := 80; BtnDetect.Height := 23;
  BtnDetect.OnClick := @OnDetectClick;

  BtnBrowse        := TButton.Create(CfgPage);
  BtnBrowse.Parent := CfgPage.Surface;
  BtnBrowse.Caption := 'Procurar...';
  BtnBrowse.Left   := CfgPage.SurfaceWidth - 88;
  BtnBrowse.Top    := Top - 24;
  BtnBrowse.Width  := 88; BtnBrowse.Height := 23;
  BtnBrowse.OnClick := @OnBrowseClick;

  LblPgPass        := TLabel.Create(CfgPage);
  LblPgPass.Parent := CfgPage.Surface;
  LblPgPass.Caption := 'Senha do PostgreSQL (usuário postgres):';
  LblPgPass.Left   := 0; LblPgPass.Top := Top; LblPgPass.AutoSize := True;
  Top := Top + 18;

  PgPassEdit           := TEdit.Create(CfgPage);
  PgPassEdit.Parent    := CfgPage.Surface;
  PgPassEdit.Left      := 0; PgPassEdit.Top := Top;
  PgPassEdit.Width     := CfgPage.SurfaceWidth - 94;
  PgPassEdit.PasswordChar := '*';
  Top := Top + 24;

  BtnTestConn        := TButton.Create(CfgPage);
  BtnTestConn.Parent := CfgPage.Surface;
  BtnTestConn.Caption := 'Testar Conexão';
  BtnTestConn.Left   := CfgPage.SurfaceWidth - 88;
  BtnTestConn.Top    := Top - 24;
  BtnTestConn.Width  := 88; BtnTestConn.Height := 23;
  BtnTestConn.OnClick := @OnTestConnClick;

  LblPgStatus        := TLabel.Create(CfgPage);
  LblPgStatus.Parent := CfgPage.Surface;
  LblPgStatus.Caption := '';
  LblPgStatus.Left   := 0; LblPgStatus.Top := Top;
  LblPgStatus.AutoSize := True;
  LblPgStatus.Font.Style := [fsBold];
  Top := Top + 20;

  // ── Separador ─────────────────────────────────────────────────────────────
  LblSep1        := TLabel.Create(CfgPage);
  LblSep1.Parent := CfgPage.Surface;
  LblSep1.Caption := '──────────────────────────────────────────────────────';
  LblSep1.Left   := 0; LblSep1.Top := Top;
  LblSep1.AutoSize := True; LblSep1.Font.Color := $BBBBBB;
  Top := Top + 16;

  // ── Porta ──────────────────────────────────────────────────────────────────
  LblPort        := TLabel.Create(CfgPage);
  LblPort.Parent := CfgPage.Surface;
  LblPort.Caption := 'Porta do App (padrão: 4000):';
  LblPort.Left   := 0; LblPort.Top := Top; LblPort.AutoSize := True;
  Top := Top + 18;

  PortEdit        := TEdit.Create(CfgPage);
  PortEdit.Parent := CfgPage.Surface;
  PortEdit.Left   := 0; PortEdit.Top := Top;
  PortEdit.Width  := 80;
  PortEdit.Text   := '{#DefaultPort}';
  Top := Top + 24;

  // ── Separador ─────────────────────────────────────────────────────────────
  LblSep2        := TLabel.Create(CfgPage);
  LblSep2.Parent := CfgPage.Surface;
  LblSep2.Caption := '──────────────────────────────────────────────────────';
  LblSep2.Left   := 0; LblSep2.Top := Top;
  LblSep2.AutoSize := True; LblSep2.Font.Color := $BBBBBB;
  Top := Top + 16;

  // ── Token do Monitor ──────────────────────────────────────────────────────
  LblToken        := TLabel.Create(CfgPage);
  LblToken.Parent := CfgPage.Surface;
  LblToken.Caption := 'Token do Monitor (obtenha no painel ZapDin Monitor):';
  LblToken.Left   := 0; LblToken.Top := Top; LblToken.AutoSize := True;
  Top := Top + 18;

  TokenEdit        := TEdit.Create(CfgPage);
  TokenEdit.Parent := CfgPage.Surface;
  TokenEdit.Left   := 0; TokenEdit.Top := Top;
  TokenEdit.Width  := CfgPage.SurfaceWidth;
  TokenEdit.Font.Size := 9;
  Top := Top + 24;

  LblTokenHint        := TLabel.Create(CfgPage);
  LblTokenHint.Parent := CfgPage.Surface;
  LblTokenHint.Caption :=
    'Acesse o Monitor → Clientes → (cliente) → copie o Token de Ativação.';
  LblTokenHint.Left    := 0; LblTokenHint.Top := Top;
  LblTokenHint.AutoSize := True;
  LblTokenHint.Font.Color := $777777;
  LblTokenHint.Font.Size  := 8;
end;

// ── Inicialização ─────────────────────────────────────────────────────────────
procedure InitializeWizard;
begin
  _PgTestPassed := False;
  CreateConfigPage;
end;

// ── Validação ao avançar ──────────────────────────────────────────────────────
function NextButtonClick(CurPageID: Integer): Boolean;
var PgBin, Port, Token: string;
begin
  Result := True;
  if CurPageID <> CfgPage.ID then Exit;

  PgBin := Trim(PgBinEdit.Text);
  Port  := Trim(PortEdit.Text);
  Token := Trim(TokenEdit.Text);

  // Caminho do PostgreSQL
  if PgBin = '' then
  begin
    MsgBox('Informe o caminho da pasta bin do PostgreSQL.', mbError, MB_OK);
    PgBinEdit.SetFocus;
    Result := False; Exit;
  end;
  if not FileExists(PgBin + '\psql.exe') then
  begin
    MsgBox('psql.exe não encontrado em:' + #13#10 + PgBin +
           #13#10#13#10 + 'Verifique se o caminho aponta para a pasta "bin" do PostgreSQL.',
           mbError, MB_OK);
    PgBinEdit.SetFocus;
    Result := False; Exit;
  end;

  // Conexão testada
  if not _PgTestPassed then
  begin
    MsgBox('Clique em "Testar Conexão" e aguarde a confirmação ' +
           'antes de continuar.', mbError, MB_OK);
    PgPassEdit.SetFocus;
    Result := False; Exit;
  end;

  // Porta
  if (Port = '') or (StrToIntDef(Port, 0) < 1024) or (StrToIntDef(Port, 0) > 65535) then
  begin
    MsgBox('Porta inválida. Use um número entre 1024 e 65535 (padrão: 4000).',
           mbError, MB_OK);
    PortEdit.SetFocus;
    Result := False; Exit;
  end;

  // Token
  if Token = '' then
  begin
    MsgBox('Informe o Token do Monitor.' + #13#10 +
           'Acesse o painel Monitor → Clientes → Token de Ativação.',
           mbError, MB_OK);
    TokenEdit.SetFocus;
    Result := False; Exit;
  end;

  Log('[ZapDin] Configuração validada: PgBin=' + PgBin + ' Port=' + Port);
end;

// ── Gera o script PowerShell final (roda após cópia dos arquivos) ─────────────
// Responsabilidades:
//   1. Cria o banco zapdin_app (se não existir)
//   2. Grava o .env definitivo
//   3. Registra as Tasks do Scheduler
procedure WriteSetupFinalScript;
var
  AppDir, ScriptFile, Content: string;
  PgBin, PgPass, Port, Token, SecretKey: string;
  DbUrl: string;
begin
  AppDir    := ExpandConstant('{app}');
  ScriptFile := AppDir + '\tools\setup_final.ps1';

  PgBin     := Trim(PgBinEdit.Text);
  PgPass    := Trim(PgPassEdit.Text);
  Port      := Trim(PortEdit.Text);
  Token     := Trim(TokenEdit.Text);
  SecretKey := GenerateSecretKey;

  // Monta a DATABASE_URL com a senha URL-encoded (@ → %40)
  // Para isso usamos PS inline no script gerado
  Content :=
    '# ZapDin Setup Final — gerado automaticamente pelo instalador'          + #13#10 +
    '$AppDir   = "' + AppDir + '"'                                            + #13#10 +
    '$PgBin    = "' + PgBin + '"'                                             + #13#10 +
    '$PgPass   = ''' + EscapeForPS(PgPass) + ''''                            + #13#10 +
    '$Port     = "' + Port + '"'                                              + #13#10 +
    '$Token    = "' + EscapeForPS(Token) + '"'                               + #13#10 +
    '$SecretKey= "' + SecretKey + '"'                                         + #13#10 +
    '$LogFile  = "$AppDir\logs\install.log"'                                  + #13#10 +
    ''                                                                        + #13#10 +
    'New-Item -ItemType Directory -Force -Path "$AppDir\logs" | Out-Null'    + #13#10 +
    'New-Item -ItemType Directory -Force -Path "$AppDir\data" | Out-Null'    + #13#10 +
    'function Log($msg) { Add-Content $LogFile "[$(Get-Date -f ''yyyy-MM-dd HH:mm:ss'')] $msg"; Write-Host $msg }' + #13#10 +
    ''                                                                        + #13#10 +
    'Log "=== ZapDin Setup v{#AppVersion} iniciando ==="'                   + #13#10 +
    ''                                                                        + #13#10 +
    '# ── 1. Criar banco zapdin_app se não existir ───────────────────────'  + #13#10 +
    '$env:PGPASSWORD = $PgPass'                                               + #13#10 +
    '$exists = & "$PgBin\psql.exe" -U postgres -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname=''zapdin_app''" 2>&1' + #13#10 +
    'if ($exists -match "1") {'                                               + #13#10 +
    '  Log "Banco zapdin_app ja existe — pulando criacao."'                  + #13#10 +
    '} else {'                                                                + #13#10 +
    '  Log "Criando banco zapdin_app..."'                                     + #13#10 +
    '  & "$PgBin\psql.exe" -U postgres -h localhost -c "CREATE DATABASE zapdin_app ENCODING=''UTF8''" 2>&1 | ForEach-Object { Log $_ }' + #13#10 +
    '  if ($LASTEXITCODE -eq 0) { Log "Banco criado com sucesso." }'         + #13#10 +
    '  else { Log "AVISO: Falha ao criar banco. O app tentara criar na inicializacao." }' + #13#10 +
    '}'                                                                       + #13#10 +
    ''                                                                        + #13#10 +
    '# ── 2. Gravar .env definitivo ──────────────────────────────────────'  + #13#10 +
    '$EnvFile = "$AppDir\.env"'                                               + #13#10 +
    '# URL-encode a senha: @ → %40, # → %23, % → %25, espaço → %20'        + #13#10 +
    '$PassEncoded = $PgPass -replace "%","%25" -replace "@","%40" -replace "#","%23" -replace " ","%20"' + #13#10 +
    '$DbUrl = "postgresql://postgres:$PassEncoded@localhost:5432/zapdin_app?sslmode=disable"' + #13#10 +
    ''                                                                        + #13#10 +
    '$envContent = @"'                                                        + #13#10 +
    'APP_STATE=locked'                                                        + #13#10 +
    'PORT=$Port'                                                              + #13#10 +
    'DATABASE_URL=$DbUrl'                                                     + #13#10 +
    'SECRET_KEY=$SecretKey'                                                   + #13#10 +
    'MONITOR_URL={#MonitorURL}'                                               + #13#10 +
    'MONITOR_CLIENT_TOKEN=$Token'                                             + #13#10 +
    'CLIENT_NAME='                                                            + #13#10 +
    'CLIENT_CNPJ='                                                            + #13#10 +
    'PLAYWRIGHT_BROWSERS_PATH=$AppDir\playwright-browsers'                   + #13#10 +
    '"@'                                                                      + #13#10 +
    ''                                                                        + #13#10 +
    'Set-Content -Path $EnvFile -Value $envContent -Encoding UTF8'           + #13#10 +
    'Log ".env gravado em: $EnvFile"'                                         + #13#10 +
    ''                                                                        + #13#10 +
    '# ── 3. Registrar Tasks do Scheduler ───────────────────────────────'   + #13#10 +
    'Log "Registrando tarefas agendadas..."'                                  + #13#10 +
    'schtasks /end    /tn "ZapDinApp"    2>$null'                            + #13#10 +
    'schtasks /end    /tn "ZapDinWorker" 2>$null'                            + #13#10 +
    'schtasks /delete /tn "ZapDinApp"    /f 2>$null'                        + #13#10 +
    'schtasks /delete /tn "ZapDinWorker" /f 2>$null'                        + #13#10 +
    ''                                                                        + #13#10 +
    'schtasks /create /tn "ZapDinApp" /tr "`"$AppDir\ZapDin-App.exe`"" /sc onstart /ru SYSTEM /rl HIGHEST /f 2>&1 | ForEach-Object { Log $_ }' + #13#10 +
    'schtasks /create /tn "ZapDinWorker" /tr "`"$AppDir\ZapDin-Worker.exe`"" /sc onstart /ru SYSTEM /rl HIGHEST /delay 0000:20 /f 2>&1 | ForEach-Object { Log $_ }' + #13#10 +
    ''                                                                        + #13#10 +
    'Log "=== Setup concluido com sucesso ==="'                              + #13#10;

  ForceDirectories(AppDir + '\tools');
  DeleteFile(ScriptFile);
  SaveStringToFile(ScriptFile, Content, False);
  Log('[ZapDin] setup_final.ps1 gerado em: ' + ScriptFile);
end;

// ── Hooks de ciclo de vida ────────────────────────────────────────────────────
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    ForceDirectories(ExpandConstant('{app}\logs'));
    ForceDirectories(ExpandConstant('{app}\tools'));
    ForceDirectories(ExpandConstant('{app}\data'));
  end;
  if CurStep = ssPostInstall then
    WriteSetupFinalScript;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  NeedsRestart := False;
  if not IsX64Compatible then
    Result := 'ZapDin requer Windows 64-bit (x64 ou ARM64 compatível).';
end;
