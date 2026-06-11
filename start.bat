@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo   合同审查智能体 - 启动脚本
echo ========================================
echo.

cd /d "%~dp0"

:: ── 检查 .env ──
if not exist ".env" (
    echo [错误] 未找到 .env 文件，请先配置 API Key
    pause
    exit /b 1
)

:: ── 检查并构建向量库 ──
set BUILT=1
for %%d in (data\chroma_civil_code data\chroma_labor_law data\chroma_labor_contract_law data\chroma_judicial_interpretation data\chroma_labor_contract_regulation) do (
    if not exist "%%d\" (
        set BUILT=0
    )
)
if "!BUILT!"=="0" (
    echo [构建] 向量数据库未完整，正在构建...
    set PYTHONPATH=%~dp0
    python builder\build_vector_store.py
    if errorlevel 1 (
        echo [错误] 向量库构建失败
        pause
        exit /b 1
    )
    echo.
) else (
    echo [跳过] 向量数据库已存在
    echo.
)

:: ── 检查前端依赖 ──
if not exist "frontend\node_modules\" (
    echo [安装] 前端依赖...
    cd frontend
    call npm install
    cd ..
    echo.
)

echo [1/2] 启动后端服务 (端口 8000)...
start "ContractAgent-Backend" cmd /k "cd /d "%~dp0" && set PYTHONPATH=%~dp0 && python run_server.py"

timeout /t 3 /nobreak >nul

echo [2/2] 启动前端服务 (端口 5173)...
start "ContractAgent-Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo ========================================
echo   两个窗口已启动！
echo   浏览器访问: http://localhost:5173
echo ========================================
echo.
pause
