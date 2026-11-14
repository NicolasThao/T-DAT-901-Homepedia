# Exporte chaque slide du deck en PNG (rendu PowerPoint reel, polices comprises) dans rendu/.
$ici = Split-Path -Parent $MyInvocation.MyCommand.Path
$deck = Join-Path $ici "Homepedia_Follow-up_2.pptx"
$sortie = Join-Path $ici "rendu"
New-Item -ItemType Directory -Force $sortie | Out-Null
Get-ChildItem $sortie -Filter *.png | Remove-Item -Force
$app = New-Object -ComObject PowerPoint.Application
$pres = $app.Presentations.Open($deck, -1, 0, 0)  # lecture seule, sans fenetre
foreach ($s in $pres.Slides) { $s.Export((Join-Path $sortie ("slide{0:D2}.png" -f $s.SlideIndex)), "PNG", 1600, 900) }
$pres.Close(); $app.Quit()
Get-ChildItem $sortie | Select-Object Name
