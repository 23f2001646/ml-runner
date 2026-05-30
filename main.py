from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import subprocess, tempfile, os, sys, signal

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # allow your Vercel site
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

# ── Safety: block dangerous calls ──
BLOCKED = [
    "os.system", "subprocess", "shutil.rmtree",
    "__import__('os')", "open('/etc", "open('/proc",
]

def is_safe(code: str) -> tuple[bool, str]:
    for b in BLOCKED:
        if b in code:
            return False, f"Blocked: '{b}' is not allowed for security."
    return True, ""


# ── Auto-prepend missing imports so partial code works ──
AUTO_IMPORTS = [
    ("torch",       "import torch"),
    ("torchvision", "import torchvision"),
    ("torchaudio",  "import torchaudio"),
    ("nn.",         "import torch.nn as nn"),
    ("optim.",      "import torch.optim as optim"),
    ("F.",          "import torch.nn.functional as F"),
    ("np.",         "import numpy as np"),
    ("pd.",         "import pandas as pd"),
    ("plt.",        "import matplotlib.pyplot as plt"),
    ("sns.",        "import seaborn as sns"),
]

def add_missing_imports(code: str) -> str:
    lines_to_add = []
    for keyword, import_stmt in AUTO_IMPORTS:
        # Skip if already imported
        pkg = import_stmt.split()[-1].split(".")[0]
        if keyword in code and pkg not in code.split("import ")[-1]:
            # More precise check: keyword used but import line not present
            already = any(
                import_stmt.strip() in line or
                f"import {pkg}" in line
                for line in code.splitlines()
            )
            if not already:
                lines_to_add.append(import_stmt)
    if lines_to_add:
        # Remove duplicates while preserving order
        seen = set()
        unique = [x for x in lines_to_add if not (x in seen or seen.add(x))]
        return "\n".join(unique) + "\n\n" + code
    return code


@app.get("/")
def root():
    return {"status": "ok", "message": "ML Runner API — Python with PyTorch"}


@app.post("/run")
async def run_code(request: Request):
    body = await request.json()
    code = body.get("code", "").strip()

    if not code:
        return JSONResponse({"output": "", "error": "No code provided"})

    safe, reason = is_safe(code)
    if not safe:
        return JSONResponse({"output": "", "error": reason})

    # Auto-add missing imports (torch, np, pd, plt etc.)
    code = add_missing_imports(code)

    # Write code to a temp file and execute
    with tempfile.NamedTemporaryFile(
        suffix=".py", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(code)
        fname = f.name

    try:
        result = subprocess.run(
            [sys.executable, fname],
            capture_output=True,
            text=True,
            timeout=20,
            env={
                **os.environ,
                "MPLBACKEND": "Agg",          # matplotlib non-interactive
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        output = result.stdout or ""
        error  = result.stderr or ""

        # Strip long tracebacks to just the useful part
        if error and len(error) > 2000:
            lines = error.splitlines()
            error = "\n".join(lines[-20:])

        return JSONResponse({"output": output, "error": error})

    except subprocess.TimeoutExpired:
        return JSONResponse({"output": "", "error": "⏱ Timed out after 20 seconds."})
    except Exception as e:
        return JSONResponse({"output": "", "error": str(e)})
    finally:
        try:
            os.unlink(fname)
        except Exception:
            pass


@app.get("/health")
def health():
    return {"status": "healthy"}
