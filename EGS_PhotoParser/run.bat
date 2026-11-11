@echo off
chcp 65001 > nul
title EGS_PhotoParser

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ОШИБКА] Виртуальное окружение не найдено.
    echo Выполни установку зависимостей перед запуском.
    pause
    exit /b 1
)

echo ========================================
echo           EGS_PhotoParser
echo ========================================
echo.

".venv\Scripts\python.exe" main.py

echo.
echo ========================================
echo Программа завершила работу.
echo ========================================
pause
