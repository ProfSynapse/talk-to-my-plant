"""Generate private deployment keys and pass values to Railway via stdin."""
import json
import os
import secrets
import subprocess
from pathlib import Path

SERVICE = "plant-api"
existing = json.loads(subprocess.check_output(["railway","variable","list","--service",SERVICE,"--json"], text=True))
local = {}
for name in ("PLANT_API_KEY", "DEVICE_API_KEY", "SIMULATOR_API_KEY"):
    value = existing.get(name) or secrets.token_urlsafe(48)
    if not existing.get(name):
        subprocess.run(["railway","variable","set","--service",SERVICE,"--skip-deploys","--stdin",name],
                       input=value, text=True, check=True, stdout=subprocess.DEVNULL)
    local[name] = value
if os.getenv("OPENROUTER_API_KEY") and not existing.get("OPENROUTER_API_KEY"):
    subprocess.run(["railway","variable","set","--service",SERVICE,"--skip-deploys","--stdin","OPENROUTER_API_KEY"],
                   input=os.environ["OPENROUTER_API_KEY"], text=True, check=True, stdout=subprocess.DEVNULL)
    print("OpenRouter credential configured from environment")
local["TELEMETRY_URL"] = "https://plant-api-production-68c9.up.railway.app/api/telemetry"
target = Path(".env.railway")
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    for key,value in local.items():
        f.write(f"{key}={value}\n")
print("Deployment credentials saved privately to .env.railway (not printed)")
