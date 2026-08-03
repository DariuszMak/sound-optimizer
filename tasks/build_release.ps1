uv python install 3.14 ; 
uv python pin 3.14 ; 
uv sync --no-dev --locked --no-cache ; 

uv run pyinstaller --clean .\scripts\standalone_build_windows.spec ; 

Copy-Item -r -fo .\dist\* .\releases\windows\ ; 
Remove-Item -r -fo .\dist, .\build ; 
