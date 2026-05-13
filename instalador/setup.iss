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
WelcomeLabel2=Este assistente irá instalar o {#AppName} no seu computador.%n%nO instalador irá configurar automaticamente:%n%n  • ZapDin App (Python embutido)%n  • PostgreSQL (instalado ou existente)%n  • Serviço Windows (auto-start)%n%nClique em Avançar para continuar.
FinishedLabel=A instalação do {#AppName} foi concluída com sucesso.%n%nO sistema será iniciado automaticamente como serviço Windows.%n%nAcesse: http://localhost:4000

[Files]
; ZapDinApp compilado pelo PyInstaller (gerado pelo GitHub Actions antes do Inno Setup)
Source: "..\dist\ZapDinApp\*"; DestDir: "{#InstallDir}"; Flags: ignoreversion recursesubdirs createallsubdirs

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
  PagePG: TInputQueryWizardPage;
  ProgressPage: TOutputProgressWizardPage;
  MonitorURL: String;
  ClientToken: String;
  PGHost: String;
  PGPort: String;
  PGUser: String;
  PGPasswd: String;
  PGAlreadyInstalled: Boolean;

// ── Detecta PostgreSQL por 3 métodos independentes ────────────────────────────
function PostgreSQLInstalled: Boolean;
var
  Versions: TArrayOfString;
  i: Integer;
begin
  Result := False;

  // ── Método 1: Registro do Windows (EnterpriseDB / instalador oficial) ────────
  // Qualquer versão instalada pelo instalador oficial registra aqui
  if RegKeyExists(HKEY_LOCAL_MACHINE, 'SOFTWARE\PostgreSQL\Installations') then
  begin
    Result := True;
    Exit;
  end;
  if RegKeyExists(HKEY_LOCAL_MACHINE, 'SOFTWARE\WOW6432Node\PostgreSQL\Installations') then
  begin
    Result := True;
    Exit;
  end;

  // ── Método 2: Serviço Windows com prefixo "postgresql" ───────────────────────
  // EnterpriseDB cria "postgresql-x64-16", "postgresql-x64-15", etc.
  SetArrayLength(Versions, 9);
  Versions[0] := '17'; Versions[1] := '16'; Versions[2] := '15';
  Versions[3] := '14'; Versions[4] := '13'; Versions[5] := '12';
  Versions[6] := '11'; Versions[7] := '10'; Versions[8] := '9.6';
  for i := 0 to GetArrayLength(Versions) - 1 do
  begin
    if RegKeyExists(HKEY_LOCAL_MACHINE,
      'SYSTEM\CurrentControlSet\Services\postgresql-x64-' + Versions[i]) then
    begin
      Result := True;
      Exit;
    end;
  end;
  // Serviço genérico "postgresql" (alguns instaladores usam esse nome)
  if RegKeyExists(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Services\postgresql') then
  begin
    Result := True;
    Exit;
  end;

  // ── Método 3: Arquivo psql.exe em caminhos padrão ────────────────────────────
  for i := 0 to GetArrayLength(Versions) - 1 do
  begin
    if FileExists('C:\Program Files\PostgreSQL\' + Versions[i] + '\bin\psql.exe') then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

// ── Encontra o psql.exe (qualquer versão instalada) ───────────────────────────
function FindPsql: String;
var
  Versions: TArrayOfString;
  i: Integer;
  Path: String;
  RegBase: String;
begin
  Result := '';

  // Primeiro tenta ler o caminho direto do registro (mais confiável)
  SetArrayLength(Versions, 9);
  Versions[0] := '17'; Versions[1] := '16'; Versions[2] := '15';
  Versions[3] := '14'; Versions[4] := '13'; Versions[5] := '12';
  Versions[6] := '11'; Versions[7] := '10'; Versions[8] := '9.6';

  for i := 0 to GetArrayLength(Versions) - 1 do
  begin
    RegBase := 'SOFTWARE\PostgreSQL\Installations\postgresql-x64-' + Versions[i];
    if RegQueryStringValue(HKEY_LOCAL_MACHINE, RegBase, 'Base Directory', Path) then
    begin
      Path := Path + '\bin\psql.exe';
      if FileExists(Path) then
      begin
        Result := Path;
        Exit;
      end;
    end;
  end;

  // Fallback: caminhos padrão
  for i := 0 to GetArrayLength(Versions) - 1 do
  begin
    Path := 'C:\Program Files\PostgreSQL\' + Versions[i] + '\bin\psql.exe';
    if FileExists(Path) then
    begin
      Result := Path;
      Exit;
    end;
  end;
end;

// ── Cria páginas customizadas ─────────────────────────────────────────────────
procedure InitializeWizard;
begin
  PGAlreadyInstalled := PostgreSQLInstalled;

  // ── Página 1: Monitor + Token ──────────────────────────────────────────────
  PageConfig := CreateInputQueryPage(
    wpWelcome,
    'Configuração do Sistema',
    'Informe os dados de conexão com o Monitor ZapDin.',
    ''
  );
  PageConfig.Add('URL do Monitor:', False);
  PageConfig.Add('Token do cliente (gerado no painel Monitor):', False);
  PageConfig.Values[0] := 'http://zapdin.gruposgapetro.com.br:5000/';
  PageConfig.Values[1] := '';

  // ── Página 2: PostgreSQL existente (mostrada apenas se já instalado) ───────
  if PGAlreadyInstalled then
  begin
    PagePG := CreateInputQueryPage(
      PageConfig.ID,
      'Configuração do PostgreSQL',
      'PostgreSQL já está instalado neste computador.' + #13#10 +
      'Informe os dados de conexão para criar o banco de dados do ZapDin.',
      ''
    );
    PagePG.Add('Host:', False);
    PagePG.Add('Porta:', False);
    PagePG.Add('Usuário:', False);
    PagePG.Add('Senha:', True);   // True = campo senha (mascarado)
    PagePG.Values[0] := 'localhost';
    PagePG.Values[1] := '5432';
    PagePG.Values[2] := 'postgres';
    PagePG.Values[3] := '';
  end;

  // ── Página de progresso (exibida durante os passos pós-instalação) ──────────
  ProgressPage := CreateOutputProgressPage(
    'Configurando ZapDin App',
    'Por favor aguarde. Este processo pode levar alguns minutos...'
  );
end;

// ── Oculta página PG se PostgreSQL NÃO estiver instalado ─────────────────────
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PGAlreadyInstalled and (PageID = PagePG.ID) then
    Result := False   // mostra a página
  else if (not PGAlreadyInstalled) and Assigned(PagePG) and (PageID = PagePG.ID) then
    Result := True;   // nunca chega aqui pois PagePG não é criado
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

  if PGAlreadyInstalled and (CurPageID = PagePG.ID) then
  begin
    if Trim(PagePG.Values[0]) = '' then
    begin
      MsgBox('Por favor, informe o Host do PostgreSQL.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if Trim(PagePG.Values[1]) = '' then
    begin
      MsgBox('Por favor, informe a Porta do PostgreSQL.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if Trim(PagePG.Values[2]) = '' then
    begin
      MsgBox('Por favor, informe o Usuário do PostgreSQL.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    PGHost   := Trim(PagePG.Values[0]);
    PGPort   := Trim(PagePG.Values[1]);
    PGUser   := Trim(PagePG.Values[2]);
    PGPasswd := Trim(PagePG.Values[3]);
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

// ── Instalação principal ──────────────────────────────────────────────────────
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Script: String;
  DatabaseURL: String;
  TotalSteps: Integer;
begin

  // ── ssPostInstall: roda APÓS os arquivos serem copiados para C:\ZapDinApp ────
  if CurStep = ssPostInstall then
  begin
    // Calcula número total de passos para a barra de progresso
    if PGAlreadyInstalled then
      TotalSteps := 4
    else
      TotalSteps := 5;

    ProgressPage.Show;
    ProgressPage.SetProgress(0, TotalSteps);

    // ── PASSO 1: PostgreSQL (somente se não instalado) ─────────────────────────
    if not PGAlreadyInstalled then
    begin
      ProgressPage.SetText(
        'Passo 1/' + IntToStr(TotalSteps) + ' — Baixando e instalando PostgreSQL 16...',
        'Arquivo de ~200 MB. Pode levar de 3 a 10 minutos dependendo da internet.' + #13#10 +
        'Por favor, não feche esta janela.'
      );
      Script :=
        '$url = "https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64.exe"' + #13#10 +
        '$out = "$env:TEMP\pg_installer.exe"' + #13#10 +
        'Write-Host "Baixando PostgreSQL 16..."' + #13#10 +
        'Invoke-WebRequest -Uri $url -OutFile $out' + #13#10 +
        'Write-Host "Instalando PostgreSQL (modo silencioso)..."' + #13#10 +
        'Start-Process $out -ArgumentList "--mode unattended --superpassword zapdin2024 --serverport 5432" -Wait' + #13#10 +
        'Remove-Item $out -Force' + #13#10 +
        'Write-Host "PostgreSQL instalado com sucesso."';
      RunPS(Script);
      PGHost   := 'localhost';
      PGPort   := '5432';
      PGUser   := 'postgres';
      PGPasswd := 'zapdin2024';
      ProgressPage.SetProgress(1, TotalSteps);
    end;

    // ── PASSO 2: Pasta de dados ────────────────────────────────────────────────
    ForceDirectories('C:\ZapDinApp\data');

    // ── PASSO 3: Criar banco de dados ──────────────────────────────────────────
    ProgressPage.SetText(
      'Passo ' + IntToStr(Ord(not PGAlreadyInstalled) + 2) + '/' + IntToStr(TotalSteps) + ' — Criando banco de dados zapdin_app...',
      'Conectando ao PostgreSQL em ' + PGHost + ':' + PGPort + '...'
    );
    Script :=
      '$env:PGPASSWORD = "' + PGPasswd + '"' + #13#10 +
      '$env:PGCONNECT_TIMEOUT = "10"' + #13#10 +
      '$pgHost = "' + PGHost + '"' + #13#10 +
      '$pgPort = "' + PGPort + '"' + #13#10 +
      '$pgUser = "' + PGUser + '"' + #13#10 +
      '$dbName = "{#DBName}"' + #13#10 +
      '# Garante que o servico PostgreSQL esta rodando' + #13#10 +
      '$pgSvc = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Where-Object { $_.Status -ne "Running" } | Select-Object -First 1' + #13#10 +
      'if ($pgSvc) {' + #13#10 +
      '  Write-Host "Iniciando servico $($pgSvc.Name)..."' + #13#10 +
      '  Start-Service $pgSvc.Name -ErrorAction SilentlyContinue' + #13#10 +
      '  Start-Sleep 3' + #13#10 +
      '}' + #13#10 +
      '# 1) psql no PATH' + #13#10 +
      '$psql = $null' + #13#10 +
      'try { $psql = (Get-Command psql -ErrorAction Stop).Source } catch {}' + #13#10 +
      '# 2) Caminhos padrao' + #13#10 +
      'if (-not $psql) {' + #13#10 +
      '  foreach ($v in @("17","16","15","14","13","12","11","10","9.6")) {' + #13#10 +
      '    $p = "C:\Program Files\PostgreSQL\$v\bin\psql.exe"' + #13#10 +
      '    if (Test-Path $p) { $psql = $p; break }' + #13#10 +
      '  }' + #13#10 +
      '}' + #13#10 +
      '# 3) Registro do Windows' + #13#10 +
      'if (-not $psql) {' + #13#10 +
      '  foreach ($v in @("17","16","15","14","13","12","11","10")) {' + #13#10 +
      '    try {' + #13#10 +
      '      $base = (Get-ItemProperty "HKLM:\SOFTWARE\PostgreSQL\Installations\postgresql-x64-$v" -EA Stop)."Base Directory"' + #13#10 +
      '      $p = "$base\bin\psql.exe"' + #13#10 +
      '      if (Test-Path $p) { $psql = $p; break }' + #13#10 +
      '    } catch {}' + #13#10 +
      '  }' + #13#10 +
      '}' + #13#10 +
      'if (-not $psql) { Write-Error "psql.exe nao encontrado"; exit 1 }' + #13#10 +
      'Write-Host "Usando psql: $psql"' + #13#10 +
      '$exists = & $psql -h $pgHost -p $pgPort -U $pgUser -tc "SELECT 1 FROM pg_database WHERE datname=''$dbName''" 2>$null' + #13#10 +
      'if ($exists -notmatch "1") {' + #13#10 +
      '  Write-Host "Criando banco $dbName..."' + #13#10 +
      '  & $psql -h $pgHost -p $pgPort -U $pgUser -c "CREATE DATABASE $dbName;"' + #13#10 +
      '  Write-Host "Banco $dbName criado com sucesso."' + #13#10 +
      '} else { Write-Host "Banco $dbName ja existe, pulando criacao." }';
    RunPS(Script);
    ProgressPage.SetProgress(Ord(not PGAlreadyInstalled) + 2, TotalSteps);

    // ── PASSO 4: Gera .env ─────────────────────────────────────────────────────
    ProgressPage.SetText(
      'Passo ' + IntToStr(Ord(not PGAlreadyInstalled) + 3) + '/' + IntToStr(TotalSteps) + ' — Gerando configuração do sistema...',
      'Validando token e gravando arquivo .env...'
    );
    DatabaseURL := 'postgresql://' + PGUser + ':' + PGPasswd + '@' + PGHost + ':' + PGPort + '/{#DBName}';
    if not FileExists('C:\ZapDinApp\.env') then
    begin
      Script :=
        '$clientName = "Posto ZapDin"' + #13#10 +
        'try {' + #13#10 +
        '  $r = Invoke-RestMethod -Uri "' + MonitorURL + 'api/activate/client-info?token=' + ClientToken + '" -Method GET -ErrorAction Stop' + #13#10 +
        '  if ($r.nome) { $clientName = $r.nome }' + #13#10 +
        '  Write-Host "Cliente identificado: $clientName"' + #13#10 +
        '} catch { Write-Host "Monitor indisponivel, usando nome padrao." }' + #13#10 +
        '$key = -join ((65..90)+(97..122)+(48..57) | Get-Random -Count 64 | ForEach-Object {[char]$_})' + #13#10 +
        '$lines = @(' + #13#10 +
        '  "APP_STATE=active",' + #13#10 +
        '  "PORT=4000",' + #13#10 +
        '  "DATABASE_URL=' + DatabaseURL + '",' + #13#10 +
        '  "SECRET_KEY=$key",' + #13#10 +
        '  "MONITOR_URL=' + MonitorURL + '",' + #13#10 +
        '  "MONITOR_CLIENT_TOKEN=' + ClientToken + '",' + #13#10 +
        '  "CLIENT_NAME=$clientName",' + #13#10 +
        '  "CLIENT_CNPJ=",' + #13#10 +
        '  "ERP_TOKEN="' + #13#10 +
        ')' + #13#10 +
        '$lines | Out-File "C:\ZapDinApp\.env" -Encoding UTF8' + #13#10 +
        'Write-Host "Arquivo .env gravado em C:\ZapDinApp\.env"';
      RunPS(Script);
    end;
    ProgressPage.SetProgress(Ord(not PGAlreadyInstalled) + 3, TotalSteps);

    // ── PASSO 5: NSSM + Serviço Windows ───────────────────────────────────────
    ProgressPage.SetText(
      'Passo ' + IntToStr(TotalSteps) + '/' + IntToStr(TotalSteps) + ' — Instalando serviço Windows (auto-start)...',
      'Registrando ZapDin App como serviço. Aguarde...'
    );
    Script :=
      '# Baixa NSSM se necessario' + #13#10 +
      'if (-not (Test-Path "C:\ZapDinApp\nssm.exe")) {' + #13#10 +
      '  Write-Host "Baixando NSSM..."' + #13#10 +
      '  Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "$env:TEMP\nssm.zip"' + #13#10 +
      '  Expand-Archive "$env:TEMP\nssm.zip" -DestinationPath "$env:TEMP\nssm_tmp" -Force' + #13#10 +
      '  Copy-Item "$env:TEMP\nssm_tmp\nssm-2.24\win64\nssm.exe" "C:\ZapDinApp\nssm.exe"' + #13#10 +
      '  Remove-Item "$env:TEMP\nssm_tmp" -Recurse -Force' + #13#10 +
      '  Remove-Item "$env:TEMP\nssm.zip" -Force' + #13#10 +
      '  Write-Host "NSSM instalado."' + #13#10 +
      '} else { Write-Host "NSSM ja existe, reutilizando." }' + #13#10 +
      '# Mata qualquer processo na porta 4000' + #13#10 +
      '$conn = Get-NetTCPConnection -LocalPort 4000 -State Listen -ErrorAction SilentlyContinue' + #13#10 +
      'if ($conn) {' + #13#10 +
      '  $pids = $conn | Select-Object -ExpandProperty OwningProcess -Unique' + #13#10 +
      '  foreach ($p in $pids) { try { Stop-Process -Id $p -Force -EA Stop; Write-Host "Matou PID $p na porta 4000" } catch {} }' + #13#10 +
      '  Start-Sleep 2' + #13#10 +
      '}' + #13#10 +
      '# Para e remove servico antigo (ignora erros se nao existir)' + #13#10 +
      'Write-Host "Parando servico anterior (se existir)..."' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" stop ZapDinApp 2>$null' + #13#10 +
      'Start-Sleep 3' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" remove ZapDinApp confirm 2>$null' + #13#10 +
      'Start-Sleep 2' + #13#10 +
      '# Instala e configura servico' + #13#10 +
      'Write-Host "Registrando servico ZapDinApp..."' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" install ZapDinApp "C:\ZapDinApp\ZapDinApp.exe"' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppDirectory "C:\ZapDinApp"' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp DisplayName "ZapDin App"' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp Start SERVICE_AUTO_START' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppStdout "C:\ZapDinApp\data\zapdin.log"' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppStderr "C:\ZapDinApp\data\zapdin.log"' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppStdoutCreationDisposition ROLLOVER' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppRotateFiles 1' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppRotateBytes 10485760' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppRestartDelay 5000' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppThrottle 60000' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppExit Default Restart' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppStopMethodSkip 0' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppKillProcessTree 1' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppKillConsoleDelay 5000' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppKillWindowDelay 5000' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" set ZapDinApp AppPreStart "powershell.exe -NoProfile -Command ""Get-NetTCPConnection -LocalPort 4000 -State Listen -EA SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -EA SilentlyContinue }"""' + #13#10 +
      'Write-Host "Iniciando servico ZapDinApp..."' + #13#10 +
      '& "C:\ZapDinApp\nssm.exe" start ZapDinApp' + #13#10 +
      'Write-Host "Servico iniciado com sucesso."';
    RunPS(Script);
    ProgressPage.SetProgress(TotalSteps, TotalSteps);

    ProgressPage.Hide;
  end;

  if CurStep = ssDone then
  begin
    // Abre o browser ao final
    ShellExec('open', 'http://localhost:4000', '', '', SW_SHOW, ewNoWait, ResultCode);
  end;
end;
