"""
Web Dashboard sử dụng FastAPI + Jinja2.
"""

import os
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import uvicorn

import database
from worker import start_worker, stop_worker, get_worker, get_running_accounts

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Discord Quest Bot — Dashboard")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", "henxi-secret-key-change-me"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ── Auth guard ─────────────────────────────────────────────────────────────────

ADMIN_USER = os.environ.get("DASHBOARD_USER", "admin")
ADMIN_PASS = os.environ.get("DASHBOARD_PASS", "admin123")


def auth_check(request: Request) -> bool:
    return request.session.get("authenticated", False)


def require_auth(request: Request):
    if not auth_check(request):
        raise HTTPException(401, "Unauthorized")


# ── Context processor ─────────────────────────────────────────────────────────

def build_context(request: Request, active_page: str = "dashboard", extra: dict = None):
    running = get_running_accounts()
    stats = database.get_stats()
    ctx = {
        "request": request,
        "active_page": active_page,
        "stats": stats,
        "running_accounts": running,
        "authenticated": auth_check(request),
    }
    if extra:
        ctx.update(extra)
    return ctx


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    error = request.session.pop("login_error", None)
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error
    })


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=303)
    request.session["login_error"] = "Sai tài khoản hoặc mật khẩu"
    return RedirectResponse(url="/login", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ── Main pages ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not auth_check(request):
        return RedirectResponse(url="/login")
    accounts = database.get_all_accounts()
    running_ids = {w["user_id"] for w in get_running_accounts()}
    stats = database.get_stats()
    recent_logs = stats.get("recent_logs", [])
    return templates.TemplateResponse("dashboard.html", build_context(
        request, "dashboard",
        {
            "accounts": accounts,
            "running_ids": running_ids,
            "recent_logs": recent_logs,
        }
    ))


@app.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request):
    if not auth_check(request):
        return RedirectResponse(url="/login")
    accounts = database.get_all_accounts()
    running_ids = {w["user_id"] for w in get_running_accounts()}
    return templates.TemplateResponse("accounts.html", build_context(
        request, "accounts",
        {"accounts": accounts, "running_ids": running_ids}
    ))


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    if not auth_check(request):
        return RedirectResponse(url="/login")
    logs = database.get_quest_logs(limit=200)
    return templates.TemplateResponse("logs.html", build_context(
        request, "logs", {"logs": logs}
    ))


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    if not auth_check(request):
        return RedirectResponse(url="/login")
    stats = database.get_stats()
    return templates.TemplateResponse("settings.html", build_context(
        request, "settings"
    ))


# ── API actions ────────────────────────────────────────────────────────────────

@app.post("/api/add-account")
async def api_add(token: str = Form(...)):
    if not token or len(token) < 50:
        return {"success": False, "error": "Token không hợp lệ"}
    try:
        token_id = database.add_account(token)
        return {"success": True, "token_id": token_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/remove-account")
async def api_remove(user_id: str = Form(...)):
    ok = database.remove_account(user_id)
    stop_worker(user_id)
    return {"success": ok}


@app.post("/api/start-worker")
async def api_start(
    user_id: str = Form(...),
    poll_interval: int = Form(60),
    auto_accept: bool = Form(True)
):
    accounts = database.get_all_accounts()
    account = next((a for a in accounts if a.get("user_id") == user_id), None)
    if not account:
        return {"success": False, "error": "Không tìm thấy tài khoản"}
    if get_worker(user_id):
        return {"success": False, "error": "Worker đang chạy"}
    try:
        start_worker(
            account["token"], user_id,
            account.get("username") or user_id,
            poll_interval, auto_accept
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/stop-worker")
async def api_stop(user_id: str = Form(...)):
    if not get_worker(user_id):
        return {"success": False, "error": "Worker không chạy"}
    stop_worker(user_id)
    return {"success": True}


@app.get("/api/status")
async def api_status():
    running = get_running_accounts()
    stats = database.get_stats()
    return {
        "running": running,
        "stats": stats,
    }


# ── Run standalone ─────────────────────────────────────────────────────────────

def run_dashboard(host: str = "0.0.0.0", port: int = 8000):
    uvicorn.run(app, host=host, port=port)
