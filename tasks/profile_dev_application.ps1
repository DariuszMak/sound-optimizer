uv run scalene run --malloc-threshold 1 --cpu-percent-threshold 0 --profile-all .\src\main.py

uv run scalene view --standalone
Start-Process .\scalene-profile.html ; 
