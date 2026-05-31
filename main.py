from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import subprocess, tempfile, os, sys, signal, re

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


# ── Auto-prepend imports so partial snippets run ──
# Note: duplicate imports are harmless in Python (`import torch` twice never errors),
# so we simply prepend the import for any usage pattern we detect. No fragile
# "already imported?" checks needed — that was the source of the earlier bug.
AUTO_IMPORTS = [
    (r"\btorch\b",       "import torch"),
    (r"\btorchvision\b", "import torchvision"),
    (r"\btorchaudio\b",  "import torchaudio"),
    (r"\bnn\.",          "import torch.nn as nn"),
    (r"\boptim\.",       "import torch.optim as optim"),
    (r"\bF\.",           "import torch.nn.functional as F"),
    (r"\bnp\.",          "import numpy as np"),
    (r"\bpd\.",          "import pandas as pd"),
    (r"\bplt\.",         "import matplotlib.pyplot as plt"),
]

def add_missing_imports(code: str) -> str:
    prelude = []
    for pattern, import_stmt in AUTO_IMPORTS:
        if re.search(pattern, code):
            prelude.append(import_stmt)
    if prelude:
        return "\n".join(prelude) + "\n\n" + code
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
