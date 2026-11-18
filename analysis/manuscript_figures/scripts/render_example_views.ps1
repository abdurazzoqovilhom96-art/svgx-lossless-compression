<#
.SYNOPSIS
  Renders the example file (Wikimedia Commons, "Sibiu County 1937.svg") for Fig. 5 with headless Microsoft Edge:
  full.png (the whole file, 1800 x 1530 px) and zoom.png (the window x 1130-1290, y 1440-1560 in SVG user units, 1600 x 1200 px).
  The original file is never modified; a copy with a viewBox is written to OutDir.
.EXAMPLE
  powershell -File render_example_views.ps1 -Svg 6e99fcb1eefa7f8bd1f21940a2164871dfd113579da454956020bdc184592477.svg -OutDir renders
#>
param(
  [Parameter(Mandatory = $true)][string]$Svg,
  [Parameter(Mandatory = $true)][string]$OutDir,
  [string]$Edge = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
)
$ErrorActionPreference = 'Stop'
$expected = '6e99fcb1eefa7f8bd1f21940a2164871dfd113579da454956020bdc184592477'
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Svg).Hash.ToLower()
if ($actual -ne $expected) { throw "SHA-256 of the SVG is $actual, expected $expected" }
if (-not (Test-Path -LiteralPath $Edge)) { throw "Microsoft Edge not found at $Edge (use -Edge)" }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
$utf8 = New-Object System.Text.UTF8Encoding($false)
$text = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $Svg).Path)
$head = $text.Substring(0, 3000); $rest = $text.Substring(3000)   # the root element lies in the first 3000 characters
if ($head -notmatch 'width="2604\.1531"' -or $head -notmatch 'height="2213\.8298"') { throw 'unexpected root element' }

function New-View([string]$viewBox, [int]$w, [int]$h, [string]$name) {
  $hd = $head -replace 'width="2604\.1531"', "width=`"$w`"" -replace 'height="2213\.8298"', "height=`"$h`" viewBox=`"$viewBox`" preserveAspectRatio=`"none`""
  [System.IO.File]::WriteAllText("$OutDir\$name.svg", $hd + $rest, $utf8)
  $html = "<html><body style='margin:0;background:#fff'><img src='$name.svg' width='$w' height='$h' style='display:block'></body></html>"
  [System.IO.File]::WriteAllText("$OutDir\$name.html", $html, $utf8)
  Start-Process -FilePath $Edge -Wait -NoNewWindow -ArgumentList @(
    '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1', '--allow-file-access-from-files',
    '--virtual-time-budget=20000', "--window-size=$w,$h", "--screenshot=$OutDir\$name.png",
    ("file:///" + ($OutDir -replace '\\', '/') + "/$name.html"))
  if (-not (Test-Path "$OutDir\$name.png")) { throw "rendering of $name failed" }
}
New-View '0 0 2604.1531 2213.8298' 1800 1530 'full'
New-View '1130 1440 160 120' 1600 1200 'zoom'
Get-ChildItem $OutDir -Filter '*.png' | Select-Object Name, Length
