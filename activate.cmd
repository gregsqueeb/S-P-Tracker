@echo off

set "TARGET=D:\SteamLibrary\steamapps\common\assettocorsa\apps\python\ptracker"

if exist "%TARGET%" (
    echo "Removing current link"
    rmdir "%TARGET%"
)

echo "Creating link ..."
mklink /D "%TARGET%" "%~dp0%

pause
