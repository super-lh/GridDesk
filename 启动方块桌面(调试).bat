@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   方块桌面 · GridDesk 调试启动
echo   这个窗口会显示服务日志，关闭窗口即停止服务
echo ============================================
echo.
where python >nul 2>nul
if %errorlevel%==0 (
  python server.py --open
) else (
  if exist "D:\anaconda\python.exe" (
    "D:\anaconda\python.exe" server.py --open
  ) else (
    echo 没有找到 python.exe，请先安装 Python 3。
  )
)
echo.
pause
