param(
  [Parameter(Mandatory=$true)][string]$ConfigPath,
  [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference = "Stop"

function Test-IFSIdentifier([string]$name) {
  if ([string]::IsNullOrEmpty($name)) { return $false }
  for ($i = 0; $i -lt $name.Length; $i++) {
    $ch = [int][char]$name[$i]
    $letter = (($ch -ge 65 -and $ch -le 90) -or ($ch -ge 97 -and $ch -le 122))
    $digit = ($ch -ge 48 -and $ch -le 57)
    if ($i -eq 0) { if (-not $letter) { return $false } }
    elseif (-not ($letter -or $digit -or $ch -eq 95)) { return $false }
  }
  return $true
}

try {
  $cfg = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json

  # VIEW adini temizle ve ASCII karakterleriyle dogrula.
  $view = ([string]$cfg.view).Trim().Trim([char]0xFEFF).Trim()
  if (-not (Test-IFSIdentifier $view)) {
    throw "Gecersiz VIEW degeri: [$view]"
  }
  if (!$cfg.columns -or $cfg.columns.Count -lt 1) {
    throw "Sorgulanacak gercek alan yok."
  }
  foreach ($fieldName in $cfg.columns) {
    if (-not (Test-IFSIdentifier ([string]$fieldName))) {
      throw "Gecersiz alan adi: $fieldName"
    }
  }

  $cache = Join-Path $env:LOCALAPPDATA "Apps\2.0"
  $names = @(
    "Ifs.Fnd.Core.dll",
    "Ifs.Fnd.Buffer.dll",
    "Ifs.Fnd.Data.dll",
    "Ifs.Fnd.AccessProvider.dll",
    "Ifs.Fnd.AccessProvider.Interactive.dll"
  )
  $paths = @{}
  foreach ($dllName in $names) {
    $dll = Get-ChildItem -Path $cache -Filter $dllName -Recurse -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (!$dll) {
      throw "IFS istemci DLL bulunamadi: $dllName. IFS uygulamasini ayni Windows hesabiyla ac."
    }
    $paths[$dllName] = $dll.FullName
  }
  foreach ($dllName in $names) {
    Add-Type -Path $paths[$dllName]
  }

  $conn = New-Object Ifs.Fnd.AccessProvider.FndConnection
  $conn.ConnectionString = [string]$cfg.ifs_url
  $conn.InteractiveMode = $true
  $conn.AutoLogon = $false
  $conn.IgnoreCertificateValidation = $false

  $cred = New-Object Ifs.Fnd.AccessProvider.Interactive.FndLoginCredentials
  $cred.ConnectTo = [string]$cfg.ifs_url
  $cred.SystemName = [string]$cfg.system_name
  $cred.Language = "tr-TR"
  $cred.ShowLoginDialog = $true
  $cred.ForcedShow = $false
  $cred.RememberPassword = $true

  $dialog = New-Object Ifs.Fnd.AccessProvider.Interactive.FndLoginDialog($conn)
  $login = $dialog.ShowDialog($cred, $true)
  if ([string]$login -ne "OK" -or !$conn.IsSessionInitialized) {
    throw "IFS oturumu baslatilamadi veya giris iptal edildi."
  }

  $cols = ($cfg.columns | ForEach-Object { '"' + [string]$_ + '"' }) -join ", "
  $where = @()
  $binds = New-Object Ifs.Fnd.AccessProvider.PLSQL.FndBindVariableCollection
  $index = 0

  foreach ($filter in $cfg.filters) {
    $field = [string]$filter.name
    $value = [string]$filter.value
    if (-not (Test-IFSIdentifier $field)) {
      throw "Gecersiz filtre alani: $field"
    }
    if (!$value -or $value -eq "%") { continue }

    if ($value -match '^(\d{2}\.\d{2}\.\d{4})\.\.(\d{2}\.\d{2}\.\d{4})$') {
      $fromName = "P_FROM_$index"
      $toName = "P_TO_$index"
      $where += ('"' + $field + '" >= TO_DATE(:' + $fromName + ",'DD.MM.YYYY') AND " + '"' + $field + '" < TO_DATE(:' + $toName + ",'DD.MM.YYYY') + 1")
      $fromAttr = New-Object Ifs.Fnd.Data.FndAlphaAttribute([string]$Matches[1])
      $toAttr = New-Object Ifs.Fnd.Data.FndAlphaAttribute([string]$Matches[2])
      $binds.Add((New-Object Ifs.Fnd.AccessProvider.PLSQL.FndBindVariable($fromName, $fromAttr)))
      $binds.Add((New-Object Ifs.Fnd.AccessProvider.PLSQL.FndBindVariable($toName, $toAttr)))
    }
    else {
      $bindName = "P_VAL_$index"
      if ($value.Contains("%") -or $value.Contains("_")) {
        $where += ('UPPER("' + $field + '") LIKE UPPER(:' + $bindName + ')')
      }
      else {
        $where += ('"' + $field + '" = :' + $bindName)
      }
      $attr = New-Object Ifs.Fnd.Data.FndAlphaAttribute($value)
      $binds.Add((New-Object Ifs.Fnd.AccessProvider.PLSQL.FndBindVariable($bindName, $attr)))
    }
    $index++
  }

  $sql = "SELECT $cols FROM $view"
  if ($where.Count -gt 0) {
    $sql += " WHERE " + ($where -join " AND ") + " AND ROWNUM <= " + [Math]::Min([int]$cfg.max_rows, 500)
  }
  else {
    $sql += " WHERE ROWNUM <= " + [Math]::Min([int]$cfg.max_rows, 500)
  }

  $limit = [Math]::Min([int]$cfg.max_rows, 500)
  $cmd = New-Object Ifs.Fnd.AccessProvider.PLSQL.FndPLSQLSelectCommand($conn)
  $cmd.CommandText = $sql
  $cmd.MaxRows = $limit
  foreach ($bind in $binds) {
    $cmd.BindVariables.Add($bind)
  }

  $table = $cmd.ExecuteReader()
  $rows = @()
  foreach ($row in $table.Rows) {
    $item = [ordered]@{}
    for ($i = 0; $i -lt $table.Columns.Count; $i++) {
      $value = $row[$i]
      $item[$table.Columns[$i].Name] = if ($null -eq $value) { $null } else { $value.ToString() }
    }
    $rows += ,([pscustomobject]$item)
  }

  [pscustomobject]@{
    rows = $rows
    view = $view
    fetched_at = (Get-Date).ToString("o")
  } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
  exit 0
}
catch {
  [Console]::Error.WriteLine(($_ | Out-String))
  exit 1
}