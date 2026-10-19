$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
& ".\.venv\Scripts\python.exe" -m streamlit run app/dashboard/main.py
