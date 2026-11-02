@echo off
chcp 65001 >nul
py -3.13 "%~dp0run.py" %*
if errorlevel 1 pause
