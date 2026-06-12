@echo off
echo ========================================
echo   ContractAgent - Start Script
echo ========================================
echo.

cd /d "%~dp0"

:: -- check .env --
if not exist ".env" (
    echo [ERROR] .env file not found
    pause
    exit /b 1
)

:: -- check and build vector store --
if not exist "data\chroma_civil_code\" (
    goto :build_vectors
)
if not exist "data\chroma_labor_law\" (
    goto :build_vectors
)
if not exist "data\chroma_labor_contract_law\" (
    goto :build_vectors
)
if not exist "data\chroma_judicial_interpretation\" (
    goto :build_vectors
)
if not exist "data\chroma_labor_contract_regulation\" (
    goto :build_vectors
)
echo [SKIP] Vector store already exists
echo.
goto :check_frontend

:build_vectors
echo [BUILD] Building vector store ...
set PYTHONPATH=%~dp0
python builder\build_vector_store.py
if %errorlevel% neq 0 (
    echo [ERROR] Vector store build failed
    pause
    exit /b 1
)
echo.

:check_frontend
:: -- check frontend deps --
if not exist "frontend\node_modules\" (
    echo [INSTALL] Installing frontend dependencies ...
    cd frontend
    call npm install
    cd ..
    echo.
)

echo [1/2] Starting backend on port 8000 ...
start "ContractAgent-Backend" cmd /k "cd /d %~dp0 && set PYTHONPATH=%~dp0 && python run_server.py"

timeout /t 3 /nobreak >nul

echo [2/2] Starting frontend on port 5173 ...
start "ContractAgent-Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo ========================================
echo   Services started!
echo   Open: http://localhost:5173
echo ========================================
echo.
pause
