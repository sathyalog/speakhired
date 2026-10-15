@echo off
rem Windows entry point to start the app. Usage: scripts\run.cmd
rem Runs run.ps1 with the PowerShell execution policy bypassed for this run only.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
