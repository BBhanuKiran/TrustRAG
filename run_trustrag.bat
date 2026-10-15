@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating TrustRAG's Python environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Failed to create the environment. Install Python 3.11 or newer and retry.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import fastapi, numpy, pypdf, sentence_transformers, dotenv" >nul 2>&1
if errorlevel 1 (
    echo Installing TrustRAG dependencies. This can take several minutes...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Dependency installation failed. Check the error above and retry.
        pause
        exit /b 1
    )
)

echo Starting the TrustRAG website at http://127.0.0.1:8765
echo Local development uses Ollama if no hosted AI provider key is configured.
echo Press Ctrl+C in this window to stop TrustRAG.
start "" "http://127.0.0.1:8765"
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8765
if errorlevel 1 (
    echo TrustRAG stopped with an error. Review the message above.
    pause
    exit /b 1
)
