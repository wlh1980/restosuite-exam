from fastapi import FastAPI, Request, HTTPException, Response, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
import jinja2
import json
import random
import string
import sqlite3
import hashlib
import os
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

app = FastAPI(title="RestoSuite Exam System")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    autoescape=jinja2.select_autoescape(['html', 'xml'])
)

def render_template(name, **context):
    template = jinja_env.get_template(name)
    return HTMLResponse(content=template.render(**context))

# Database setup
DB_PATH = os.getenv("RESTOSUITE_EXAM_DB", os.path.join(BASE_DIR, "exam.db"))
QUESTION_BANK_PATH = os.getenv(
    "RESTOSUITE_QUESTION_BANK",
    os.path.join(BASE_DIR, "question_bank_final_v2.json")
)

MONTHLY_ATTEMPT_LIMIT = 2  # Max exams per candidate per month

# Department → modules mapping
DEPARTMENT_MODULES = {
    "sales": ["Marketing", "POS"],
    "implementation": ["POS", "KDS", "Supply Chain", "Singapore/Malaysia Localization"],
    "customer_service": ["POS", "KDS", "Singapore/Malaysia Localization"],
}
DEPARTMENT_LABELS = {
    "sales": "Sales / 销售",
    "implementation": "Implementation / 实施",
    "customer_service": "Customer Service / 客服",
}

# Admin credentials for dashboard
ADMIN_USERNAME = os.getenv("RESTOSUITE_EXAM_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("RESTOSUITE_EXAM_ADMIN_PASSWORD", "Resto2026!")
ADMIN_SESSION_SECRET = os.getenv("RESTOSUITE_EXAM_SESSION_SECRET", ADMIN_PASSWORD)
ADMIN_SESSION_COOKIE = "rs_exam_admin"
security = HTTPBasic(auto_error=False)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS exam_sessions (
        id TEXT PRIMARY KEY,
        exam_url TEXT UNIQUE,
        candidate_name TEXT DEFAULT '',
        module TEXT,
        difficulty TEXT,
        num_questions INTEGER,
        duration_minutes INTEGER,
        pass_rate REAL,
        questions_json TEXT,
        created_at TEXT,
        expires_at TEXT,
        is_completed INTEGER DEFAULT 0,
        is_mock INTEGER DEFAULT 0
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS exam_results (
        session_id TEXT PRIMARY KEY,
        answers_json TEXT,
        score REAL,
        total_questions INTEGER,
        correct_answers INTEGER,
        passed INTEGER,
        completed_at TEXT,
        FOREIGN KEY (session_id) REFERENCES exam_sessions(id)
    )''')
    # Migrations
    for col_def in ["candidate_name TEXT DEFAULT ''", "is_mock INTEGER DEFAULT 0"]:
        try:
            conn.execute(f"ALTER TABLE exam_sessions ADD COLUMN {col_def}")
        except Exception:
            pass
    conn.commit()
    conn.close()

def load_question_bank():
    with open(QUESTION_BANK_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_token():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_hash = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
    return f"{timestamp}-{random_hash}"

def generate_exam_url():
    random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"exam-{random_id}"

def get_monthly_attempts(candidate_name: str, year_month: str) -> int:
    """Count real (non-mock) exams a candidate has started this month."""
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM exam_sessions WHERE candidate_name = ? AND created_at LIKE ? AND is_mock = 0",
        (candidate_name, f"{year_month}%")
    ).fetchone()["cnt"]
    conn.close()
    return count

def get_monthly_mock_attempts(candidate_name: str, year_month: str) -> int:
    """Count mock exams a candidate has started this month."""
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM exam_sessions WHERE candidate_name = ? AND created_at LIKE ? AND is_mock = 1",
        (candidate_name, f"{year_month}%")
    ).fetchone()["cnt"]
    conn.close()
    return count

def get_candidate_monthly_stats(candidate_name: str) -> list:
    """
    Return list of monthly stats for a candidate, sorted by month desc.
    Each item: { year_month, attempts, passed_any, all_failed }
    """
    conn = get_db()
    rows = conn.execute("""
        SELECT s.id, s.created_at, s.candidate_name, r.passed, r.score
        FROM exam_sessions s
        LEFT JOIN exam_results r ON s.id = r.session_id
        WHERE s.candidate_name = ? AND s.is_completed = 1 AND s.is_mock = 0
        ORDER BY s.created_at DESC
    """, (candidate_name,)).fetchall()
    conn.close()

    monthly = defaultdict(lambda: {"attempts": 0, "passed_any": False, "scores": []})
    for row in rows:
        ym = row["created_at"][:7]  # "2026-04"
        monthly[ym]["attempts"] += 1
        if row["passed"]:
            monthly[ym]["passed_any"] = True
        if row["score"] is not None:
            monthly[ym]["scores"].append(row["score"])

    result = []
    for ym, data in sorted(monthly.items(), reverse=True):
        result.append({
            "year_month": ym,
            "attempts": data["attempts"],
            "passed_any": data["passed_any"],
            "all_failed": not data["passed_any"],
            "best_score": max(data["scores"]) if data["scores"] else 0
        })
    return result

def get_consecutive_failed_months(monthly_stats: list) -> int:
    """Count how many consecutive months (most recent first) candidate failed ALL attempts."""
    count = 0
    for m in monthly_stats:
        if m["all_failed"]:
            count += 1
        else:
            break
    return count

def get_alert_level(consecutive_months: int, failed_this_month: bool) -> dict:
    """Return alert info based on consecutive failed months."""
    if consecutive_months >= 3:
        return {
            "level": "termination",
            "color": "red",
            "icon": "🚨",
            "label_en": "TERMINATION WARNING",
            "label_zh": "辞退警告",
            "msg_en": f"Failed all attempts for {consecutive_months} consecutive months. Initiate termination process.",
            "msg_zh": f"连续 {consecutive_months} 个月未通过，按规定需启动辞退程序。"
        }
    elif consecutive_months == 2:
        return {
            "level": "written_warning",
            "color": "orange",
            "icon": "⚠️",
            "label_en": "WRITTEN WARNING",
            "label_zh": "书面警告",
            "msg_en": "Failed all attempts for 2 consecutive months. Issue a written warning.",
            "msg_zh": "连续 2 个月未通过，需发出书面警告书。"
        }
    elif consecutive_months == 1 and failed_this_month:
        return {
            "level": "study_required",
            "color": "yellow",
            "icon": "📚",
            "label_en": "STUDY REQUIRED",
            "label_zh": "需加班学习",
            "msg_en": "Failed both attempts this month. Candidate must complete additional study.",
            "msg_zh": "本月两次均未通过，需安排加班学习。"
        }
    return None

# Candidate level detection
CANDIDATE_LEVELS = {
    "not_started": {"label_en": "Not Started", "label_zh": "未开始", "icon": "⚪"},
    "entry": {"label_en": "Entry Level", "label_zh": "入门级", "icon": "🟡"},
    "certified": {"label_en": "Certified", "label_zh": "已认证", "icon": "🟢"},
}

def get_candidate_level(candidate_name: str) -> dict:
    """Determine a candidate's level based on exam history.
    
    Returns:
        { "level": "not_started"|"entry"|"certified", "first_pass_date": str|None, "best_score": float|None }
    """
    conn = get_db()
    # Check if they've ever passed a real exam
    passed_row = conn.execute(
        "SELECT r.completed_at, r.score FROM exam_results r "
        "JOIN exam_sessions s ON r.session_id = s.id "
        "WHERE s.candidate_name = ? AND s.is_mock = 0 AND r.passed = 1 "
        "ORDER BY r.completed_at ASC LIMIT 1",
        (candidate_name,)
    ).fetchone()
    
    # Check if they've ever taken a real exam
    attempted = conn.execute(
        "SELECT COUNT(*) as cnt FROM exam_sessions "
        "WHERE candidate_name = ? AND is_mock = 0",
        (candidate_name,)
    ).fetchone()["cnt"]
    
    # Get best score
    best = conn.execute(
        "SELECT MAX(r.score) as best FROM exam_results r "
        "JOIN exam_sessions s ON r.session_id = s.id "
        "WHERE s.candidate_name = ? AND s.is_mock = 0",
        (candidate_name,)
    ).fetchone()
    conn.close()
    
    if passed_row:
        return {
            "level": "certified",
            "label_en": "Certified",
            "label_zh": "已认证",
            "icon": "🟢",
            "first_pass_date": passed_row["completed_at"][:10] if passed_row["completed_at"] else "N/A",
            "first_pass_score": passed_row["score"],
            "best_score": best["best"] if best and best["best"] else 0
        }
    elif attempted > 0:
        return {
            "level": "entry",
            "label_en": "Entry Level",
            "label_zh": "入门级",
            "icon": "🟡",
            "first_pass_date": None,
            "first_pass_score": None,
            "best_score": best["best"] if best and best["best"] else 0
        }
    else:
        return {
            "level": "not_started",
            "label_en": "Not Started",
            "label_zh": "未开始",
            "icon": "⚪",
            "first_pass_date": None,
            "first_pass_score": None,
            "best_score": 0
        }

def get_all_candidates() -> list:
    """Return all unique candidate names who have taken real exams."""
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT candidate_name FROM exam_sessions "
        "WHERE candidate_name != '' AND is_mock = 0 "
        "ORDER BY candidate_name"
    ).fetchall()
    conn.close()
    return [r["candidate_name"] for r in rows]

def verify_admin(credentials: HTTPBasicCredentials):
    """Verify admin login credentials. Returns True if valid."""
    if credentials is None:
        return False
    # Constant-time comparison to prevent timing attacks
    user_ok = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    pass_ok = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    return user_ok and pass_ok

def _admin_signature(username: str, expires_at: str) -> str:
    payload = f"{username}|{expires_at}|{ADMIN_SESSION_SECRET}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def create_admin_session_value(username: str) -> str:
    expires_at = (datetime.utcnow() + timedelta(hours=12)).isoformat()
    signature = _admin_signature(username, expires_at)
    return f"{username}|{expires_at}|{signature}"

def verify_admin_cookie(request: Request) -> bool:
    raw = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    try:
        username, expires_at, signature = raw.split("|", 2)
        if datetime.utcnow() > datetime.fromisoformat(expires_at):
            return False
        expected = _admin_signature(username, expires_at)
        return (
            secrets.compare_digest(username, ADMIN_USERNAME) and
            secrets.compare_digest(signature, expected)
        )
    except Exception:
        return False

def verify_admin_request(request: Request, credentials: Optional[HTTPBasicCredentials]) -> bool:
    return verify_admin(credentials) or verify_admin_cookie(request)

def _create_exam_session(candidate_name: str, module: str, difficulty: str,
                          num_questions: int, duration_minutes: int, pass_rate: float,
                          is_mock: bool = False):
    """Core logic: pick questions, save session, return (exam_url, token, expires)."""
    bank = load_question_bank()
    all_questions = bank["questions"]

    if module != "all":
        # Support comma-separated multi-module (for department filtering)
        if "," in module:
            mods = [m.strip() for m in module.split(",")]
            all_questions = [q for q in all_questions if q.get("module", "") in mods]
        else:
            all_questions = [q for q in all_questions if q.get("module", "").lower() == module.lower()]
    if difficulty != "all":
        all_questions = [q for q in all_questions if q.get("difficulty", "").lower() == difficulty.lower()]

    if len(all_questions) < num_questions:
        # If not enough, use all available
        num_questions = len(all_questions)
    if num_questions == 0:
        raise HTTPException(status_code=400, detail="No questions available for this selection.")

    selected = random.sample(all_questions, num_questions)
    for q in selected:
        opts = q["options"]
        keys = list(opts.keys())
        random.shuffle(keys)
        q["options"] = {k: opts[k] for k in keys}

    exam_url = generate_exam_url()
    token = generate_token()

    conn = get_db()
    now = datetime.now()
    expires = now + timedelta(hours=24)
    conn.execute(
        "INSERT INTO exam_sessions (id, exam_url, candidate_name, module, difficulty, num_questions, duration_minutes, pass_rate, questions_json, created_at, expires_at, is_mock) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (token, exam_url, candidate_name, module, difficulty, num_questions, duration_minutes, pass_rate,
         json.dumps(selected, ensure_ascii=False), now.isoformat(), expires.isoformat(), int(is_mock))
    )
    conn.commit()
    conn.close()
    return exam_url, token, expires

@app.get("/", response_class=HTMLResponse)
async def index():
    response = render_template("index.html")
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response

@app.get("/robots.txt")
async def robots_txt():
    return Response(content="User-agent: *\nDisallow: /\n", media_type="text/plain")

@app.post("/start-exam")
async def start_exam(request: Request):
    form_data = await request.form()
    candidate_name = form_data.get("candidate_name", "").strip()
    department = form_data.get("department", "").strip()
    exam_type = form_data.get("exam_type", "real")  # "real" or "mock"
    duration_minutes = 30
    pass_rate = 80.0  # Fixed

    if not candidate_name:
        response = render_template("index.html", error_en="Please enter your name.", error_zh="请输入姓名。")
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    if not department or department not in DEPARTMENT_MODULES:
        response = render_template("index.html", error_en="Please select your department.", error_zh="请选择所在部门。")
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    # Build module filter from department
    dept_modules = DEPARTMENT_MODULES[department]
    module_filter = ",".join(dept_modules)
    dept_label = DEPARTMENT_LABELS[department]

    is_mock = (exam_type == "mock")

    year_month = datetime.now().strftime("%Y-%m")

    if is_mock:
        # Mock exam: 20 questions, no time limit, unlimited attempts, not recorded in results
        num_questions = 20
        mock_duration = 0  # 0 = no time limit
        exam_url, token, expires = _create_exam_session(
            candidate_name, module_filter, "all", num_questions, mock_duration, pass_rate, is_mock=True
        )
        return RedirectResponse(url=f"/training/{exam_url}?token={token}", status_code=303)

    # Real exam: check 24-hour cooldown after mock exam
    conn = get_db()
    last_mock = conn.execute(
        "SELECT created_at FROM exam_sessions WHERE candidate_name = ? AND is_mock = 1 ORDER BY created_at DESC LIMIT 1",
        (candidate_name,)
    ).fetchone()
    conn.close()
    if last_mock:
        last_mock_time = datetime.fromisoformat(last_mock["created_at"])
        hours_since_mock = (datetime.now() - last_mock_time).total_seconds() / 3600
        if hours_since_mock < 24:
            hours_left = int(24 - hours_since_mock) + 1
            response = render_template("index.html",
                error_en=f"You must wait 24 hours after completing the mock exam before taking the official exam. Please try again in about {hours_left} hour(s).",
                error_zh=f"模拟考试完成后需等待 24 小时才能参加正式考试，请约 {hours_left} 小时后再试。"
            )
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
            return response

    # Real exam: check monthly limit
    attempts_this_month = get_monthly_attempts(candidate_name, year_month)
    if attempts_this_month >= MONTHLY_ATTEMPT_LIMIT:
        response = render_template("index.html",
            error_en=f"You have used both exam attempts for this month ({year_month}). Please try again next month.",
            error_zh=f"您本月（{year_month}）的两次考试机会已用完，请下月再试。"
        )
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    # Auto-determine question count: 1st attempt = 30, 2nd = 50
    num_questions = 30 if attempts_this_month == 0 else 50

    exam_url, token, expires = _create_exam_session(
        candidate_name, module_filter, "all", num_questions, duration_minutes, pass_rate, is_mock=False
    )
    return RedirectResponse(url=f"/training/{exam_url}?token={token}", status_code=303)

@app.get("/generate-exam")
async def generate_exam(
    module: str = "all",
    difficulty: str = "all",
    num_questions: int = 20,
    duration_minutes: int = 30,
    pass_rate: float = 80.0,
    name: str = ""
):
    exam_url, token, expires = _create_exam_session(
        name, module, difficulty, num_questions, duration_minutes, pass_rate
    )
    full_url = f"/training/{exam_url}?token={token}"
    return {
        "exam_url": full_url,
        "full_url": f"https://www.restosuite.sg{full_url}",
        "candidate_name": name,
        "expires_at": expires.isoformat(),
        "num_questions": num_questions,
        "duration_minutes": duration_minutes,
        "pass_rate": pass_rate
    }

def _render_exam_page(exam_url: str, token: str):
    conn = get_db()
    session = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (token,)).fetchone()
    conn.close()

    if not session:
        response = render_template("error.html", error="Invalid exam link. Please contact your administrator.")
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    expires_at = datetime.fromisoformat(session["expires_at"])
    if datetime.now() > expires_at:
        response = render_template("error.html", error="This exam link has expired. Please request a new one.")
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    questions = json.loads(session["questions_json"])
    candidate_name = session["candidate_name"] or ""
    is_mock = bool(session["is_mock"])

    response = render_template("exam.html", token=token, questions=questions,
                                duration_minutes=session["duration_minutes"],
                                num_questions=session["num_questions"],
                                exam_url=exam_url,
                                candidate_name=candidate_name,
                                is_mock=is_mock)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response

@app.get("/training/{exam_url}")
async def exam_page(exam_url: str, token: str):
    return _render_exam_page(exam_url, token)

@app.get("/{exam_url}")
async def exam_page_short(exam_url: str, token: str):
    if not exam_url.startswith("exam-"):
        raise HTTPException(status_code=404, detail="Not Found")
    return _render_exam_page(exam_url, token)

@app.post("/submit-exam")
async def submit_exam(request: Request):
    form_data = await request.form()
    token = form_data.get("token")

    conn = get_db()
    session = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (token,)).fetchone()

    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Exam session not found")

    questions = json.loads(session["questions_json"])
    answers = {}
    correct = 0

    for i, q in enumerate(questions):
        answer = form_data.get(f"q_{i}", "")
        answers[f"q_{i}"] = answer
        if answer == q["correct_answer"]:
            correct += 1

    total = len(questions)
    score = round((correct / total) * 100, 1) if total > 0 else 0
    passed = score >= session["pass_rate"]
    is_mock = bool(session["is_mock"])

    now = datetime.now()

    if not is_mock:
        # Only save results for real exams (mock results shown via session questions)
        conn.execute(
            "INSERT OR REPLACE INTO exam_results (session_id, answers_json, score, total_questions, correct_answers, passed, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token, json.dumps(answers), score, total, correct, int(passed), now.isoformat())
        )
    else:
        # Save mock exam results too so the result page can display actual score
        conn.execute(
            "INSERT OR REPLACE INTO exam_results (session_id, answers_json, score, total_questions, correct_answers, passed, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token, json.dumps(answers), score, total, correct, int(passed), now.isoformat())
        )
    conn.execute("UPDATE exam_sessions SET is_completed = 1 WHERE id = ?", (token,))
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/training/result/{token}", status_code=303)

@app.get("/result/{token}", response_class=HTMLResponse)
async def result_page(token: str):
    conn = get_db()
    session = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (token,)).fetchone()
    conn.close()

    if not session:
        response = render_template("error.html", error="Results not found.")
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    is_mock = bool(session["is_mock"])
    questions = json.loads(session["questions_json"])
    candidate_name = session["candidate_name"] or ""

    # For mock: compute answers from submitted data in session (re-grade from form)
    # We store answers temporarily in session for mock; just show score from DB
    conn = get_db()
    result = conn.execute("SELECT * FROM exam_results WHERE session_id = ?", (token,)).fetchone()
    conn.close()

    if not is_mock and not result:
        response = render_template("error.html", error="Results not found.")
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    # For mock exams without saved result, re-render a simple page
    if is_mock and not result:
        response = render_template("result.html",
                                    token=token,
                                    candidate_name=candidate_name,
                                    is_mock=True,
                                    questions=questions,
                                    answers={},
                                    score=0,
                                    total_questions=session["num_questions"],
                                    correct_answers=0,
                                    passed=False,
                                    pass_rate=session["pass_rate"],
                                    weak_modules=[],
                                    module_stats={},
                                    attempts_remaining=None,
                                    year_month="")
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    answers = json.loads(result["answers_json"])

    # Module performance analysis
    module_stats = {}
    for i, q in enumerate(questions):
        mod = q.get("module", "General")
        user_ans = answers.get(f"q_{i}", "")
        if mod not in module_stats:
            module_stats[mod] = {"total": 0, "correct": 0}
        module_stats[mod]["total"] += 1
        if user_ans == q["correct_answer"]:
            module_stats[mod]["correct"] += 1

    weak_modules = []
    for mod, stats in module_stats.items():
        pct = round(stats["correct"] / stats["total"] * 100) if stats["total"] else 0
        if pct < 80:
            weak_modules.append({"module": mod, "score": pct,
                                  "correct": stats["correct"], "total": stats["total"]})
    weak_modules.sort(key=lambda x: x["score"])

    year_month = datetime.now().strftime("%Y-%m")
    attempts_used = get_monthly_attempts(candidate_name, year_month)
    attempts_remaining = max(0, MONTHLY_ATTEMPT_LIMIT - attempts_used) if not is_mock else None

    response = render_template("result.html",
                                token=token,
                                candidate_name=candidate_name,
                                is_mock=is_mock,
                                questions=questions,
                                answers=answers,
                                score=result["score"],
                                total_questions=result["total_questions"],
                                correct_answers=result["correct_answers"],
                                passed=bool(result["passed"]),
                                pass_rate=session["pass_rate"],
                                weak_modules=weak_modules,
                                module_stats=module_stats,
                                attempts_remaining=attempts_remaining,
                                year_month=year_month)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response

@app.get("/admin/results", response_class=HTMLResponse)
async def admin_results(request: Request, credentials: HTTPBasicCredentials = Depends(security)):
    if not verify_admin_request(request, credentials):
        auth_error = credentials is not None
        response = render_template("admin.html", login_required=True, auth_error=auth_error)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.status_code = 401
        return response

    # --- Authenticated: show dashboard ---
    conn = get_db()
    results = conn.execute("""
        SELECT r.*, s.module, s.difficulty, s.num_questions, s.created_at, s.candidate_name
        FROM exam_results r
        JOIN exam_sessions s ON r.session_id = s.id
        ORDER BY r.completed_at DESC
    """).fetchall()
    conn.close()

    candidate_names = list(dict.fromkeys(
        r["candidate_name"] for r in results if r["candidate_name"]
    ))

    candidate_alerts = {}
    for name in candidate_names:
        monthly_stats = get_candidate_monthly_stats(name)
        consec = get_consecutive_failed_months(monthly_stats)
        year_month = datetime.now().strftime("%Y-%m")
        this_month = next((m for m in monthly_stats if m["year_month"] == year_month), None)
        failed_both_this_month = (
            this_month and
            this_month["all_failed"] and
            this_month["attempts"] >= MONTHLY_ATTEMPT_LIMIT
        )
        alert = get_alert_level(consec, failed_both_this_month)
        attempts_this_month = get_monthly_attempts(name, year_month)
        level_info = get_candidate_level(name)
        mock_count = get_monthly_mock_attempts(name, year_month)

        candidate_alerts[name] = {
            "alert": alert,
            "consecutive_failed_months": consec,
            "attempts_this_month": attempts_this_month,
            "attempts_remaining": max(0, MONTHLY_ATTEMPT_LIMIT - attempts_this_month),
            "monthly_stats": monthly_stats[:3],
            "level": level_info,
            "mock_attempts_this_month": mock_count,
        }

    response = render_template("admin.html",
                                results=results,
                                candidate_alerts=candidate_alerts,
                                monthly_limit=MONTHLY_ATTEMPT_LIMIT,
                                login_required=False)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response

@app.post("/admin/login")
async def admin_login(request: Request):
    form = await request.form()
    user = form.get("username", "").strip()
    pwd = form.get("password", "").strip()
    if (secrets.compare_digest(user, ADMIN_USERNAME) and
        secrets.compare_digest(pwd, ADMIN_PASSWORD)):
        response = RedirectResponse(url="/training/admin/results", status_code=303)
        response.set_cookie(
            ADMIN_SESSION_COOKIE,
            create_admin_session_value(user),
            max_age=12 * 60 * 60,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
        )
        return response
    response = render_template("admin.html", login_required=True, auth_error=True)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response

@app.on_event("startup")
async def startup():
    init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8500)
