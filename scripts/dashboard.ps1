# Opens the dashboard at http://localhost:8501. First run creates its own Python environment
# (.venv-dash) so the dashboard's libraries can never change the pipeline's.
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
if (-not (Test-Path ".venv-dash\Scripts\streamlit.exe")) {
    python -m venv .venv-dash
    & ".venv-dash\Scripts\python.exe" -m pip install -q -r requirements-dashboard.txt
}
& ".venv-dash\Scripts\streamlit.exe" run dashboard\app.py --browser.gatherUsageStats false
