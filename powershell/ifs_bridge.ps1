param([Parameter(Mandatory=$true)][string]$ConfigPath,[Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference="Stop"
try {
  $cfg=Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if($cfg.view -notmatch '^[A-Za-z][A-Za-z0-9_]*$'){throw "Geçersiz VIEW."}
  foreach($f in $cfg.fields){if($f -notmatch '^[A-Za-z][A-Za-z0-9_]*$'){throw "Geçersiz alan adı."}}
  $cache=Join-Path $env:LOCALAPPDATA "Apps\2.0"
  $names=@("Ifs.Fnd.Core.dll","Ifs.Fnd.Buffer.dll","Ifs.Fnd.Data.dll","Ifs.Fnd.AccessProvider.dll","Ifs.Fnd.AccessProvider.Interactive.dll")
  $paths=@{}
  foreach($n in $names){
    $x=Get-ChildItem -Path $cache -Filter $n -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if(!$x){throw "IFS istemci DLL bulunamadı: $n. IFS uygulamasını aynı Windows hesabıyla aç."}; $paths[$n]=$x.FullName
  }
  foreach($n in $names){Add-Type -Path $paths[$n]}
  $conn=New-Object Ifs.Fnd.AccessProvider.FndConnection
  $conn.ConnectionString=[string]$cfg.ifs_url; $conn.InteractiveMode=$true; $conn.AutoLogon=$false; $conn.IgnoreCertificateValidation=$false
  $cred=New-Object Ifs.Fnd.AccessProvider.Interactive.FndLoginCredentials
  $cred.ConnectTo=[string]$cfg.ifs_url; $cred.SystemName=[string]$cfg.system_name; $cred.Language="tr-TR"
  $cred.ShowLoginDialog=$true; $cred.ForcedShow=$true; $cred.RememberPassword=$false
  $dialog=New-Object Ifs.Fnd.AccessProvider.Interactive.FndLoginDialog($conn)
  $login=$dialog.ShowDialog($cred)
  if([string]$login -ne "OK" -or !$conn.IsSessionInitialized){throw "IFS oturumu başlatılamadı veya giriş iptal edildi."}
  $cols=($cfg.fields | ForEach-Object {'"'+$_+'"'}) -join ", "
  $where=@(); $binds=New-Object Ifs.Fnd.AccessProvider.PLSQL.FndBindVariableCollection
  foreach($entry in $cfg.keys.PSObject.Properties){
    if($entry.Name -notmatch '^[A-Za-z][A-Za-z0-9_]*$'){throw "Geçersiz anahtar."}
    $where+=('"'+$entry.Name+'" = :'+$entry.Name)
    $attr=New-Object Ifs.Fnd.Data.FndAlphaAttribute([string]$entry.Value)
    $bind=New-Object Ifs.Fnd.AccessProvider.PLSQL.FndBindVariable($entry.Name,$attr); $binds.Add($bind)
  }
  if(!$where.Count){throw "Anahtar filtresi olmadan sorgu çalıştırılmaz."}
  $sql="SELECT $cols FROM $($cfg.view) WHERE "+($where -join " AND ")+" AND ROWNUM <= 20"
  $cmd=New-Object Ifs.Fnd.AccessProvider.PLSQL.FndPLSQLSelectCommand($conn)
  $cmd.CommandText=$sql; $cmd.MaxRows=20; $cmd.BindVariables=$binds
  $table=$cmd.ExecuteReader(); $rows=@()
  foreach($r in $table.Rows){
    $item=[ordered]@{}
    for($i=0;$i -lt $table.Columns.Count;$i++){
      $v=$r[$i]; $item[$table.Columns[$i].Name]=if($null -eq $v){$null}else{$v.ToString()}
    }
    $rows+=,[pscustomobject]$item
  }
  [pscustomobject]@{rows=$rows;view=$cfg.view;fetched_at=(Get-Date).ToString("o")} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
  $conn.Dispose(); exit 0
} catch {
  [Console]::Error.WriteLine($_.ToString()); exit 1
}
