; ============================================================
;  ZapDin App — Setup Installer
;  Compilar com: Inno Setup 6 (https://jrsoftware.org/isinfo.php)
;  Gera: ZapDin-Setup.exe
; ============================================================

#define AppName      "ZapDin App"
#define AppVersion   "1.0"
#define AppPublisher "ZapDin"
#define AppURL       "https://github.com/cristianoradin/zapdinapp"
#define InstallDir   "C:\ZapDinApp"
#define PGVersion    "16"
#define PGPass       "zapdin2024"
#define DBName       "zapdin_app"

[Setup]
AppId={{B7C2A1D4-3E5F-4A9B-8C6D-1F2E3A4B5C6D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={#InstallDir}
DisableDirPage=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=ZapDin-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=120
DisableWelcomePage=no
LicenseFile=
PrivilegesRequired=admin
ShowLanguageDialog=no
LanguageDetectionMethod=none

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
WelcomeLabel1=Bem-vindo ao instalador do {#AppName}
WelcomeLabel2=Este assistente irá instalar o {#AppName} no seu computador.%n%nO instalador irá configurar automaticamente:%n%n  • Python 3.12%n  • PostgreSQL 16%n  • Git%n  • ZapDin App%n%nClique em Avançar para continuar.
FinishedLabel=A instalação do {#AppName} foi concluída com sucesso.%n%nO sistema será iniciado automaticamente como serviço Windows.%n%nAcesse: http://localhost:4000

[Files]
; Nenhum arquivo local — tudo baixado durante a instalação

[Icons]
Name: "{group}\ZapDin App"; Filename: "http://localhost:4000"
Name: "{group}\Desinstalar ZapDin App"; Filename: "{uninstallexe}"
Name: "{commondesktop}\ZapDin App"; Filename: "{#InstallDir}\INICIAR.bat"; WorkingDir: "{#InstallDir}"

[UninstallRun]
Filename: "{#InstallDir}\nssm.exe"; Parameters: "stop ZapDinApp"; Flags: runhidden
Filename: "{#InstallDir}\nssm.exe"; Parameters: "remove ZapDinApp confirm"; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{#InstallDir}"

[Code]

// ── Variáveis globais ──────────────────────────────────────────────────────────
var
  PageConfig: TInputQueryWizardPage;
  PageProgress: TOutputProgressWizardPage;
  MonitorURL: String;
  ClientToken: String;
  ClientName: String;

// ── Cria páginas customizadas ─────────────────────────────────────────────────
procedure InitializeWizard;
begin
  // Página de configuração
  PageConfig := CreateInputQueryPage(
    wpWelcome,
    'Configuração do Sistema',
    'Informe os dados de conexão com o Monitor ZapDin.',
    ''
  );
  PageConfig.Add('URL do Monitor:', False);
  PageConfig.Add('Token do cliente (gerado no painel Monitor):', False);

  // Valores padrão
  PageConfig.Values[0] := 'http://zapdin.gruposgapetro.com.br:5000/';
  PageConfig.Values[1] := '';
end;

// ── Valida campos obrigatórios ────────────────────────────────────────────────
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = PageConfig.ID then
  begin
    if Trim(PageConfig.Values[0]) = '' then
    begin
      MsgBox('Por favor, informe a URL do Monitor.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if Trim(PageConfig.Values[1]) = '' then
    begin
      MsgBox('Por favor, informe o Token do cliente.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    MonitorURL  := Trim(PageConfig.Values[0]);
    ClientToken := Trim(PageConfig.Values[1]);
  end;
end;

// ── Executa comando PowerShell ────────────────────────────────────────────────
function RunPS(Script: String): Integer;
var
  TmpFile: String;
  ResultCode: Integer;
begin
  TmpFile := ExpandConstant('{tmp}\zapdin_step.ps1');
  SaveStringToFile(TmpFile, Script, False);
  Exec(
    'powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -File "' + TmpFile + '"',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
  Result := ResultCode;
  DeleteFile(TmpFile);
end;

// ── Verifica se Python está instalado ────────────────────────────────────────
function PythonInstalled: Boolean;
var
  ResultCode: Integer;
begin
  Exec('python', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
end;

// ── Verifica se Git está instalado ───────────────────────────────────────────
function GitInstalled: Boolean;
var
  ResultCode: Integer;
begin
  Exec('git', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
end;

// ── Verifica se PostgreSQL está instalado ─────────────────────────────────────
function PostgreSQLInstalled: Boolean;
begin
  Result := FileExists('C:\Program Files\PostgreSQL\' + '{#PGVersion}' + '\bin\psql.exe');
end;

// ── Instalação principal ──────────────────────────────────────────────────────
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Script: String;
begin
  if CurStep = ssInstall then
  begin

    // ── PASSO 1: Python ───────────────────────────────────────────────────────
    WizardForm.StatusLabel.Caption := 'Verificando Python...';
    if not PythonInstalled then
    begin
      WizardForm.StatusLabel.Caption := 'Baixando e instalando Python 3.12...';
      Script :=
        '$url = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe"' + #13#10 +
        '$out = "$env:TEMP\python_installer.exe"' + #13#10 +
        'Invoke-WebRequest -Uri $url -OutFile $out' + #13#10 +
        'Start-Process $out -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait' + #13#10 +
        'Remove-Item $out -Force';
      RunPS(Script);
    end;

    // ── PASSO 2: Git ──────────────────────────────────────────────────────────
    WizardForm.StatusLabel.Caption := 'Verificando Git...';
    if not GitInstalled then
    begin
      WizardForm.StatusLabel.Caption := 'Baixando e instalando Git...';
      Script :=
        '$url = "https://github.com/git-for-windows/git/releases/download/v2.47.0.windows.2/Git-2.47.0.2-64-bit.exe"' + #13#10 +
        '$out = "$env:TEMP\git_installer.exe"' + #13#10 +
        'Invoke-WebRequest -Uri $url -OutFile $out' + #13#10 +
        'Start-Process $out -ArgumentList "/VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /COMPONENTS=icons,ext\reg\shellhere,assoc,assoc_sh" -Wait' + #13#10 +
        'Remove-Item $out -Force';
      RunPS(Script);
    end;

    // ── PASSO 3: PostgreSQL ───────────────────────────────────────────────────
    WizardForm.StatusLabel.Caption := 'Verificando PostgreSQL...';
    if not PostgreSQLInstalled then
    begin
      WizardForm.StatusLabel.Caption := 'Baixando PostgreSQL 16 (aguarde, arquivo grande)...';
      Script :=
        '$url = "https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64.exe"' + #13#10 +
        '$out = "$env:TEMP\pg_installer.exe"' + #13#10 +
        'Invoke-WebRequest -Uri $url -OutFile $out' + #13#10 +
        'Start-Process $out -ArgumentList "--mode unattended --superpassword {#PGPass} --serverport 5432" -Wait' + #13#10 +
        'Remove-Item $out -Force';
      RunPS(Script);
    end;

    // ── PASSO 4: Cria banco ───────────────────────────────────────────────────
    WizardForm.StatusLabel.Caption := 'Criando banco de dados...';
    Script :=
      '$env:PGPASSWORD = "{#PGPass}"' + #13#10 +
      '$psql = "C:\Program Files\PostgreSQL\{#PGVersion}\bin\psql.exe"' + #13#10 +
      '$exists = & $psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname=''{#DBName}''"' + #13#10 +
      'if ($exists -notmatch "1") {' + #13#10 +
      '  & $psql -U postgres -c "CREATE DATABASE {#DBName};"' + #13#10 +
      '}';
    RunPS(Script);

    // ── PASSO 5: Clona repositório ────────────────────────────────────────────
    WizardForm.StatusLabel.Caption := 'Baixando ZapDin App...';
    Script :=
      'if (Test-Path "C:\ZapDinApp\.git") {' + #13#10 +
      '  cd C:\ZapDinApp; git pull origin main' + #13#10 +
      '} else {' + #13#10 +
      '  git clone https://github.com/cristianoradin/zapdinapp.git C:\ZapDinApp' + #13#10 +
      '}';
    RunPS(Script);

    // ── PASSO 6: Cria venv ────────────────────────────────────────────────────
    WizardForm.StatusLabel.Caption := 'Criando ambiente Python...';
    Script :=
      'if (-not (Test-Path "C:\ZapDinApp\.venv")) {' + #13#10 +
      '  python -m venv C:\ZapDinApp\.venv' + #13#10 +
      '}';
    RunPS(Script);

    // ── PASSO 7: Instala dependências ─────────────────────────────────────────
    WizardForm.StatusLabel.Caption := 'Instalando dependências Python...';
    Script :=
      'C:\ZapDinApp\.venv\Scripts\python -m pip install --upgrade pip -q' + #13#10 +
      'C:\ZapDinApp\.venv\Scripts\python -m pip install -r C:\ZapDinApp\requirements.txt -q';
    RunPS(Script);

    // ── PASSO 8: Playwright ───────────────────────────────────────────────────
    WizardForm.StatusLabel.Caption := 'Instalando navegador WhatsApp (Chromium)...';
    Script := 'C:\ZapDinApp\.venv\Scripts\python -m playwright install chromium';
    RunPS(Script);

    // ── PASSO 9: Pasta data ───────────────────────────────────────────────────
    ForceDirectories('C:\ZapDinApp\data');

    // ── PASSO 10: Busca nome + gera .env via PowerShell ──────────────────────
    WizardForm.StatusLabel.Caption := 'Validando token e configurando sistema...';
    if not FileExists('C:\ZapDinApp\.env') then
    begin
      // PowerShell busca o nome pelo token e grava o .env diretamente
      Script :=
        '$clientName = "Posto ZapDin"' + #13#10 +
        'try {' + #13#10 +
        '  $r = Invoke-RestMethod -Uri "' + MonitorURL + 'api/activate/client-info?token=' + ClientToken + '" -Method GET -ErrorAction Stop' + #13#10 +
        '  if ($r.nome) { $clientName = $r.nome }' + #13#10 +
        '} catch {}' + #13#10 +
        '$key = -join ((65..90)+(97..122)+(48..57) | Get-Random -Count 64 | ForEach-Object {[char]$_})' + #13#10 +
        '$lines = @(' + #13#10 +
        '  "APP_STATE=locked",' + #13#10 +
        '  "PORT=4000",' + #13#10 +
        '  "DATABASE_URL=postgresql://postgres:{#PGPass}@localhost/{#DBName}",' + #13#10 +
        '  "SECRET_KEY=$key",' + #13#10 +
        '  "MONITOR_URL=' + MonitorURL + '",' + #13#10 +
        '  "MONITOR_CLIENT_TOKEN=' + ClientToken + '",' + #13#10 +
        '  "CLIENT_NAME=$clientName",' + #13#10 +
        '  "CLIENT_CNPJ=",' + #13#10 +
        '  "ERP_TOKEN="' + #13#10 +
        ')' + #13#10 +
        '$lines | Out-File "C:\ZapDinApp\.env" -Encoding UTF8';
      RunPS(Script);
    end;

    // ── PASSO 11: NSSM + Serviço ──────────────────────────────────────────────
    WizardForm.StatusLabel.Caption := 'Instalando serviço Windows...';
    Script :=
      '# Baixa NSSM' + #13#10 +
      'if (-not (Test-Path "C:\ZapDinApp\nssm.exe")) {' + #13#10 +
      '  Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "$env:TEMP\nssm.zip"' + #13#10 +
      '  Expand-Archive "$env:TEMP\nssm.zip" -DestinationPath "$env:TEMP\nssm_tmp" -Force' + #13#10 +
      '  Copy-Item "$env:TEMP\nssm_tmp\nssm-2.24\win64\nssm.exe" "C:\ZapDinApp\nssm.exe"' + #13#10 +
      '  Remove-Item "$env:TEMP\nssm_tmp" -Recurse -Force' + #13#10 +
      '  Remove-Item "$env:TEMP\nssm.zip" -Force' + #13#10 +
      '}' + #13#10 +
      '# Remove servico antigo' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" stop ZapDinApp 2>$null' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" remove ZapDinApp confirm 2>$null' + #13#10 +
      'Start-Sleep 2' + #13#10 +
      '# Instala servico' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" install ZapDinApp "C:\ZapDinApp\.venv\Scripts\python.exe" "-m uvicorn main:app --host 0.0.0.0 --port 4000"' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppDirectory "C:\ZapDinApp"' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp DisplayName "ZapDin App"' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp Start SERVICE_AUTO_START' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppStdout "C:\ZapDinApp\data\zapdin.log"' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppStderr "C:\ZapDinApp\data\zapdin.log"' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" start ZapDinApp';
    RunPS(Script);

  end;

  if CurStep = ssDone then
  begin
    // Abre o browser ao final
    ShellExec('open', 'http://localhost:4000', '', '', SW_SHOW, ewNoWait, ResultCode);
  end;
end;
