; =============================================================================
;  ZapDin App — Instalador Profissional v5
;  Inno Setup 6.3+
;  Build: GitHub Actions → PyInstaller → Inno Setup
;
;  Fluxo de instalação:
;    1. Coleta: URL do Monitor, Token do cliente, porta
;    2. Detecta/instala PostgreSQL 16 (silencioso se ausente)
;    3. Cria banco zapdin_app
;    4. Grava .env com TODAS as variáveis necessárias
;    5. Registra ZapDinApp + ZapDinWorker no Task Scheduler
;    6. Inicia o app e abre o browser
; =============================================================================

; AppVersion é substituído automaticamente pelo GitHub Actions ao fazer push de tag
#define AppName      "ZapDin App"
#define AppVersion   "1.3.18"
#define AppPublisher "ZapDin Sistemas"
#define AppURL       "https://zapdin.com.br"
#define InstallDir   "C:\ZapDinApp"
#define DBName       "zapdin_app"
#define DefaultPort  "4000"

; =============================================================================
[Setup]
AppId={{B7C2A1D4-3E5F-4A9B-8C6D-1F2E3A4B5C6D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/suporte
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

DefaultDirName={#InstallDir}
DisableDirPage=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

OutputDir=.
OutputBaseFilename=ZapDin-Setup
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

WizardStyle=modern
WizardSizePercent=120
DisableWelcomePage=no
PrivilegesRequired=admin
ShowLanguageDialog=no
LanguageDetectionMethod=none
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763    ; Windows 10 1809 mínimo

; =============================================================================
[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
WelcomeLabel1=Bem-vindo ao instalador do {#AppName} v{#AppVersion}
WelcomeLabel2=Este assistente irá instalar o {#AppName} no seu computador.%n%nO instalador irá configurar automaticamente:%n%n  ✓ ZapDin App (Python embutido, sem instalação extra)%n  ✓ PostgreSQL (detectado ou instalado automaticamente)%n  ✓ Banco de dados zapdin_app%n  ✓ Serviço Windows (inicia automaticamente no login)%n%nRequisitos:%n  • Windows 10 64-bit ou superior%n  • Conexão com a internet (apenas durante instalação)%n  • Mínimo 1 GB de espaço livre%n%nClique em Avançar para continuar.
FinishedLabel=Instalação do {#AppName} concluída com sucesso!%n%nO sistema foi iniciado e abrirá automaticamente no seu navegador.%n%nAcesse: http://localhost:{#DefaultPort}%n%nEm caso de dúvidas, contate o suporte ZapDin.

; =============================================================================
[Files]
; ZapDinApp compilado pelo PyInstaller (toda a pasta dist\ZapDinApp\)
Source: "..\dist\ZapDinApp\*"; DestDir: "{#InstallDir}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

; =============================================================================
[Dirs]
Name: "{#InstallDir}\data";  Permissions: authusers-modify
Name: "{#InstallDir}\logs";  Permissions: authusers-modify

; =============================================================================
[Icons]
Name: "{group}\{#AppName}"; \
  Filename: "{#InstallDir}\ZapDinApp.exe"
Name: "{group}\Abrir ZapDin no Navegador"; \
  Filename: "http://localhost:{#DefaultPort}"
Name: "{group}\Desinstalar {#AppName}"; \
  Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; \
  Filename: "{#InstallDir}\ZapDinApp.exe"; \
  Tasks: desktopicon

; =============================================================================
[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; \
  GroupDescription: "Atalhos:"; Flags: checkedonce

; =============================================================================
[UninstallRun]
; Para os serviços na ordem correta
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Stop-ScheduledTask -TaskName ZapDinWorker -EA SilentlyContinue"""; \
  Flags: runhidden
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Stop-ScheduledTask -TaskName ZapDinApp -EA SilentlyContinue"""; \
  Flags: runhidden
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Unregister-ScheduledTask -TaskName ZapDinWorker -Confirm:$false -EA SilentlyContinue"""; \
  Flags: runhidden; RunOnceId: "RemoveWorkerTask"
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Unregister-ScheduledTask -TaskName ZapDinApp -Confirm:$false -EA SilentlyContinue"""; \
  Flags: runhidden; RunOnceId: "RemoveAppTask"
Filename: "taskkill.exe"; Parameters: "/IM ZapDinApp.exe /F"; Flags: runhidden
Filename: "taskkill.exe"; Parameters: "/IM ZapDinWorker.exe /F"; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{#InstallDir}\data"
Type: filesandordirs; Name: "{#InstallDir}\logs"
Type: files;          Name: "{#InstallDir}\.env"
Type: filesandordirs; Name: "{#InstallDir}"

; =============================================================================
[Code]

// ─────────────────────────────────────────────────────────────────────────────
// VARIÁVEIS GLOBAIS
// ─────────────────────────────────────────────────────────────────────────────
var
  // Páginas
  PageConfig:   TInputQueryWizardPage;  // Monitor URL, Token, Porta
  PagePG:       TInputQueryWizardPage;  // PostgreSQL (se já instalado)
  ProgressPage: TOutputProgressWizardPage;

  // Configuração coletada
  MonitorURL:   String;
  ClientToken:  String;
  AppPort:      String;
  PGHost:       String;
  PGPort:       String;
  PGUser:       String;
  PGPasswd:     String;

  // Estado
  PGAlreadyInstalled: Boolean;

// ─────────────────────────────────────────────────────────────────────────────
// DETECÇÃO DO POSTGRESQL
// ─────────────────────────────────────────────────────────────────────────────

function PostgreSQLInstalled: Boolean;
var
  Versions: TArrayOfString;
  i: Integer;
begin
  Result := False;

  // Método 1: Registro oficial EnterpriseDB
  if RegKeyExists(HKEY_LOCAL_MACHINE, 'SOFTWARE\PostgreSQL\Installations') then
    begin Result := True; Exit; end;
  if RegKeyExists(HKEY_LOCAL_MACHINE, 'SOFTWARE\WOW6432Node\PostgreSQL\Installations') then
    begin Result := True; Exit; end;

  // Método 2: Serviço Windows postgresql-x64-*
  SetArrayLength(Versions, 9);
  Versions[0] := '17'; Versions[1] := '16'; Versions[2] := '15';
  Versions[3] := '14'; Versions[4] := '13'; Versions[5] := '12';
  Versions[6] := '11'; Versions[7] := '10'; Versions[8] := '9.6';
  for i := 0 to GetArrayLength(Versions) - 1 do
  begin
    if RegKeyExists(HKEY_LOCAL_MACHINE,
      'SYSTEM\CurrentControlSet\Services\postgresql-x64-' + Versions[i]) then
      begin Result := True; Exit; end;
  end;
  if RegKeyExists(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Services\postgresql') then
    begin Result := True; Exit; end;

  // Método 3: Arquivos em caminhos padrão + SGAPetro
  for i := 0 to GetArrayLength(Versions) - 1 do
  begin
    if FileExists('C:\Program Files\PostgreSQL\' + Versions[i] + '\bin\psql.exe') then
      begin Result := True; Exit; end;
    if FileExists('C:\PostgreSQL\' + Versions[i] + '\bin\psql.exe') then
      begin Result := True; Exit; end;
  end;
  // SGAPetro (cliente frequente)
  if FileExists('C:\SGAPetro\PostgreSQL\bin\psql.exe') then
    begin Result := True; Exit; end;
  if FileExists('D:\SGAPetro\PostgreSQL\bin\psql.exe') then
    begin Result := True; Exit; end;
end;

function FindPsqlPath: String;
var
  Versions: TArrayOfString;
  i: Integer;
  BasePath, RegBase: String;
begin
  Result := '';

  SetArrayLength(Versions, 9);
  Versions[0] := '17'; Versions[1] := '16'; Versions[2] := '15';
  Versions[3] := '14'; Versions[4] := '13'; Versions[5] := '12';
  Versions[6] := '11'; Versions[7] := '10'; Versions[8] := '9.6';

  // Via registro (mais confiável)
  for i := 0 to GetArrayLength(Versions) - 1 do
  begin
    RegBase := 'SOFTWARE\PostgreSQL\Installations\postgresql-x64-' + Versions[i];
    if RegQueryStringValue(HKEY_LOCAL_MACHINE, RegBase, 'Base Directory', BasePath) then
    begin
      if FileExists(BasePath + '\bin\psql.exe') then
        begin Result := BasePath + '\bin\psql.exe'; Exit; end;
    end;
  end;

  // Caminhos padrão
  for i := 0 to GetArrayLength(Versions) - 1 do
  begin
    if FileExists('C:\Program Files\PostgreSQL\' + Versions[i] + '\bin\psql.exe') then
      begin Result := 'C:\Program Files\PostgreSQL\' + Versions[i] + '\bin\psql.exe'; Exit; end;
    if FileExists('C:\PostgreSQL\' + Versions[i] + '\bin\psql.exe') then
      begin Result := 'C:\PostgreSQL\' + Versions[i] + '\bin\psql.exe'; Exit; end;
  end;

  // SGAPetro
  if FileExists('C:\SGAPetro\PostgreSQL\bin\psql.exe') then
    begin Result := 'C:\SGAPetro\PostgreSQL\bin\psql.exe'; Exit; end;
  if FileExists('D:\SGAPetro\PostgreSQL\bin\psql.exe') then
    begin Result := 'D:\SGAPetro\PostgreSQL\bin\psql.exe'; Exit; end;
end;

// ─────────────────────────────────────────────────────────────────────────────
// UTILITÁRIOS
// ─────────────────────────────────────────────────────────────────────────────

// Executa script PowerShell em arquivo temporário, retorna exit code
function RunPS(Script: String): Integer;
var
  TmpFile: String;
  RC: Integer;
begin
  TmpFile := ExpandConstant('{tmp}\zapdin_step.ps1');
  SaveStringToFile(TmpFile, Script, False);
  Exec(
    'powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -NonInteractive -File "' + TmpFile + '"',
    '', SW_HIDE, ewWaitUntilTerminated, RC
  );
  DeleteFile(TmpFile);
  Result := RC;
end;

// Executa PowerShell inline (comando simples)
function RunPSInline(Cmd: String): Integer;
var RC: Integer;
begin
  Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -NonInteractive -Command "' + Cmd + '"',
    '', SW_HIDE, ewWaitUntilTerminated, RC);
  Result := RC;
end;

// ─────────────────────────────────────────────────────────────────────────────
// CRIAÇÃO DAS PÁGINAS
// ─────────────────────────────────────────────────────────────────────────────

procedure InitializeWizard;
begin
  PGAlreadyInstalled := PostgreSQLInstalled;

  // ── Página 1: Monitor + Token + Porta ────────────────────────────────────
  PageConfig := CreateInputQueryPage(
    wpWelcome,
    'Configuração do ZapDin',
    'Informe os dados fornecidos pela equipe ZapDin para este cliente.',
    ''
  );
  PageConfig.Add('URL do Monitor ZapDin (ex: http://zapdin.empresa.com.br:5000/):', False);
  PageConfig.Add('Token do cliente (obtido no painel Monitor → Clientes):', False);
  PageConfig.Add('Porta do app (padrão: 4000 — altere apenas se solicitado):', False);

  PageConfig.Values[0] := 'http://zapdin.gruposgapetro.com.br:5000/';
  PageConfig.Values[1] := '';
  PageConfig.Values[2] := '{#DefaultPort}';

  // ── Página 2: PostgreSQL (apenas se já instalado) ─────────────────────────
  if PGAlreadyInstalled then
  begin
    PagePG := CreateInputQueryPage(
      PageConfig.ID,
      'Configuração do PostgreSQL',
      'PostgreSQL encontrado neste computador.' + #13#10 +
      'Informe os dados de acesso para criar o banco do ZapDin.',
      ''
    );
    PagePG.Add('Host:', False);
    PagePG.Add('Porta:', False);
    PagePG.Add('Usuário:', False);
    PagePG.Add('Senha do PostgreSQL:', True);
    PagePG.Values[0] := 'localhost';
    PagePG.Values[1] := '5432';
    PagePG.Values[2] := 'postgres';
    PagePG.Values[3] := '';
  end;

  // ── Página de progresso ───────────────────────────────────────────────────
  ProgressPage := CreateOutputProgressPage(
    'Instalando ZapDin App',
    'Por favor, aguarde enquanto o sistema é configurado...'
  );
end;

// ─────────────────────────────────────────────────────────────────────────────
// CONTROLE DE PÁGINAS
// ─────────────────────────────────────────────────────────────────────────────

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  // Pula a página PG se PostgreSQL NÃO está instalado (ela nem foi criada)
  if (not PGAlreadyInstalled) and Assigned(PagePG) and (PageID = PagePG.ID) then
    Result := True;
end;

// ─────────────────────────────────────────────────────────────────────────────
// VALIDAÇÃO AO AVANÇAR
// ─────────────────────────────────────────────────────────────────────────────

function NextButtonClick(CurPageID: Integer): Boolean;
var PortNum: Integer;
begin
  Result := True;

  // ── Valida Página 1 ───────────────────────────────────────────────────────
  if CurPageID = PageConfig.ID then
  begin
    if Trim(PageConfig.Values[0]) = '' then
    begin
      MsgBox('Informe a URL do Monitor.', mbError, MB_OK);
      Result := False; Exit;
    end;
    if Trim(PageConfig.Values[1]) = '' then
    begin
      MsgBox('Informe o Token do cliente.', mbError, MB_OK);
      Result := False; Exit;
    end;
    if Trim(PageConfig.Values[2]) = '' then
    begin
      MsgBox('Informe a porta do app.', mbError, MB_OK);
      Result := False; Exit;
    end;
    PortNum := StrToIntDef(Trim(PageConfig.Values[2]), 0);
    if (PortNum < 1024) or (PortNum > 65535) then
    begin
      MsgBox('Porta inválida. Use um número entre 1024 e 65535 (padrão: 4000).', mbError, MB_OK);
      Result := False; Exit;
    end;

    MonitorURL  := Trim(PageConfig.Values[0]);
    // Garante barra final na URL
    if (Length(MonitorURL) > 0) and (MonitorURL[Length(MonitorURL)] <> '/') then
      MonitorURL := MonitorURL + '/';
    ClientToken := Trim(PageConfig.Values[1]);
    AppPort     := Trim(PageConfig.Values[2]);
  end;

  // ── Valida Página 2 (PostgreSQL) ──────────────────────────────────────────
  if PGAlreadyInstalled and Assigned(PagePG) and (CurPageID = PagePG.ID) then
  begin
    if Trim(PagePG.Values[0]) = '' then
    begin
      MsgBox('Informe o host do PostgreSQL.', mbError, MB_OK);
      Result := False; Exit;
    end;
    PortNum := StrToIntDef(Trim(PagePG.Values[1]), 0);
    if (PortNum < 1) or (PortNum > 65535) then
    begin
      MsgBox('Porta do PostgreSQL inválida. Padrão: 5432.', mbError, MB_OK);
      Result := False; Exit;
    end;
    if Trim(PagePG.Values[2]) = '' then
    begin
      MsgBox('Informe o usuário do PostgreSQL.', mbError, MB_OK);
      Result := False; Exit;
    end;
    PGHost   := Trim(PagePG.Values[0]);
    PGPort   := Trim(PagePG.Values[1]);
    PGUser   := Trim(PagePG.Values[2]);
    PGPasswd := PagePG.Values[3];
  end;
end;

// ─────────────────────────────────────────────────────────────────────────────
// INSTALAÇÃO PRINCIPAL
// ─────────────────────────────────────────────────────────────────────────────

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Script: String;
  TotalSteps, CurrentStep: Integer;
  LogFile: String;
begin
  // Abre o browser ao final
  if CurStep = ssDone then
  begin
    if AppPort = '' then AppPort := '{#DefaultPort}';
    ShellExec('open', 'http://localhost:' + AppPort,
      '', '', SW_SHOW, ewNoWait, ResultCode);
    Exit;
  end;

  if CurStep <> ssPostInstall then Exit;

  LogFile := '{#InstallDir}\logs\install.log';

  if PGAlreadyInstalled then
    TotalSteps := 4
  else
    TotalSteps := 5;

  CurrentStep := 0;
  ProgressPage.Show;
  ProgressPage.SetProgress(0, TotalSteps);

  // ════════════════════════════════════════════════════════════════════════
  // PASSO 1 (opcional): Instalar PostgreSQL se não encontrado
  // ════════════════════════════════════════════════════════════════════════
  if not PGAlreadyInstalled then
  begin
    CurrentStep := CurrentStep + 1;
    ProgressPage.SetText(
      'Passo ' + IntToStr(CurrentStep) + '/' + IntToStr(TotalSteps) +
        ' — Baixando e instalando PostgreSQL 16...',
      'Download de ~200 MB. Pode levar até 10 minutos. Não feche esta janela.'
    );
    Script :=
      'Set-StrictMode -Off' + #13#10 +
      '$logFile = "' + LogFile + '"' + #13#10 +
      'function Log($m) { $ts = Get-Date -f "yyyy-MM-dd HH:mm:ss"; Add-Content $logFile "[$ts] $m"; Write-Host $m }' + #13#10 +
      'New-Item -ItemType Directory -Force -Path "{#InstallDir}\logs" | Out-Null' + #13#10 +
      'Log "=== Instalando PostgreSQL 16 ==="' + #13#10 +
      '$url = "https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64.exe"' + #13#10 +
      '$out = "$env:TEMP\pg_installer.exe"' + #13#10 +
      'Log "Baixando de: $url"' + #13#10 +
      'try {' + #13#10 +
      '  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12' + #13#10 +
      '  Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -ErrorAction Stop' + #13#10 +
      '  Log "Download concluido."' + #13#10 +
      '} catch {' + #13#10 +
      '  Log "ERRO no download: $_"' + #13#10 +
      '  exit 1' + #13#10 +
      '}' + #13#10 +
      'Log "Instalando PostgreSQL (modo silencioso)..."' + #13#10 +
      '$args = "--mode unattended --superpassword zapdin2024! --serverport 5432 --servicename postgresql --serviceaccount NT AUTHORITY\NetworkService"' + #13#10 +
      'Start-Process $out -ArgumentList $args -Wait -ErrorAction Stop' + #13#10 +
      'Remove-Item $out -Force -ErrorAction SilentlyContinue' + #13#10 +
      'Log "PostgreSQL instalado. Aguardando servico iniciar..."' + #13#10 +
      'Start-Sleep 5' + #13#10 +
      '# Inicia o servico PostgreSQL' + #13#10 +
      '$svc = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1' + #13#10 +
      'if ($svc) {' + #13#10 +
      '  if ($svc.Status -ne "Running") { Start-Service $svc.Name -ErrorAction SilentlyContinue; Start-Sleep 3 }' + #13#10 +
      '  Log "Servico PostgreSQL: $($svc.Status)"' + #13#10 +
      '}' + #13#10 +
      'Log "PostgreSQL pronto."';
    RunPS(Script);

    // Define credenciais para os próximos passos
    PGHost   := 'localhost';
    PGPort   := '5432';
    PGUser   := 'postgres';
    PGPasswd := 'zapdin2024!';
    ProgressPage.SetProgress(CurrentStep, TotalSteps);
  end;

  // ════════════════════════════════════════════════════════════════════════
  // PASSO 2: Criar banco de dados
  // ════════════════════════════════════════════════════════════════════════
  CurrentStep := CurrentStep + 1;
  ProgressPage.SetText(
    'Passo ' + IntToStr(CurrentStep) + '/' + IntToStr(TotalSteps) +
      ' — Criando banco de dados ' + '{#DBName}' + '...',
    'Conectando ao PostgreSQL em ' + PGHost + ':' + PGPort + '...'
  );

  Script :=
    'Set-StrictMode -Off' + #13#10 +
    '$logFile = "' + LogFile + '"' + #13#10 +
    'function Log($m) { $ts = Get-Date -f "yyyy-MM-dd HH:mm:ss"; Add-Content $logFile "[$ts] $m"; Write-Host $m }' + #13#10 +
    'New-Item -ItemType Directory -Force -Path "{#InstallDir}\logs" | Out-Null' + #13#10 +
    'Log "=== Configurando banco de dados ==="' + #13#10 +
    '$env:PGPASSWORD    = "' + PGPasswd + '"' + #13#10 +
    '$env:PGCONNECT_TIMEOUT = "15"' + #13#10 +
    '$pgHost = "' + PGHost + '"' + #13#10 +
    '$pgPort = "' + PGPort + '"' + #13#10 +
    '$pgUser = "' + PGUser + '"' + #13#10 +
    '$dbName = "{#DBName}"' + #13#10 +
    '' + #13#10 +
    '# Garante que o servico PostgreSQL esta rodando' + #13#10 +
    '$svc = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Where-Object { $_.Status -ne "Running" } | Select-Object -First 1' + #13#10 +
    'if ($svc) {' + #13#10 +
    '  Log "Iniciando servico $($svc.Name)..."' + #13#10 +
    '  Start-Service $svc.Name -ErrorAction SilentlyContinue' + #13#10 +
    '  Start-Sleep 4' + #13#10 +
    '}' + #13#10 +
    '' + #13#10 +
    '# Localiza psql.exe' + #13#10 +
    '$psql = $null' + #13#10 +
    '# 1) PATH' + #13#10 +
    'try { $psql = (Get-Command psql -ErrorAction Stop).Source } catch {}' + #13#10 +
    '# 2) Registro' + #13#10 +
    'if (-not $psql) {' + #13#10 +
    '  foreach ($v in @("17","16","15","14","13","12","11","10")) {' + #13#10 +
    '    try {' + #13#10 +
    '      $base = (Get-ItemProperty "HKLM:\SOFTWARE\PostgreSQL\Installations\postgresql-x64-$v" -EA Stop)."Base Directory"' + #13#10 +
    '      $p = "$base\bin\psql.exe"' + #13#10 +
    '      if (Test-Path $p) { $psql = $p; break }' + #13#10 +
    '    } catch {}' + #13#10 +
    '  }' + #13#10 +
    '}' + #13#10 +
    '# 3) Caminhos padrão' + #13#10 +
    'if (-not $psql) {' + #13#10 +
    '  foreach ($v in @("17","16","15","14","13","12","11","10")) {' + #13#10 +
    '    $paths = @(' + #13#10 +
    '      "C:\Program Files\PostgreSQL\$v\bin\psql.exe",' + #13#10 +
    '      "C:\PostgreSQL\$v\bin\psql.exe"' + #13#10 +
    '    )' + #13#10 +
    '    foreach ($p in $paths) { if (Test-Path $p) { $psql = $p; break } }' + #13#10 +
    '    if ($psql) { break }' + #13#10 +
    '  }' + #13#10 +
    '}' + #13#10 +
    '# 4) SGAPetro' + #13#10 +
    'if (-not $psql) {' + #13#10 +
    '  foreach ($d in @("C:","D:")) {' + #13#10 +
    '    $p = "$d\SGAPetro\PostgreSQL\bin\psql.exe"' + #13#10 +
    '    if (Test-Path $p) { $psql = $p; break }' + #13#10 +
    '  }' + #13#10 +
    '}' + #13#10 +
    '' + #13#10 +
    'if (-not $psql) {' + #13#10 +
    '  Log "ERRO: psql.exe nao encontrado. PostgreSQL pode nao estar instalado corretamente."' + #13#10 +
    '  exit 1' + #13#10 +
    '}' + #13#10 +
    'Log "psql encontrado: $psql"' + #13#10 +
    '' + #13#10 +
    '# Testa conexao' + #13#10 +
    '$testResult = & $psql -h $pgHost -p $pgPort -U $pgUser -tc "SELECT 1" 2>&1' + #13#10 +
    'if ($LASTEXITCODE -ne 0) {' + #13#10 +
    '  Log "ERRO na conexao com PostgreSQL: $testResult"' + #13#10 +
    '  exit 1' + #13#10 +
    '}' + #13#10 +
    'Log "Conexao OK."' + #13#10 +
    '' + #13#10 +
    '# Cria banco se nao existir' + #13#10 +
    '$exists = & $psql -h $pgHost -p $pgPort -U $pgUser -tc "SELECT 1 FROM pg_database WHERE datname=''$dbName''" 2>$null' + #13#10 +
    'if ($exists -match "1") {' + #13#10 +
    '  Log "Banco $dbName ja existe."' + #13#10 +
    '} else {' + #13#10 +
    '  Log "Criando banco $dbName..."' + #13#10 +
    '  $r = & $psql -h $pgHost -p $pgPort -U $pgUser -c "CREATE DATABASE $dbName ENCODING=''UTF8'' LC_COLLATE=''Portuguese_Brazil.1252'' LC_CTYPE=''Portuguese_Brazil.1252'' TEMPLATE=template0;" 2>&1' + #13#10 +
    '  if ($LASTEXITCODE -eq 0) { Log "Banco $dbName criado com sucesso." }' + #13#10 +
    '  else { Log "AVISO: Falha ao criar banco (pode ja existir): $r" }' + #13#10 +
    '}' + #13#10 +
    'Log "Configuracao do banco concluida."';

  RunPS(Script);
  ProgressPage.SetProgress(CurrentStep, TotalSteps);

  // ════════════════════════════════════════════════════════════════════════
  // PASSO 3: Gerar .env
  // ════════════════════════════════════════════════════════════════════════
  CurrentStep := CurrentStep + 1;
  ProgressPage.SetText(
    'Passo ' + IntToStr(CurrentStep) + '/' + IntToStr(TotalSteps) +
      ' — Configurando sistema...',
    'Gerando configuração e validando token...'
  );

  Script :=
    'Set-StrictMode -Off' + #13#10 +
    '$logFile = "' + LogFile + '"' + #13#10 +
    'function Log($m) { $ts = Get-Date -f "yyyy-MM-dd HH:mm:ss"; Add-Content $logFile "[$ts] $m"; Write-Host $m }' + #13#10 +
    'Log "=== Gerando .env ==="' + #13#10 +
    '' + #13#10 +
    '# URL-encode seguro via .NET (trata @, #, $, !, +, espaços, etc.)' + #13#10 +
    '$pgPass   = "' + PGPasswd + '"' + #13#10 +
    '$passEnc  = [System.Uri]::EscapeDataString($pgPass)' + #13#10 +
    '$dbUrl    = "postgresql://' + PGUser + ':$passEnc@' + PGHost + ':' + PGPort + '/{#DBName}?sslmode=disable"' + #13#10 +
    '' + #13#10 +
    '# Gera SECRET_KEY aleatória (64 chars alfanuméricos)' + #13#10 +
    '$chars    = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"' + #13#10 +
    '$rng      = New-Object System.Security.Cryptography.RNGCryptoServiceProvider' + #13#10 +
    '$secretKey = ""' + #13#10 +
    'for ($i = 0; $i -lt 64; $i++) {' + #13#10 +
    '  $b = [byte[]]::new(1)' + #13#10 +
    '  $rng.GetBytes($b)' + #13#10 +
    '  $secretKey += $chars[$b[0] % $chars.Length]' + #13#10 +
    '}' + #13#10 +
    '' + #13#10 +
    '# Gera ERP_TOKEN aleatório (32 chars)' + #13#10 +
    '$erpToken = ""' + #13#10 +
    'for ($i = 0; $i -lt 32; $i++) {' + #13#10 +
    '  $b = [byte[]]::new(1)' + #13#10 +
    '  $rng.GetBytes($b)' + #13#10 +
    '  $erpToken += $chars[$b[0] % $chars.Length]' + #13#10 +
    '}' + #13#10 +
    '' + #13#10 +
    '# Busca nome do cliente no Monitor' + #13#10 +
    '$clientName = ""' + #13#10 +
    'try {' + #13#10 +
    '  $apiUrl = "' + MonitorURL + 'api/activate/client-info?token=' + ClientToken + '"' + #13#10 +
    '  Log "Buscando dados do cliente em: $apiUrl"' + #13#10 +
    '  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12' + #13#10 +
    '  $r = Invoke-RestMethod -Uri $apiUrl -Method GET -TimeoutSec 10 -ErrorAction Stop' + #13#10 +
    '  if ($r.nome) { $clientName = $r.nome; Log "Cliente: $clientName" }' + #13#10 +
    '} catch { Log "Aviso: Monitor indisponivel. Nome do cliente sera configurado apos ativacao." }' + #13#10 +
    '' + #13#10 +
    '# Grava .env sem BOM (UTF8NoBOM) — pydantic-settings requer isso' + #13#10 +
    '$envPath  = "{#InstallDir}\.env"' + #13#10 +
    '$port     = "' + AppPort + '"' + #13#10 +
    '$lines = @(' + #13#10 +
    '  "# ZapDin App — gerado pelo instalador v{#AppVersion}",' + #13#10 +
    '  "APP_STATE=active",' + #13#10 +
    '  "PORT=$port",' + #13#10 +
    '  "DATABASE_URL=$dbUrl",' + #13#10 +
    '  "SECRET_KEY=$secretKey",' + #13#10 +
    '  "MONITOR_URL=' + MonitorURL + '",' + #13#10 +
    '  "MONITOR_CLIENT_TOKEN=' + ClientToken + '",' + #13#10 +
    '  "CLIENT_NAME=$clientName",' + #13#10 +
    '  "CLIENT_CNPJ=",' + #13#10 +
    '  "ERP_TOKEN=$erpToken",' + #13#10 +
    '  "SERVICE_NAME=ZapDinApp",' + #13#10 +
    '  "PUBLIC_URL=http://localhost:$port",' + #13#10 +
    '  "WA_BACKEND=evolution",' + #13#10 +
    '  "EVOLUTION_URL=http://localhost:8080",' + #13#10 +
    '  "EVOLUTION_API_KEY=zapdin-evo-2024",' + #13#10 +
    '  "DISPATCH_MIN_DELAY=1.0",' + #13#10 +
    '  "DISPATCH_MAX_DELAY=4.0",' + #13#10 +
    '  "COOKIE_SECURE=false"' + #13#10 +
    ')' + #13#10 +
    '$utf8NoBom = New-Object System.Text.UTF8Encoding $false' + #13#10 +
    '[System.IO.File]::WriteAllLines($envPath, $lines, $utf8NoBom)' + #13#10 +
    'Log ".env gravado em: $envPath"' + #13#10 +
    'Log "PORT=$port | DB=' + DBName + ' | WA=evolution"';

  RunPS(Script);
  ProgressPage.SetProgress(CurrentStep, TotalSteps);

  // ════════════════════════════════════════════════════════════════════════
  // PASSO 4: Registrar Tasks no Agendador
  // ════════════════════════════════════════════════════════════════════════
  CurrentStep := CurrentStep + 1;
  ProgressPage.SetText(
    'Passo ' + IntToStr(CurrentStep) + '/' + IntToStr(TotalSteps) +
      ' — Configurando inicialização automática...',
    'Registrando ZapDinApp e ZapDinWorker no Agendador de Tarefas...'
  );

  Script :=
    'Set-StrictMode -Off' + #13#10 +
    '$logFile = "' + LogFile + '"' + #13#10 +
    'function Log($m) { $ts = Get-Date -f "yyyy-MM-dd HH:mm:ss"; Add-Content $logFile "[$ts] $m"; Write-Host $m }' + #13#10 +
    'Log "=== Registrando tarefas agendadas ==="' + #13#10 +
    '' + #13#10 +
    '# Mata processos na porta para evitar conflito' + #13#10 +
    'try {' + #13#10 +
    '  $port = ' + AppPort + #13#10 +
    '  $conns = Get-NetTCPConnection -LocalPort $port -State Listen -EA SilentlyContinue' + #13#10 +
    '  if ($conns) {' + #13#10 +
    '    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique' + #13#10 +
    '    foreach ($p in $pids) { Stop-Process -Id $p -Force -EA SilentlyContinue }' + #13#10 +
    '    Start-Sleep 2' + #13#10 +
    '    Log "Processos na porta $port encerrados."' + #13#10 +
    '  }' + #13#10 +
    '} catch { Log "Aviso: nao foi possivel verificar porta $port" }' + #13#10 +
    '' + #13#10 +
    '# Remove tasks antigas' + #13#10 +
    'Unregister-ScheduledTask -TaskName "ZapDinApp"    -Confirm:$false -EA SilentlyContinue' + #13#10 +
    'Unregister-ScheduledTask -TaskName "ZapDinWorker" -Confirm:$false -EA SilentlyContinue' + #13#10 +
    'Start-Sleep 1' + #13#10 +
    '' + #13#10 +
    '# Usuario atual' + #13#10 +
    '$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name' + #13#10 +
    'Log "Usuario para as tasks: $user"' + #13#10 +
    '' + #13#10 +
    '# ── ZapDinApp: AtLogon, InteractiveToken (precisa de sessao para Playwright) ──' + #13#10 +
    '$action   = New-ScheduledTaskAction -Execute "{#InstallDir}\ZapDinApp.exe" -WorkingDirectory "{#InstallDir}"' + #13#10 +
    '$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $user' + #13#10 +
    '$settings = New-ScheduledTaskSettingsSet `' + #13#10 +
    '  -ExecutionTimeLimit ([TimeSpan]::Zero) `' + #13#10 +
    '  -RestartCount 5 `' + #13#10 +
    '  -RestartInterval (New-TimeSpan -Minutes 1) `' + #13#10 +
    '  -MultipleInstances IgnoreNew `' + #13#10 +
    '  -StartWhenAvailable $true' + #13#10 +
    '$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest' + #13#10 +
    'try {' + #13#10 +
    '  Register-ScheduledTask -TaskName "ZapDinApp" `' + #13#10 +
    '    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `' + #13#10 +
    '    -Description "ZapDin App v{#AppVersion} — servidor HTTP" `' + #13#10 +
    '    -Force | Out-Null' + #13#10 +
    '  Log "ZapDinApp registrado (InteractiveToken / AtLogon)."' + #13#10 +
    '} catch { Log "ERRO ao registrar ZapDinApp: $_" }' + #13#10 +
    '' + #13#10 +
    '# ── ZapDinWorker: AtLogon +30s delay, S4U ──────────────────────────────' + #13#10 +
    '$workerExe = "{#InstallDir}\ZapDinWorker.exe"' + #13#10 +
    'if (Test-Path $workerExe) {' + #13#10 +
    '  $actionW   = New-ScheduledTaskAction -Execute $workerExe -WorkingDirectory "{#InstallDir}"' + #13#10 +
    '  $triggerW  = New-ScheduledTaskTrigger -AtLogOn -User $user' + #13#10 +
    '  $triggerW.Delay = "PT30S"' + #13#10 +
    '  $settingsW = New-ScheduledTaskSettingsSet `' + #13#10 +
    '    -ExecutionTimeLimit ([TimeSpan]::Zero) `' + #13#10 +
    '    -RestartCount 5 `' + #13#10 +
    '    -RestartInterval (New-TimeSpan -Minutes 2) `' + #13#10 +
    '    -MultipleInstances IgnoreNew `' + #13#10 +
    '    -StartWhenAvailable $true' + #13#10 +
    '  $principalW = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest' + #13#10 +
    '  try {' + #13#10 +
    '    Register-ScheduledTask -TaskName "ZapDinWorker" `' + #13#10 +
    '      -Action $actionW -Trigger $triggerW -Settings $settingsW -Principal $principalW `' + #13#10 +
    '      -Description "ZapDin Worker v{#AppVersion} — fila de envios" `' + #13#10 +
    '      -Force | Out-Null' + #13#10 +
    '    Log "ZapDinWorker registrado (AtLogon +30s)."' + #13#10 +
    '  } catch { Log "ERRO ao registrar ZapDinWorker: $_" }' + #13#10 +
    '} else {' + #13#10 +
    '  Log "AVISO: ZapDinWorker.exe nao encontrado em $workerExe — task nao registrada."' + #13#10 +
    '}' + #13#10 +
    '' + #13#10 +
    'Log "Tasks registradas com sucesso."';

  RunPS(Script);
  ProgressPage.SetProgress(CurrentStep, TotalSteps);

  // ════════════════════════════════════════════════════════════════════════
  // PASSO 5: Iniciar app e verificar
  // ════════════════════════════════════════════════════════════════════════
  CurrentStep := CurrentStep + 1;
  ProgressPage.SetText(
    'Passo ' + IntToStr(CurrentStep) + '/' + IntToStr(TotalSteps) +
      ' — Iniciando ZapDin App...',
    'Aguardando o sistema ficar online (até 30 segundos)...'
  );

  Script :=
    'Set-StrictMode -Off' + #13#10 +
    '$logFile = "' + LogFile + '"' + #13#10 +
    'function Log($m) { $ts = Get-Date -f "yyyy-MM-dd HH:mm:ss"; Add-Content $logFile "[$ts] $m"; Write-Host $m }' + #13#10 +
    'Log "=== Iniciando ZapDin App ==="' + #13#10 +
    '' + #13#10 +
    '# Inicia as tasks' + #13#10 +
    'Start-ScheduledTask -TaskName "ZapDinApp" -ErrorAction SilentlyContinue' + #13#10 +
    'Start-Sleep 5' + #13#10 +
    '' + #13#10 +
    '# Aguarda o app responder na porta' + #13#10 +
    '$port   = ' + AppPort + #13#10 +
    '$url    = "http://127.0.0.1:$port/api/activate/status"' + #13#10 +
    '$online = $false' + #13#10 +
    'for ($i = 0; $i -lt 30; $i++) {' + #13#10 +
    '  try {' + #13#10 +
    '    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 -EA Stop' + #13#10 +
    '    $online = $true' + #13#10 +
    '    Log "ZapDin App online na tentativa $($i+1)."' + #13#10 +
    '    break' + #13#10 +
    '  } catch { Start-Sleep 1 }' + #13#10 +
    '}' + #13#10 +
    '' + #13#10 +
    'if ($online) {' + #13#10 +
    '  Log "Sistema iniciado com sucesso na porta $port."' + #13#10 +
    '} else {' + #13#10 +
    '  Log "AVISO: App nao respondeu em 30s. Verifique {#InstallDir}\logs\"' + #13#10 +
    '}' + #13#10 +
    '' + #13#10 +
    '# Resume erros do log de instalacao' + #13#10 +
    '$erros = @()' + #13#10 +
    'if (Test-Path $logFile) {' + #13#10 +
    '  $erros = Get-Content $logFile | Where-Object { $_ -match " ERRO " }' + #13#10 +
    '}' + #13#10 +
    'if ($erros.Count -gt 0) {' + #13#10 +
    '  Add-Type -AssemblyName System.Windows.Forms' + #13#10 +
    '  $msg = "Instalacao concluida com erros:`n`n"' + #13#10 +
    '  $erros | Select-Object -First 5 | ForEach-Object { $msg += "• $_`n" }' + #13#10 +
    '  $msg += "`nLog completo: {#InstallDir}\logs\install.log"' + #13#10 +
    '  [System.Windows.Forms.MessageBox]::Show($msg, "ZapDin — Aviso", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)' + #13#10 +
    '} else {' + #13#10 +
    '  Log "=== Instalacao concluida sem erros ==="' + #13#10 +
    '}';

  RunPS(Script);
  ProgressPage.SetProgress(TotalSteps, TotalSteps);
  ProgressPage.Hide;
end;


// ─────────────────────────────────────────────────────────────────────────────
// PRÉ-REQUISITOS
// ─────────────────────────────────────────────────────────────────────────────
function PrepareToInstall(var NeedsRestart: Boolean): String;
var RC: Integer;
begin
  Result := '';
  NeedsRestart := False;

  // Windows 64-bit obrigatório
  if not IsX64Compatible then
  begin
    Result := 'ZapDin requer Windows 64-bit (x64 ou ARM64 compatível).' + #13#10 +
              'Este computador não é compatível.';
    Exit;
  end;

  // Mínimo 500 MB livres
  Exec('powershell.exe',
    '-NoProfile -Command "if ((Get-PSDrive C -EA SilentlyContinue).Free -lt 524288000) { exit 1 } else { exit 0 }"',
    '', SW_HIDE, ewWaitUntilTerminated, RC);
  if RC <> 0 then
  begin
    Result := 'Espaço insuficiente em C:.' + #13#10 +
              'ZapDin requer pelo menos 500 MB livres.' + #13#10 +
              'Libere espaço e tente novamente.';
    Exit;
  end;

  // PowerShell 5.1+ (verificação básica)
  Exec('powershell.exe',
    '-NoProfile -Command "if ($PSVersionTable.PSVersion.Major -lt 5) { exit 1 } else { exit 0 }"',
    '', SW_HIDE, ewWaitUntilTerminated, RC);
  if RC <> 0 then
  begin
    Result := 'PowerShell 5.1 ou superior é necessário.' + #13#10 +
              'Instale via Windows Update e tente novamente.';
    Exit;
  end;
end;
