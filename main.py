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
