param([Parameter(Mandatory=$true)][string]$ConfigPath,[Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference="Stop"
try {
  $cfg=Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if($cfg.view -notmatch '^[A-Za-z][A-Za-z0-9_]*$'){throw "Geçersiz VIEW."}
  if(!$cfg.columns -or $cfg.columns.Count -lt 1){throw "Sorgulanacak gerçek alan yok."}
  foreach($f in $cfg.columns){if($f -notmatch '^[A-Za-z][A-Za-z0-9_]*$'){throw "Geçersiz alan adı: $f"}}
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
  $cols=($cfg.columns | ForEach-Object {'"' + $_ + '"'}) -join ", "
  $where=@()
  $binds=New-Object Ifs.Fnd.AccessProvider.PLSQL.FndBindVariableCollection
  $index=0
  foreach($filter in $cfg.filters){
    $field=[string]$filter.name; $value=[string]$filter.value
    if($field -notmatch '^[A-Za-z][A-Za-z0-9_]*$'){throw "Geçersiz filtre alanı."}
    if(!$value -or $value -eq "%"){continue}
    if($value -match '^(\d{2}\.\d{2}\.\d{4})\.\.(\d{2}\.\d{2}\.\d{4})$'){
      $fromName="P_FROM_$index"; $toName="P_TO_$index"
      $where+=('"' + $field + '" >= TO_DATE(:' + $fromName + ",'DD.MM.YYYY') AND " + '"' + $field + '" < TO_DATE(:' + $toName + ",'DD.MM.YYYY') + 1")
      $a=New-Object Ifs.Fnd.Data.FndAlphaAttribute([string]$Matches[1])
      $b=New-Object Ifs.Fnd.Data.FndAlphaAttribute([string]$Matches[2])
      $binds.Add((New-Object Ifs.Fnd.AccessProvider.PLSQL.FndBindVariable($fromName,$a)))
      $binds.Add((New-Object Ifs.Fnd.AccessProvider.PLSQL.FndBindVariable($toName,$b)))
    } else {
      $bindName="P_VAL_$index"
      $where+=('"' + $field + '" = :' + $bindName)
      $attr=New-Object Ifs.Fnd.Data.FndAlphaAttribute($value)
      $binds.Add((New-Object Ifs.Fnd.AccessProvider.PLSQL.FndBindVariable($bindName,$attr)))
    }
    $index++
  }
  $sql="SELECT $cols FROM $($cfg.view)"
  if($where.Count){$sql+=" WHERE " + ($where -join " AND ")}
  $limit=[Math]::Min([int]$cfg.max_rows,500)
  $sql+=" AND ROWNUM <= $limit" 
  if(!$where.Count){$sql="SELECT $cols FROM $($cfg.view) WHERE ROWNUM <= $limit"}
  $cmd=New-Object Ifs.Fnd.AccessProvider.PLSQL.FndPLSQLSelectCommand($conn)
  $cmd.CommandText=$sql; $cmd.MaxRows=$limit; $cmd.BindVariables=$binds
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