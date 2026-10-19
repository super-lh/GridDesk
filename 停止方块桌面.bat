@echo off
chcp 65001 >nul
echo 正在停止方块桌面的本地服务...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" 2>nul
echo 完成。如果应用窗口还在，直接关闭窗口即可。
timeout /t 2 >nul
