# A teljes elemzés újrafuttatása (Windows PowerShell).
# Minden szám, ábra és táblázat ebből a futásból származik.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install --quiet pandas numpy scipy matplotlib pyarrow pyyaml
python run_analysis.py
