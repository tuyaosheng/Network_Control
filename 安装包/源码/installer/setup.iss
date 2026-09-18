; 网络控制器CTR - 主控端安装程序
; 依赖 dist\ 下已经编译好的：网络控制器主控端.exe / apply_config.exe / CTR.exe
; 编译：ISCC installer\setup.iss（由 build_installer.bat 调用）

#define AppName "网络控制器CTR"
#define AppVersion "2.0.0"
#define ControllerFolder "主控端"
#define AgentFolder "被控端（学生机）"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName=C:\Users\Public\Documents\NetControl
DefaultGroupName=网络控制器CTR
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=网络控制器CTR安装程序
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
SetupIconFile=..\controller\assets\app.ico
UninstallDisplayIcon={app}\{#ControllerFolder}\网络控制器主控端.exe

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "..\dist\网络控制器主控端.exe"; DestDir: "{app}\{#ControllerFolder}"; Flags: ignoreversion
Source: "..\dist\apply_config.exe";     DestDir: "{app}\{#ControllerFolder}"; Flags: ignoreversion
Source: "..\dist\CTR.exe";              DestDir: "{app}\{#AgentFolder}";      Flags: ignoreversion
Source: "..\install_agent.bat";         DestDir: "{app}\{#AgentFolder}";      Flags: ignoreversion
Source: "..\uninstall_agent.bat";       DestDir: "{app}\{#AgentFolder}";      Flags: ignoreversion

[Icons]
Name: "{autodesktop}\网络控制器主控端"; Filename: "{app}\{#ControllerFolder}\网络控制器主控端.exe"
Name: "{group}\网络控制器主控端";       Filename: "{app}\{#ControllerFolder}\网络控制器主控端.exe"
Name: "{group}\卸载网络控制器CTR";      Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#ControllerFolder}\apply_config.exe"; \
    Parameters: "--controller-dir ""{app}\{#ControllerFolder}"" --agent-dir ""{app}\{#AgentFolder}"" --ip ""{code:GetChosenIP}"" --netmask ""{code:GetChosenNetmask}"" --password ""{code:GetChosenPassword}"""; \
    StatusMsg: "正在生成配置..."; Flags: runhidden waituntilterminated
Filename: "{app}\{#ControllerFolder}\网络控制器主控端.exe"; Description: "运行网络控制器主控端"; Flags: postinstall nowait skipifsilent unchecked

[Code]
var
  NicPage: TWizardPage;
  NicCombo: TNewComboBox;
  NicHintLabel: TNewStaticText;
  SubnetPreviewLabel: TNewStaticText;
  ManualIPEdit: TNewEdit;
  ManualMaskEdit: TNewEdit;
  ManualLabel1: TNewStaticText;
  ManualLabel2: TNewStaticText;
  UseManualMode: Boolean;
  NicDescs, NicIPs, NicMasks: TStringList;
  PasswordPage: TInputQueryWizardPage;

{ ---------- 工具函数 ---------- }

function Trim2(const S: String): String;
begin
  Result := Trim(S);
end;

{ 取一行里最后一个冒号（中英文冒号都算）后面的内容 }
function ValueAfterColon(const Line: String): String;
var
  P1, P2, P: Integer;
begin
  P1 := 0;
  P2 := 0;
  { 找最后一个 ':' 或 '：' 的位置 }
  for P := 1 to Length(Line) do
  begin
    if (Line[P] = ':') then P1 := P;
    if (Line[P] = '：') then P2 := P;
  end;
  P := P1;
  if P2 > P then P := P2;
  if P = 0 then
    Result := ''
  else
    Result := Trim2(Copy(Line, P + 1, Length(Line) - P));
end;

{ 去掉 "192.168.1.100(首选)" 这种后缀，只留 IP 本身 }
function StripParenSuffix(const S: String): String;
var
  P: Integer;
begin
  Result := S;
  P := Pos('(', Result);
  if P > 0 then Result := Copy(Result, 1, P - 1);
  P := Pos('（', Result);
  if P > 0 then Result := Copy(Result, 1, P - 1);
  Result := Trim2(Result);
end;

function LooksLikeIPv4(const S: String): Boolean;
var
  I: Integer;
  DotCount: Integer;
  C: Char;
begin
  Result := False;
  if Length(S) = 0 then Exit;
  DotCount := 0;
  for I := 1 to Length(S) do
  begin
    C := S[I];
    if C = '.' then
      DotCount := DotCount + 1
    else if not ((C >= '0') and (C <= '9')) then
      Exit;
  end;
  Result := (DotCount = 3);
end;

function SplitOctet(const IP: String; Index: Integer): Integer;
var
  Parts: TStringList;
begin
  Result := 0;
  Parts := TStringList.Create;
  try
    Parts.Delimiter := '.';
    Parts.StrictDelimiter := True;
    Parts.DelimitedText := IP;
    if Parts.Count = 4 then
      Result := StrToIntDef(Parts[Index], 0);
  finally
    Parts.Free;
  end;
end;

{ 仅用于向导里实时预览网段，真正写配置的计算在 apply_config.exe 里用 Python 权威计算一遍 }
function ComputeCidrPreview(const IP, Mask: String): String;
var
  I, Prefix, MaskOctet, Bit: Integer;
  NetOctets: array[0..3] of Integer;
begin
  Result := '';
  if (not LooksLikeIPv4(IP)) or (not LooksLikeIPv4(Mask)) then Exit;

  Prefix := 0;
  for I := 0 to 3 do
  begin
    MaskOctet := SplitOctet(Mask, I);
    NetOctets[I] := SplitOctet(IP, I) and MaskOctet;
    for Bit := 7 downto 0 do
    begin
      if (MaskOctet and (1 shl Bit)) <> 0 then
        Prefix := Prefix + 1;
    end;
  end;

  Result := Format('%d.%d.%d.%d/%d', [NetOctets[0], NetOctets[1], NetOctets[2], NetOctets[3], Prefix]);
end;

{ ---------- 网卡探测：解析 ipconfig /all 输出 ---------- }

procedure DetectNics;
var
  TmpFile: String;
  Lines: TStringList;
  I: Integer;
  Line, LineTrim: String;
  CurDesc, CurIP, CurMask: String;
  IsHeaderLine: Boolean;
begin
  NicDescs := TStringList.Create;
  NicIPs := TStringList.Create;
  NicMasks := TStringList.Create;

  TmpFile := ExpandConstant('{tmp}\ipconfig_all.txt');
  Exec(ExpandConstant('{cmd}'), '/c ipconfig /all > "' + TmpFile + '"', '',
       SW_HIDE, ewWaitUntilTerminated, I);

  if not FileExists(TmpFile) then Exit;

  Lines := TStringList.Create;
  try
    Lines.LoadFromFile(TmpFile);

    CurDesc := '';
    CurIP := '';
    CurMask := '';

    for I := 0 to Lines.Count - 1 do
    begin
      Line := Lines[I];
      LineTrim := Trim2(Line);
      if LineTrim = '' then Continue;

      { 适配器标题行：不以空白开头，且以冒号结尾（中英文冒号） }
      IsHeaderLine := (Length(Line) > 0) and (Line[1] <> ' ') and (Line[1] <> #9) and
                       ((Copy(LineTrim, Length(LineTrim), 1) = ':') or
                        (Copy(LineTrim, Length(LineTrim), 1) = '：'));

      if IsHeaderLine then
      begin
        CurDesc := '';
        CurIP := '';
        CurMask := '';
        Continue;
      end;

      if (Pos('描述', LineTrim) = 1) or (Pos('Description', LineTrim) = 1) then
        CurDesc := ValueAfterColon(LineTrim)
      else if (Pos('IPv4', LineTrim) = 1) then
        CurIP := StripParenSuffix(ValueAfterColon(LineTrim))
      else if (Pos('子网掩码', LineTrim) = 1) or (Pos('Subnet Mask', LineTrim) = 1) then
        CurMask := StripParenSuffix(ValueAfterColon(LineTrim));

      if (CurIP <> '') and (CurMask <> '') and LooksLikeIPv4(CurIP) and LooksLikeIPv4(CurMask) then
      begin
        if (CurIP <> '127.0.0.1') and (Copy(CurIP, 1, 8) <> '169.254.') then
        begin
          NicDescs.Add(CurDesc);
          NicIPs.Add(CurIP);
          NicMasks.Add(CurMask);
        end;
        CurIP := '';
        CurMask := '';
      end;
    end;
  finally
    Lines.Free;
  end;
end;

{ ---------- 自定义页面 ---------- }

procedure UpdateSubnetPreview(Sender: TObject);
var
  IP, Mask, Cidr: String;
begin
  if UseManualMode then
  begin
    IP := ManualIPEdit.Text;
    Mask := ManualMaskEdit.Text;
  end
  else if (NicCombo <> nil) and (NicCombo.ItemIndex >= 0) then
  begin
    IP := NicIPs[NicCombo.ItemIndex];
    Mask := NicMasks[NicCombo.ItemIndex];
  end
  else
  begin
    IP := '';
    Mask := '';
  end;

  Cidr := ComputeCidrPreview(IP, Mask);
  if Cidr = '' then
    SubnetPreviewLabel.Caption := '局域网网段：（自动计算失败，安装完成后可在主控端「设置」页手动修改）'
  else
    SubnetPreviewLabel.Caption := '局域网网段（白名单放行范围，自动计算）：' + Cidr;
end;

procedure CreateNicPage;
var
  I: Integer;
  Y: Integer;
begin
  NicPage := CreateCustomPage(wpSelectDir, '选择教师机 IP',
    '被控端需要知道教师机的 IP 才能连回来，请选择本机用于连接学生机所在局域网的网卡');

  if NicDescs.Count > 0 then
  begin
    UseManualMode := False;

    NicHintLabel := TNewStaticText.Create(NicPage);
    NicHintLabel.Parent := NicPage.Surface;
    NicHintLabel.Top := 0;
    NicHintLabel.Left := 0;
    NicHintLabel.Caption := '检测到以下网卡，请选择连接学生机所在局域网的那一个：';
    NicHintLabel.AutoSize := True;

    NicCombo := TNewComboBox.Create(NicPage);
    NicCombo.Parent := NicPage.Surface;
    NicCombo.Left := 0;
    NicCombo.Top := NicHintLabel.Top + NicHintLabel.Height + 8;
    NicCombo.Width := NicPage.SurfaceWidth;
    NicCombo.Style := csDropDownList;
    for I := 0 to NicDescs.Count - 1 do
      NicCombo.Items.Add(NicDescs[I] + '  -  ' + NicIPs[I]);
    NicCombo.ItemIndex := 0;
    NicCombo.OnChange := @UpdateSubnetPreview;

    Y := NicCombo.Top + NicCombo.Height + 16;
  end
  else
  begin
    UseManualMode := True;

    NicHintLabel := TNewStaticText.Create(NicPage);
    NicHintLabel.Parent := NicPage.Surface;
    NicHintLabel.Top := 0;
    NicHintLabel.Left := 0;
    NicHintLabel.Caption := '未能自动探测到网卡信息，请手动填写教师机 IP 和子网掩码：';
    NicHintLabel.AutoSize := True;

    ManualLabel1 := TNewStaticText.Create(NicPage);
    ManualLabel1.Parent := NicPage.Surface;
    ManualLabel1.Left := 0;
    ManualLabel1.Top := NicHintLabel.Top + NicHintLabel.Height + 12;
    ManualLabel1.Caption := '教师机 IP：';
    ManualLabel1.AutoSize := True;

    ManualIPEdit := TNewEdit.Create(NicPage);
    ManualIPEdit.Parent := NicPage.Surface;
    ManualIPEdit.Left := 100;
    ManualIPEdit.Top := ManualLabel1.Top - 3;
    ManualIPEdit.Width := NicPage.SurfaceWidth - 100;
    ManualIPEdit.Text := '192.168.1.100';
    ManualIPEdit.OnChange := @UpdateSubnetPreview;

    ManualLabel2 := TNewStaticText.Create(NicPage);
    ManualLabel2.Parent := NicPage.Surface;
    ManualLabel2.Left := 0;
    ManualLabel2.Top := ManualIPEdit.Top + ManualIPEdit.Height + 12;
    ManualLabel2.Caption := '子网掩码：';
    ManualLabel2.AutoSize := True;

    ManualMaskEdit := TNewEdit.Create(NicPage);
    ManualMaskEdit.Parent := NicPage.Surface;
    ManualMaskEdit.Left := 100;
    ManualMaskEdit.Top := ManualLabel2.Top - 3;
    ManualMaskEdit.Width := NicPage.SurfaceWidth - 100;
    ManualMaskEdit.Text := '255.255.255.0';
    ManualMaskEdit.OnChange := @UpdateSubnetPreview;

    Y := ManualMaskEdit.Top + ManualMaskEdit.Height + 16;
  end;

  SubnetPreviewLabel := TNewStaticText.Create(NicPage);
  SubnetPreviewLabel.Parent := NicPage.Surface;
  SubnetPreviewLabel.Left := 0;
  SubnetPreviewLabel.Top := Y;
  SubnetPreviewLabel.Width := NicPage.SurfaceWidth;
  SubnetPreviewLabel.AutoSize := True;
  SubnetPreviewLabel.Caption := '';

  UpdateSubnetPreview(nil);
end;

procedure InitializeWizard;
begin
  DetectNics;
  CreateNicPage;

  PasswordPage := CreateInputQueryPage(NicPage.ID,
    '设置退出/解锁密码',
    '这个密码同时用于被控端托盘图标「退出」和拔网线锁屏时的「解锁」',
    '两处都会用到这一个密码，请牢记，装完之后也可以在主控端「设置」页里改。');
  PasswordPage.Add('密码：', True);
  PasswordPage.Add('确认密码：', True);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  if CurPageID = NicPage.ID then
  begin
    if UseManualMode then
    begin
      if not LooksLikeIPv4(ManualIPEdit.Text) then
      begin
        MsgBox('请输入合法的 IP 地址，例如 192.168.1.100', mbError, MB_OK);
        Result := False;
        Exit;
      end;
      if not LooksLikeIPv4(ManualMaskEdit.Text) then
      begin
        MsgBox('请输入合法的子网掩码，例如 255.255.255.0', mbError, MB_OK);
        Result := False;
        Exit;
      end;
    end
    else
    begin
      if (NicCombo = nil) or (NicCombo.ItemIndex < 0) then
      begin
        MsgBox('请选择一个网卡', mbError, MB_OK);
        Result := False;
        Exit;
      end;
    end;
  end;

  if CurPageID = PasswordPage.ID then
  begin
    if (PasswordPage.Values[0] = '') then
    begin
      MsgBox('密码不能为空', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if PasswordPage.Values[0] <> PasswordPage.Values[1] then
    begin
      MsgBox('两次输入的密码不一致，请重新输入', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
end;

// ---------- 供 [Run] 段的 code 取值函数调用 ----------

function GetChosenIP(Param: String): String;
begin
  if UseManualMode then
    Result := ManualIPEdit.Text
  else
    Result := NicIPs[NicCombo.ItemIndex];
end;

function GetChosenNetmask(Param: String): String;
begin
  if UseManualMode then
    Result := ManualMaskEdit.Text
  else
    Result := NicMasks[NicCombo.ItemIndex];
end;

function GetChosenPassword(Param: String): String;
begin
  Result := PasswordPage.Values[0];
end;
