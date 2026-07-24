deactivate ; 
clear ; 

# $ports = 8000, 8001
# 
# foreach ($port in $ports) {
#     $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
#     if ($conns) {
#         $conns | Select-Object -ExpandProperty OwningProcess -Unique |
#             Where-Object { $_ -gt 0 } |
#             ForEach-Object {
#                 Write-Host "Port $port is used by PID $_. Killing..."
#                 Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
#             }
#     } else {
#         Write-Host "No process is using port $port."
#     }
# }

uv self update ; 
uv cache clean ; 

git reset --hard HEAD ; 
git clean -x -d -f ; 