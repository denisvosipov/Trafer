# ==========================
# File: app.py
# Run with: streamlit run app.py
# ==========================
import streamlit as st
import sqlite3
import json
import hashlib
import datetime
from typing import List, Dict, Any, Optional

DB_PATH = 'app.db'

# ---------------
# Utilities
# ---------------

def set_page(new_page: str):
    st.session_state.page = new_page


def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Users: minimal auth (teacher / pupil)
    c.execute(
        '''CREATE TABLE IF NOT EXISTS users (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               role TEXT NOT NULL CHECK(role IN ("teacher","pupil")),
               name TEXT NOT NULL,
               email TEXT UNIQUE NOT NULL,
               password_hash TEXT NOT NULL
           );'''
    )

    # Problems
    c.execute(
        '''CREATE TABLE IF NOT EXISTS problems (
               id TEXT PRIMARY KEY,                -- e.g. "MATH101"
               content TEXT NOT NULL,             -- HTML/Markdown allowed
               answer_type TEXT NOT NULL CHECK(answer_type IN ("single","table")),
               answer_json TEXT NOT NULL,         -- JSON: string or [[...]]
               created_by INTEGER,
               updated_at TEXT
           );'''
    )

    # Papers (collections of problem ids)
    c.execute(
        '''CREATE TABLE IF NOT EXISTS papers (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               problem_ids_json TEXT NOT NULL,    -- JSON array of strings
               mode TEXT NOT NULL CHECK(mode IN ("training","test1","test2")),
               show_problem_ids INTEGER NOT NULL CHECK(show_problem_ids IN (0,1)),
               created_by INTEGER,
               created_at TEXT
           );'''
    )

    # Submissions (per paper & pupil & attempt)
    c.execute(
        '''CREATE TABLE IF NOT EXISTS submissions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               paper_id INTEGER NOT NULL,
               pupil_id INTEGER NOT NULL,
               answers_json TEXT NOT NULL,              -- {problem_id: answer or [[...]]}
               score REAL NOT NULL,                     -- percentage 0..100
               attempt_no INTEGER NOT NULL,
               submitted_at TEXT
           );'''
    )

    conn.commit()
    conn.close()


def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode('utf-8')).hexdigest()


# ---------------
# Auth helpers
# ---------------

def ensure_demo_users():
    """Create one teacher and two pupils if not existing, to help first run."""
    conn = get_conn()
    c = conn.cursor()
    # check if any user exists
    c.execute('SELECT COUNT(*) FROM users')
    (cnt,) = c.fetchone()
    if cnt == 0:
        users = [
            ("teacher", "Teacher One", "teacher@example.com", hash_pw("teach123")),
            ("pupil", "Pupil Alice", "alice@example.com", hash_pw("alice123")),
            ("pupil", "Pupil Bob", "bob@example.com", hash_pw("bob123")),
        ]
        c.executemany('INSERT INTO users(role,name,email,password_hash) VALUES (?,?,?,?)', users)
        conn.commit()
    conn.close()


def login_form():
    # Kept for compatibility (unused in new header-based UI)
    st.sidebar.subheader("Sign in")
    email = st.sidebar.text_input("Email", key="login_email")
    pw = st.sidebar.text_input("Password", type="password", key="login_pw")
    if st.sidebar.button("Sign in"):
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT id, role, name, email, password_hash FROM users WHERE email = ?', (email,))
        row = c.fetchone()
        conn.close()
        if row and row[4] == hash_pw(pw):
            st.session_state.user = {"id": row[0], "role": row[1], "name": row[2], "email": row[3]}
            st.success(f"Signed in as {row[2]} ({row[1]})")
        else:
            st.error("Invalid credentials")

def login_form_main():
    st.subheader("Sign in")
    email = st.text_input("Email", key="login_email_main")
    pw = st.text_input("Password", type="password", key="login_pw_main")
    if st.button("Sign in", key="signin_main"):
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT id, role, name, email, password_hash FROM users WHERE email = ?', (email,))
        row = c.fetchone()
        conn.close()
        if row and row[4] == hash_pw(pw):
            st.session_state.user = {"id": row[0], "role": row[1], "name": row[2], "email": row[3]}
            set_page("Home")
            st.rerun()
        else:
            st.error("Invalid credentials")

def require_auth(role: str = None) -> Optional[Dict[str, Any]]:
    user = st.session_state.get("user")
    if not user:
        st.info("Please sign in using the header.")
        return None
    if role and user["role"] != role:
        st.error(f"This section is for {role}s only.")
        return None
    return user


# ---------------
# Problem helpers
# ---------------

def get_problem(pid: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id, content, answer_type, answer_json, updated_at FROM problems WHERE id = ?', (pid,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        'id': row[0], 'content': row[1], 'answer_type': row[2],
        'answer': json.loads(row[3]), 'updated_at': row[4]
    }


def save_problem(pid: str, content_html_md: str, answer_type: str, answer):
    now = datetime.datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO problems(id, content, answer_type, answer_json, created_by, updated_at)\
               VALUES(?, ?, ?, ?, COALESCE((SELECT created_by FROM problems WHERE id = ?), ?), ?)',
              (pid, content_html_md, answer_type, json.dumps(answer), pid, st.session_state.user['id'], now))
    conn.commit()
    conn.close()


# ---------------
# Paper helpers
# ---------------

def get_paper(paper_id: int) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id, title, problem_ids_json, mode, show_problem_ids, created_by, created_at FROM papers WHERE id = ?', (paper_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        'id': row[0], 'title': row[1], 'problem_ids': json.loads(row[2]), 'mode': row[3],
        'show_problem_ids': bool(row[4]), 'created_by': row[5], 'created_at': row[6]
    }


def create_paper(title: str, problem_ids: List[str], mode: str, show_ids: bool):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT INTO papers(title, problem_ids_json, mode, show_problem_ids, created_by, created_at) VALUES(?,?,?,?,?,?)',
              (title, json.dumps(problem_ids), mode, 1 if show_ids else 0, st.session_state.user['id'], datetime.datetime.utcnow().isoformat()))
    conn.commit()
    pid = c.lastrowid
    conn.close()
    return pid


# ---------------
# Submissions
# ---------------


def record_submission(paper_id: int, pupil_id: int, answers: Dict[str, Any], score: float, attempt_no: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT INTO submissions(paper_id, pupil_id, answers_json, score, attempt_no, submitted_at) VALUES(?,?,?,?,?,?)',
              (paper_id, pupil_id, json.dumps(answers), score, attempt_no, datetime.datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_attempt_count(paper_id: int, pupil_id: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM submissions WHERE paper_id=? AND pupil_id=?', (paper_id, pupil_id))
    (cnt,) = c.fetchone()
    conn.close()
    return cnt


def get_teacher_logs():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT s.id, s.paper_id, u.name, u.email, s.score, s.attempt_no, s.submitted_at
                 FROM submissions s JOIN users u ON s.pupil_id = u.id
                 ORDER BY s.submitted_at DESC LIMIT 200''')
    rows = c.fetchall()
    conn.close()
    return rows

def get_pupil_attempts(pupil_id: int):
    """Returns list of (submitted_at, paper_id, paper_title, mode, score, attempt_no)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT s.submitted_at, p.id, p.title, p.mode, s.score, s.attempt_no
                 FROM submissions s JOIN papers p ON s.paper_id = p.id
                 WHERE s.pupil_id = ?
                 ORDER BY s.submitted_at DESC''', (pupil_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_problem_count_for_papers(paper_ids: List[int]) -> Dict[int, int]:
    if not paper_ids:
        return {}
    placeholders = ','.join(['?']*len(paper_ids))
    conn = get_conn()
    c = conn.cursor()
    c.execute(f'SELECT id, problem_ids_json FROM papers WHERE id IN ({placeholders})', tuple(paper_ids))
    res = {row[0]: len(json.loads(row[1])) for row in c.fetchall()}
    conn.close()
    return res

def get_attempt_counts_by_paper(pupil_id: int) -> Dict[int, int]:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT paper_id, COUNT(*) FROM submissions WHERE pupil_id = ? GROUP BY paper_id', (pupil_id,))
    d = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return d

def attempts_remaining(mode: str, attempts_so_far: int) -> Optional[int]:
    if mode == 'training':
        return None  # None = infinity for display
    limit = 1 if mode == 'test1' else 2
    rem = max(0, limit - attempts_so_far)
    return rem



# ---------------
# Answer checking
# ---------------

def normalize_scalar(x: str) -> str:
    return (x or "").strip().lower()


def check_single(user_ans: str, correct_ans: str) -> bool:
    return normalize_scalar(user_ans) == normalize_scalar(correct_ans)


def check_table(user_tab: List[List[str]], correct_tab: List[List[str]]) -> bool:
    if len(user_tab) != len(correct_tab):
        return False
    for r in range(len(correct_tab)):
        if len(user_tab[r]) != len(correct_tab[r]):
            return False
        for c in range(len(correct_tab[r])):
            if normalize_scalar(str(user_tab[r][c])) != normalize_scalar(str(correct_tab[r][c])):
                return False
    return True


def auto_score(problem_ids: List[str], user_answers: Dict[str, Any]) -> (float, Dict[str, bool]):
    results = {}
    correct_count = 0
    for pid in problem_ids:
        prob = get_problem(pid)
        if not prob:
            results[pid] = False
            continue
        if prob['answer_type'] == 'single':
            ok = check_single(str(user_answers.get(pid, "")), str(prob['answer']))
        else:
            ok = check_table(user_answers.get(pid, []), prob['answer'])
        results[pid] = ok
        if ok:
            correct_count += 1
    pct = 100.0 * correct_count / max(1, len(problem_ids))
    return pct, results


# ---------------
# UI Components
# ---------------

def editor_for_problem(existing=None):
    st.write("**Problem content** (Markdown/HTML; you can use <u>underline</u>, images via Markdown `![](URL)`, and links)")
    content = st.text_area("Content", value=(existing['content'] if existing else ''), height=220)
    answer_type = st.selectbox("Answer type", ["single", "table"], index=(0 if not existing or existing['answer_type']=='single' else 1))
    if answer_type == 'single':
        ans = st.text_input("Correct answer (alphanumeric)", value=(existing['answer'] if existing else ''))
    else:
        st.caption("Enter table as rows separated by newlines, cells by commas. Example: \nA,B\nC,D")
        table_text = ''
        if existing and isinstance(existing['answer'], list):
            table_text = "\n".join([",".join(map(str,row)) for row in existing['answer']])
        table_text = st.text_area("Correct answer table", value=table_text, height=120)
        ans = [ [cell.strip() for cell in line.split(',')] for line in table_text.splitlines() if line.strip() != '' ]
    return content, answer_type, ans


def render_problem(prob: Dict[str, Any], show_id: bool):
    if show_id:
        st.caption(f"Problem ID: {prob['id']}")
    st.markdown(prob['content'], unsafe_allow_html=True)


def input_for_answer(prob: Dict[str, Any], key_prefix: str):
    if prob['answer_type'] == 'single':
        return st.text_input("Your answer", key=f"{key_prefix}_single")
    else:
        rows = st.number_input("Rows", min_value=1, max_value=20, value=len(prob['answer']) if isinstance(prob['answer'], list) else 2, key=f"{key_prefix}_rows")
        cols = st.number_input("Cols", min_value=1, max_value=20, value=len(prob['answer'][0]) if isinstance(prob['answer'], list) and prob['answer'] else 2, key=f"{key_prefix}_cols")
        grid = []
        for r in range(int(rows)):
            row_vals = []
            cols_container = st.columns(int(cols))
            for c in range(int(cols)):
                row_vals.append(cols_container[c].text_input("", key=f"{key_prefix}_r{r}c{c}"))
            grid.append(row_vals)
        return grid


# ---------------
# Pages
# ---------------

def page_home():
    user = st.session_state.get("user")
    st.title("Problem DB (MVP)")
    if not user:
        st.write("Small, simple system for problems & papers. Built in Streamlit.")
        login_form_main()
        st.caption("Demo users: teacher@example.com / teach123; alice@example.com / alice123; bob@example.com / bob123")
        return

    # Logged-in landing pages
    if user["role"] == "pupil":
        st.subheader("Access paper")
        col1, col2 = st.columns([2,1])
        with col1:
            pid = st.text_input("Enter Paper ID", key="home_paper_id")
        with col2:
            if st.button("Open", key="open_paper_home"):
                st.session_state.paper_id_input = pid
                set_page("Pupil: Paper")
                st.rerun()

        st.divider()
        st.subheader("Past attempts")
        attempts = get_pupil_attempts(user['id'])
        if not attempts:
            st.info("No attempts yet.")
        else:
            paper_ids = [row[1] for row in attempts]
            counts = get_attempt_counts_by_paper(user['id'])
            sizes = get_problem_count_for_papers(paper_ids)
            # Table header
            h = st.columns([3,2,3,2,2,2])
            h[0].markdown("**Date/Time (UTC)**")
            h[1].markdown("**Paper ID**")
            h[2].markdown("**Title**")
            h[3].markdown("**Score**")
            h[4].markdown("**Attempts left**")
            h[5].markdown("**Action**")
            for i, (submitted_at, paper_id, title, mode, score, attempt_no) in enumerate(attempts):
                y = sizes.get(paper_id, 0)
                x = round((score/100.0) * y) if y else 0
                rem = attempts_remaining(mode, counts.get(paper_id, 0))
                rem_str = '∞' if rem is None else str(rem)
                cols = st.columns([3,2,3,2,2,2])
                cols[0].write(submitted_at)
                cols[1].write(f"{paper_id}")
                cols[2].write(title)
                cols[3].write(f"{x} / {y} ({score:.0f}%)")
                cols[4].write(rem_str)
                if cols[5].button("Open", key=f"open_attempt_{i}"):
                    st.session_state.paper_id_input = str(paper_id)
                    set_page("Pupil: Paper")
                    st.rerun()
    else:
        st.subheader("Welcome, Teacher")
        st.write("Use the sidebar to manage Problems and Papers.")



def page_teacher_problems():
    user = require_auth("teacher")
    if not user: return
    st.header("Manage Problems")

    # Create / Edit
    st.subheader("Create or Edit a Problem")
    pid = st.text_input("Problem ID (alphanumeric, unique)")
    existing = get_problem(pid) if pid else None
    if existing:
        st.success("Loaded existing problem.")
    content, answer_type, ans = editor_for_problem(existing)
    if st.button("Save Problem"):
        if not pid:
            st.error("Please enter a Problem ID.")
        else:
            save_problem(pid, content, answer_type, ans)
            st.success(f"Problem '{pid}' saved.")

    st.divider()

    # Preview
    st.subheader("Preview")
    if pid:
        p = get_problem(pid)
        if p:
            render_problem(p, show_id=True)
            st.caption(f"Answer type: {p['answer_type']}")
            st.code(json.dumps(p['answer'], ensure_ascii=False, indent=2))
        else:
            st.info("Enter a valid Problem ID to preview.")

    st.divider()
    st.subheader("Mass Import (placeholder)")
    st.file_uploader("Upload CSV/XLSX of problems (placeholder – not parsed yet)")
    st.caption("This is a placeholder. File is not processed yet.")


def page_teacher_papers():
    user = require_auth("teacher")
    if not user: return
    st.header("Create Papers")

    title = st.text_input("Paper title")

    st.caption("Enter problem IDs (comma-separated)")
    raw_ids = st.text_input("Problem IDs", placeholder="MATH101,MATH102,...")
    pid_list = [x.strip() for x in raw_ids.split(',') if x.strip()]

    mode = st.selectbox("Mode", ["training","test1","test2"])
    show_ids = st.checkbox("Show problem IDs to pupils", value=True)

    if st.button("Create Paper"):
        if not title or not pid_list:
            st.error("Please provide a title and at least one problem ID.")
        else:
            pid = create_paper(title, pid_list, mode, show_ids)
            st.success(f"Paper created with ID {pid}")

    st.divider()
    st.subheader("Teacher Logs (latest 200)")
    rows = get_teacher_logs()
    if not rows:
        st.info("No submissions yet.")
    else:
        st.dataframe([
            {
                'Submission ID': r[0],
                'Paper ID': r[1],
                'Pupil': r[2],
                'Email': r[3],
                'Score %': r[4],
                'Attempt': r[5],
                'Submitted at (UTC)': r[6]
            } for r in rows
        ], use_container_width=True)


def page_pupil_paper():
    user = require_auth("pupil")
    if not user: return
    st.header("Take a Paper")

    pid = st.text_input("Enter Paper ID", key="paper_id_input")
    if not pid:
        return
    try:
        paper_id = int(pid)
    except ValueError:
        st.error("Paper ID must be a number.")
        return

    paper = get_paper(paper_id)
    if not paper:
        st.error("Paper not found.")
        return

    st.subheader(paper['title'])
    st.caption(f"Mode: {paper['mode']}")

    problems = [get_problem(x) for x in paper['problem_ids']]
    missing = [paper['problem_ids'][i] for i,p in enumerate(problems) if p is None]
    if missing:
        st.warning(f"Missing problems: {', '.join(missing)}")

    answers = {}
    for p in problems:
        if not p:
            continue
        with st.expander(f"Problem {p['id']}" if paper['show_problem_ids'] else "Problem"):
            render_problem(p, show_id=paper['show_problem_ids'])
            answers[p['id']] = input_for_answer(p, key_prefix=f"paper_{paper_id}_{p['id']}")

    # Attempt control for test modes
    attempts_so_far = get_attempt_count(paper_id, user['id'])

    # Submit button
    submitted = st.button("Submit Paper")
    if not submitted:
        return

    # Enforce mode rules
    if paper['mode'] == 'test1' and attempts_so_far >= 1:
        st.error("Test mode-1 allows only one attempt.")
        return
    if paper['mode'] == 'test2' and attempts_so_far >= 2:
        st.error("Test mode-2 allows only two attempts.")
        return

    pct, per_problem = auto_score([p['id'] for p in problems if p], answers)
    attempt_no = attempts_so_far + 1
    record_submission(paper_id, user['id'], answers, pct, attempt_no)

    st.subheader(f"Your Score: {pct:.1f}%")

    # Feedback per mode
    if paper['mode'] == 'training':
        st.info("Training mode: see per-problem correctness below. You can try again anytime.")
        for p in problems:
            if not p: continue
            st.write(f"**{p['id']}**: {'✅ Correct' if per_problem[p['id']] else '❌ Incorrect'}")
    elif paper['mode'] == 'test1':
        st.info("Test mode-1: one attempt. Correct answers are revealed now.")
        for p in problems:
            if not p: continue
            st.write(f"**{p['id']}**: {'✅' if per_problem[p['id']] else '❌'}")
            st.caption("Correct answer:")
            if p['answer_type'] == 'single':
                st.code(str(p['answer']))
            else:
                st.code(json.dumps(p['answer'], ensure_ascii=False, indent=2))
    else:  # test2
        if attempt_no == 1:
            st.info("Test mode-2: you have one more attempt. Incorrect questions shown below.")
            wrong = [p['id'] for p in problems if p and not per_problem[p['id']]]
            if wrong:
                st.error("You got these wrong: " + ", ".join(wrong))
            else:
                st.success("All correct!")
        else:
            st.info("Test mode-2: Final results. Correct answers revealed.")
            for p in problems:
                if not p: continue
                st.write(f"**{p['id']}**: {'✅' if per_problem[p['id']] else '❌'}")
                st.caption("Correct answer:")
                if p['answer_type'] == 'single':
                    st.code(str(p['answer']))
                else:
                    st.code(json.dumps(p['answer'], ensure_ascii=False, indent=2))


# ---------------
# App bootstrap
# ---------------

def main():
    st.set_page_config(page_title="Problem DB", page_icon="🧮", layout="wide")
    init_db()
    ensure_demo_users()

    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'page' not in st.session_state:
        st.session_state.page = "Home"

    # Header (logo left, user info right)
    # Header (logo left, user info right)
    h1, hsp, h2 = st.columns([1,6,3])
    with h1:
        if st.button("🏫", help="Home", key="header_home_logo"):
            set_page("Home")
            st.rerun()

    with h2:
        if st.session_state.user:
            u = st.session_state.user
            st.markdown(f"You are logged in as **{u['name']}** ({u['role']}).")
            if st.button("Log out", key="logout_btn"):
                st.session_state.user = None
                set_page("Home")
                st.rerun()
        else:
            st.markdown("Not signed in.")


    # Teacher-only sidebar
    if st.session_state.user and st.session_state.user["role"] == "teacher":
        st.sidebar.title("Teacher")
        if st.sidebar.button("Problem Editor", key="btn_problem_editor"):
            set_page("Teacher: Problems")
        if st.sidebar.button("Paper Editor", key="btn_paper_editor"):
            set_page("Teacher: Papers")


    # Route
    page = st.session_state.page
    if page == "Home":
        page_home()
    elif page == "Teacher: Problems":
        if require_auth("teacher"):
            page_teacher_problems()
    elif page == "Teacher: Papers":
        if require_auth("teacher"):
            page_teacher_papers()
    elif page == "Pupil: Paper":
        if require_auth("pupil"):
            page_pupil_paper()


if __name__ == '__main__':
    main()

# ==========================
# File: requirements.txt (put next to app.py)
# ==========================
# streamlit and nothing else is strictly required; sqlite3 is in stdlib
# If you deploy on Streamlit Community Cloud, include this file.
# ---
# streamlit>=1.33
