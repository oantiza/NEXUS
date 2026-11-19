@echo off
rem Arrastra encima de este archivo uno o varios C3D, o una carpeta que los contenga.
rem Los informes se guardan en la carpeta "informes", junto a este archivo. Los C3D no se modifican.
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
  echo Arrastra encima de este archivo uno o varios C3D, o una carpeta que los contenga.
  pause
  exit /b 1
)
set PYTHON=python
where python >nul 2>nul || set PYTHON=py -3
%PYTHON% -m nexus_mocap revisar %* --salida "%~dp0informes"
if errorlevel 1 (
  pause
  exit /b 1
)
start "" "%~dp0informes\indice.html"
