@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "SKIP_DEPENDENCIES=0"
set "SKIP_INSTALLER=0"

:parse_arguments
if "%~1"=="" goto arguments_done
if /I "%~1"=="-SkipDependencies" set "SKIP_DEPENDENCIES=1" & shift & goto parse_arguments
if /I "%~1"=="--skip-dependencies" set "SKIP_DEPENDENCIES=1" & shift & goto parse_arguments
if /I "%~1"=="-SkipInstaller" set "SKIP_INSTALLER=1" & shift & goto parse_arguments
if /I "%~1"=="--skip-installer" set "SKIP_INSTALLER=1" & shift & goto parse_arguments
echo Argomento non riconosciuto: %~1
echo Uso: build_windows.bat [-SkipDependencies] [-SkipInstaller]
exit /b 2

:arguments_done
set "PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Ambiente Python non trovato. Eseguire prima run_windows.bat.
    exit /b 1
)

if "%SKIP_DEPENDENCIES%"=="0" (
    "%PYTHON%" -m pip install -r requirements.txt -r requirements-build.txt
    if errorlevel 1 (
        echo Installazione delle dipendenze non riuscita.
        exit /b 1
    )
)

"%PYTHON%" -m PyInstaller --noconfirm --clean packaging\TravelPhotoMapper.spec
if errorlevel 1 (
    echo Build PyInstaller non riuscita.
    exit /b 1
)

if "%SKIP_INSTALLER%"=="1" (
    echo Eseguibile creato in dist\TravelPhotoMapper.exe
    exit /b 0
)

set "ISCC="
for %%I in (ISCC.exe) do set "ISCC=%%~$PATH:I"
if defined ISCC goto iscc_found
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if defined ISCC goto iscc_found
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

echo Inno Setup 6 non trovato. Installarlo oppure usare -SkipInstaller.
exit /b 1

:iscc_found
"%ISCC%" "installer\TravelPhotoMapper.iss"
if errorlevel 1 (
    echo Compilazione del setup Inno Setup non riuscita.
    exit /b 1
)

echo Setup creato in dist\installer\TravelPhotoMapper-Setup-1.0.0.exe
exit /b 0
