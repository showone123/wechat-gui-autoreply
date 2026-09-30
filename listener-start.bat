@echo off
chcp 65001 >nul
title WeChat Listener - START
setlocal
set "PYEXE=%WECHAT_LISTENER_PYTHON%"
if not defined PYEXE (
  set "PYEXE=python"
  where python >nul 2>nul || set "PYEXE=py -3"
)
%PYEXE% "%~dp0listener_ctl.py" start
echo.
pause
endlocal
