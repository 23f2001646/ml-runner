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

def is_safe(code: str):
    for b in BLOCKED:
        if b in code:
            return False, f"Blocked: '{b}' is not allowed for security."
    return True, ""


# ── Auto-prepend imports so partial snippets run ──
# Duplicate imports are harmless in Python, so we just prepend on detection.
AUTO_IMPORTS = [
    (r"\btorch\b",       "import torch"),
    (r"\btorchvision\b", "import torchvision"),
    (r"\btorchaudio\b",  "import torchaudio"),
    (r"\bnn\.",          "import torch.nn as nn"),
    (r"\boptim\.",       "import torch.optim as optim"),
    (r"\bF\.",           "import torch.nn.functional as F"),
    (r"\bnp\.",          "import numpy as np"),
    (r"\bpd\.",          "import pandas as pd"),
]

# matplotlib needs the headless AGG backend set BEFORE pyplot is imported.
MPL_PRELUDE = (
    "import matplotlib\n"
    "matplotlib.use('AGG')\n"
    "import matplotlib.pyplot as plt\n"
    "plt.show = lambda *a, **k: None\n"
)

# After user code runs, capture any open figures as base64 PNGs.
# The frontend splits on '__PG_IMG__' to render them inline.
PLOT_CAPTURE = (
    "\n\n# __auto_plot_capture__\n"
    "try:\n"
    "    import sys as __s\n"
    "    if 'matplotlib' in __s.modules:\n"
    "        import io as __io, base64 as __b64\n"
    "        import matplotlib.pyplot as __plt\n"
    "        for __n in __plt.get_fignums():\n"
    "            __f = __plt.figure(__n)\n"
    "            __buf = __io.BytesIO()\n"
    "            __f.savefig(__buf, format='png', bbox_inches='tight', dpi=92)\n"
    "            __buf.seek(0)\n"
    "            print('__PG_IMG__data:image/png;base64,' + __b64.b64encode(__buf.getvalue()).decode())\n"
    "        __plt.close('all')\n"
    "except Exception:\n"
    "    pass\n"
)

def prepare_code(code: str) -> str:
    prelude = []
    for pattern, import_stmt in AUTO_IMPORTS:
        if re.search(pattern, code):
            prelude.append(import_stmt)
    uses_mpl = re.search(r"\b(plt|pyplot|matplotlib)\b", code)
    head = ""
    if uses_mpl:
        head += MPL_PRELUDE
    if prelude:
        head += "\n".join(prelude) + "\n"
    body = (head + "\n" + code) if head else code
    if uses_mpl:
        body += PLOT_CAPTURE
    return body


@app.get("/")
def root():
    return {"status": "ok", "message": "ML Runner API — Python with PyTorch"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/run")
async def run_code(request: Request):
    body = await request.json()
    code = body.get("code", "").strip()

    if not code:
        return JSONResponse({"output": "", "error": "No code provided"})

    safe, reason = is_safe(code)
    if not safe:
        return JSONResponse({"output": "", "error": reason})

    # Auto-add imports + matplotlib headless setup + figure capture
    code = prepare_code(code)

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
                "MPLBACKEND": "Agg",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        output = result.stdout or ""
        error = result.stderr or ""

        # Trim very long tracebacks to the useful tail
        if error and len(error) > 2000:
            error = "\n".join(error.splitlines()[-20:])

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
