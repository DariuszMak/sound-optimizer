$repo = if ($PSScriptRoot) { $PSScriptRoot } else { $PWD.Path }

$env:UV_PROJECT_ENVIRONMENT = ".venv-wsl"
$env:UV_LINK_MODE = "copy"
$env:WSLENV = "UV_PROJECT_ENVIRONMENT:UV_LINK_MODE"

wsl -e bash -lc "uv cache clean"

wsl --cd "$repo" -e bash -lc "uv run scalene run --malloc-threshold 1 --cpu-percent-threshold 0 .\src\main.py && uv run scalene view --standalone"

Start-Process .\scalene-profile.html ; 
