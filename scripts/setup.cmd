@echo off
rem Windows entry point for setup. Usage: scripts\setup.cmd  or  scripts\setup.cmd -Online
rem Runs setup.ps1 with the PowerShell execution policy bypassed for this run only.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
