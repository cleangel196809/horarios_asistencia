# SISCA Mobile - Verificador de requisitos (Windows)
Write-Host ""
Write-Host "===  VERIFICADOR DE REQUISITOS - SISCA MOBILE  ===" -ForegroundColor Cyan
Write-Host ""

function Check {
  param($Nombre, $Comando, $UrlDescarga, $RequeridoPara)
  try {
    $version = (Invoke-Expression $Comando) 2>$null
    if ($version) {
      Write-Host "  [OK] $Nombre" -ForegroundColor Green -NoNewline
      Write-Host " -> $version" -ForegroundColor DarkGray
      return $true
    } else { throw }
  } catch {
    Write-Host "  [FALTA] $Nombre" -ForegroundColor Red
    Write-Host "         Necesario para: $RequeridoPara" -ForegroundColor Yellow
    Write-Host "         Descarga: $UrlDescarga" -ForegroundColor DarkCyan
    return $false
  }
}

$nodeOK   = Check "Node.js"        "node --version"        "https://nodejs.org/"                  "Capacitor"
$npmOK    = Check "npm"            "npm --version"         "(viene con Node.js)"                  "Capacitor"
$javaOK   = Check "Java JDK"       "java -version 2>&1 | Select-Object -First 1"  "https://adoptium.net/ (JDK 17)"  "Compilar Android"
$gradleOK = $javaOK  # gradle se baja solo con Android Studio
$adbOK    = Check "Android SDK"    "adb --version 2>&1 | Select-Object -First 1"  "Android Studio: https://developer.android.com/studio"  "Compilar y emular Android"

Write-Host ""
Write-Host "===  TU IP LOCAL  ===" -ForegroundColor Cyan
Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp,Manual 2>$null `
  | Where-Object { $_.IPAddress -notmatch '^169\.' } `
  | Select-Object IPAddress, InterfaceAlias `
  | Format-Table -AutoSize

Write-Host "===  RESUMEN  ===" -ForegroundColor Cyan
if ($nodeOK -and $javaOK -and $adbOK) {
  Write-Host "  Estas listo para compilar la app Android." -ForegroundColor Green
} else {
  Write-Host "  Instala lo que falta antes de continuar." -ForegroundColor Yellow
}
Write-Host ""
Read-Host "Presiona Enter para salir"
