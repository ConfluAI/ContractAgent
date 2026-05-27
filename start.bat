@echo off
chcp 65001 >nul
echo ========================================
echo   合同审查智能体 - 启动脚本
echo ========================================
echo.

echo [1/2] 启动后端服务 (端口 8000)...
start "ContractAgent-Backend" cmd /k "cd /d "%~dp0" && set PYTHONPATH=. && python -m uvicorn server.main:app --reload --port 8000"

timeout /t 3 /nobreak >nul

echo [2/2] 启动前端服务 (端口 5173)...
start "ContractAgent-Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo ========================================
echo   两个窗口已启动！
echo   浏览器访问: http://localhost:5173
echo   管理员账号: admin / admin123
echo ========================================
echo.
pause
