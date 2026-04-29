#!/usr/bin/env python3
"""
Monthly Exam Reminder Script
Sends email reminders to team members who haven't completed their monthly exam.
Run as a cron job on the 1st and 15th of each month.
"""

import sqlite3, json, os, requests
from datetime import datetime

DB_PATH = "/root/restosuite-exam/exam.db"
AGENTMAIL_INBOX = "Restosuite_Benedict@agentmail.to"

def load_api_key():
    """Load AgentMail API key from .env"""
    env_path = "/root/.hermes/profiles/benedict/.env"
    if not os.path.exists(env_path):
        return ""
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("AGENTMAIL_API_KEY="):
                return line.split("=", 1)[1]
    return ""

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_candidates_needing_reminder():
    """
    Find candidates who:
    - Have taken real exams this month but haven't passed
    - OR haven't taken any exams this month at all
    """
    conn = get_db()
    year_month = datetime.now().strftime("%Y-%m")
    
    # All candidates who have ever taken a real exam
    all_candidates = conn.execute(
        "SELECT DISTINCT candidate_name FROM exam_sessions "
        "WHERE candidate_name != '' AND is_mock = 0 "
        "ORDER BY candidate_name"
    ).fetchall()
    
    reminders = []
    for row in all_candidates:
        name = row["candidate_name"]
        
        # Check this month's real exams - passed?
        passed_this_month = conn.execute(
            "SELECT COUNT(*) as cnt FROM exam_results r "
            "JOIN exam_sessions s ON r.session_id = s.id "
            "WHERE s.candidate_name = ? AND s.is_mock = 0 "
            "AND r.passed = 1 AND r.completed_at LIKE ?",
            (name, f"{year_month}%")
        ).fetchone()["cnt"]
        
        if passed_this_month > 0:
            continue  # Already passed this month, skip
        
        # Check if they attempted this month
        attempted = conn.execute(
            "SELECT COUNT(*) as cnt FROM exam_sessions "
            "WHERE candidate_name = ? AND is_mock = 0 "
            "AND created_at LIKE ?",
            (name, f"{year_month}%")
        ).fetchone()["cnt"]
        
        # Get best score if attempted
        best_score = 0
        if attempted > 0:
            best = conn.execute(
                "SELECT MAX(r.score) as best FROM exam_results r "
                "JOIN exam_sessions s ON r.session_id = s.id "
                "WHERE s.candidate_name = ? AND s.is_mock = 0",
                (name,)
            ).fetchone()
            best_score = best["best"] if best and best["best"] else 0
        
        # Get department info (from most recent session)
        dept = conn.execute(
            "SELECT module FROM exam_sessions "
            "WHERE candidate_name = ? AND is_mock = 0 "
            "ORDER BY created_at DESC LIMIT 1",
            (name,)
        ).fetchone()
        
        reminders.append({
            "name": name,
            "attempted": attempted > 0,
            "best_score": best_score,
            "module": dept["module"] if dept else "Unknown",
            "year_month": year_month,
            "attempts_used": attempted
        })
    
    conn.close()
    return reminders

def send_reminder_email(candidates, api_key):
    """Send summary email to admin about candidates needing reminders."""
    if not candidates:
        print(f"[{datetime.now().isoformat()}] No candidates need reminders.")
        return
    
    year_month = datetime.now().strftime("%Y-%m")
    
    # Build email content
    total = len(candidates)
    attempted = [c for c in candidates if c["attempted"]]
    not_attempted = [c for c in candidates if not c["attempted"]]
    
    text_body = f"""Monthly Exam Reminder — {year_month}

Summary:
- Total candidates needing completion: {total}
- Attempted but not passed: {len(attempted)}
- Not yet attempted: {len(not_attempted)}

Candidates needing completion:
"""
    
    html_rows = ""
    for c in candidates:
        status = "❌ Failed" if c["attempted"] else "⚠️ Not Attempted"
        score = f"{c['best_score']}%" if c["attempted"] else "—"
        text_body += f"\n  {c['name']} | {status} | Best: {score}"
        html_rows += f"""
        <tr>
            <td style="padding:10px;border-bottom:1px solid #334155;font-weight:600;">{c['name']}</td>
            <td style="padding:10px;border-bottom:1px solid #334155;">
                {"<span style='color:#f87171;'>❌ Failed</span>" if c["attempted"] else "<span style='color:#eab308;'>⚠️ Not Attempted</span>"}
            </td>
            <td style="padding:10px;border-bottom:1px solid #334155;text-align:center;">{score}</td>
            <td style="padding:10px;border-bottom:1px solid #334155;text-align:center;">{c['attempts_used']}/2</td>
        </tr>"""
    
    text_body += f"\n\nPlease complete your exam at: https://www.restosuite.sg/training/"
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Monthly Exam Reminder</title></head>
<body style="margin:0;padding:20px;background-color:#0f172a;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background-color:#1e293b;border-radius:12px;overflow:hidden;border:1px solid #334155;">
<tr><td style="background:linear-gradient(135deg,#3b82f6,#2563eb);padding:28px 40px;">
<span style="color:#fff;font-size:22px;font-weight:bold;">RESTOSUITE</span>
<span style="color:#93c5fd;font-size:14px;margin-left:12px;">Training System</span>
</td></tr>
<tr><td style="padding:32px 40px;">
<h2 style="color:#60a5fa;margin:0 0 8px 0;">📅 Monthly Exam Reminder</h2>
<p style="color:#94a3b8;font-size:14px;margin:0 0 20px 0;">{year_month} — {total} team member(s) need to complete the exam</p>

<div style="background:#1e3a5f;border-left:4px solid #3b82f6;padding:16px 20px;margin:20px 0;border-radius:0 8px 8px 0;">
<p style="margin:0;color:#93c5fd;font-size:14px;font-weight:bold;">📊 Summary</p>
<p style="margin:8px 0 0 0;color:#94a3b8;font-size:13px;">
Attempted but not passed: <strong style="color:#f87171;">{len(attempted)}</strong><br>
Not yet attempted: <strong style="color:#eab308;">{len(not_attempted)}</strong>
</p>
</div>

<table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;">
<thead><tr style="background:#0f172a;">
<th style="padding:10px;text-align:left;color:#94a3b8;font-size:12px;">Name</th>
<th style="padding:10px;text-align:left;color:#94a3b8;font-size:12px;">Status</th>
<th style="padding:10px;text-align:center;color:#94a3b8;font-size:12px;">Best Score</th>
<th style="padding:10px;text-align:center;color:#94a3b8;font-size:12px;">Attempts</th>
</tr></thead>
<tbody>{html_rows}</tbody>
</table>

<div style="text-align:center;margin:28px 0;">
<a href="https://www.restosuite.sg/training/"
   style="display:inline-block;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;text-decoration:none;padding:12px 28px;border-radius:6px;font-size:15px;font-weight:bold;">
  Take Exam Now →
</a>
</div>
</td></tr>
<tr><td style="background:#0f172a;padding:20px 40px;border-top:1px solid #334155;">
<p style="margin:0;font-size:11px;color:#64748b;">
RestoSuite Private Limited<br>
7 Holland Village Way, #05-03/05, Singapore 275748<br>
This is an automated reminder from the Training System.
</p>
</td></tr>
</table>
</td></tr></table>
</body>
</html>"""

    # Send via AgentMail
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": [AGENTMAIL_INBOX],
        "subject": f"📅 Monthly Exam Reminder — {year_month} ({total} pending)",
        "text": text_body,
        "html": html
    }
    
    try:
        resp = requests.post(
            f"https://api.agentmail.to/v0/inboxes/{AGENTMAIL_INBOX}/messages/send",
            headers=headers,
            json=payload,
            timeout=30
        )
        if resp.status_code == 200:
            print(f"[{datetime.now().isoformat()}] Reminder sent successfully. {total} candidates notified.")
        else:
            print(f"[{datetime.now().isoformat()}] Failed to send: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Error sending email: {e}")

def main():
    api_key = load_api_key()
    if not api_key:
        print(f"[{datetime.now().isoformat()}] ERROR: No API key found.")
        return
    
    candidates = get_candidates_needing_reminder()
    send_reminder_email(candidates, api_key)

if __name__ == "__main__":
    main()
