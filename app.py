"""
ProctorAI – Online Exam Proctoring System
Database : MySQL (via PyMySQL)
Run      : python app.py
Open     : http://localhost:5000

Requirements:
    pip install flask pymysql authlib requests

MySQL Setup (XAMPP):
    1. Start Apache + MySQL in XAMPP Control Panel
    2. Open http://localhost/phpmyadmin
    3. Create database: proctorAI_db
    4. Import the file: proctorAI_db.sql in phpMyAdmin
    5. Run: python app.py
"""

import os
import json
import hashlib
import secrets
import datetime
from functools import wraps

import pymysql
import pymysql.cursors

from authlib.integrations.flask_client import OAuth
from flask import (Flask, render_template, request,
                   redirect, url_for, session, jsonify, g)

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# ──────────────────────────────────────────────────────────────
#  JINJA2 CUSTOM FILTER — fix datetime display from MySQL
# ──────────────────────────────────────────────────────────────
@app.template_filter('fmt_dt')
def fmt_dt(value, fmt='%Y-%m-%d %H:%M'):
    """Format MySQL datetime object OR string safely in templates.
    Usage: {{ s.start_time | fmt_dt }}
           {{ v.timestamp | fmt_dt('%Y-%m-%d %H:%M:%S') }}
           {{ s.created_at | fmt_dt('%Y-%m-%d') }}
    """
    if value is None:
        return '—'
    if isinstance(value, datetime.datetime):
        return value.strftime(fmt)
    val = str(value)
    if fmt == '%Y-%m-%d %H:%M:%S':
        return val[:19]
    if fmt == '%Y-%m-%d':
        return val[:10]
    return val[:16]

# ──────────────────────────────────────────────────────────────
#  GOOGLE OAUTH CONFIG
# ──────────────────────────────────────────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id="",
    client_secret="",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# ──────────────────────────────────────────────────────────────
#  MYSQL CONFIG  ← change these to match your XAMPP setup
# ──────────────────────────────────────────────────────────────
DB_CONFIG = {
    'host':        'localhost',
    'port':        3306,
    'user':        'root',
    'password':    '',
    'database':    'proctorAI_db',
    'charset':     'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'connect_timeout': 30,       # ← add this
}


# ──────────────────────────────────────────────────────────────
#  DATABASE HELPERS
# ──────────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = pymysql.connect(**DB_CONFIG)
    else:
        # Reconnect if connection was lost
        try:
            g.db.ping(reconnect=True)
        except Exception:
            g.db = pymysql.connect(**DB_CONFIG)
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db:
        db.close()

def query(sql, args=(), one=False):
    """Run SELECT — returns list of dicts, or one dict if one=True."""
    db  = get_db()
    cur = db.cursor()
    cur.execute(sql, args)
    result = cur.fetchall()
    cur.close()
    return (result[0] if result else None) if one else result

def execute(sql, args=()):
    """Run INSERT / UPDATE / DELETE — returns last inserted row id."""
    db  = get_db()
    cur = db.cursor()
    cur.execute(sql, args)
    db.commit()
    last_id = cur.lastrowid
    cur.close()
    return last_id

def to_dt(value):
    """Convert MySQL datetime or string to datetime object safely."""
    if isinstance(value, datetime.datetime):
        return value
    if value is None:
        return datetime.datetime.now()
    return datetime.datetime.fromisoformat(str(value))

def now_str():
    """Return current datetime as ISO string for MySQL storage."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()


# ──────────────────────────────────────────────────────────────
#  AUTH DECORATORS
# ──────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ──────────────────────────────────────────────────────────────
#  AUTH ROUTES
# ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user = query(
            "SELECT * FROM users WHERE email=%s AND password=%s",
            (request.form['email'], hash_pw(request.form['password'])),
            one=True
        )
        if user:
            session['user_id']   = user['id']
            session['username']  = user['username']
            session['role']      = user['role']
            session['full_name'] = user['full_name'] or user['username']
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        error = 'Invalid email or password.'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ──────────────────────────────────────────────────────────────
#  GOOGLE OAUTH ROUTES  (Students only)
# ──────────────────────────────────────────────────────────────
@app.route('/auth/google')
def google_login():
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def google_callback():
    """Google redirects back here after login."""
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')

        if not user_info:
            return redirect(url_for('login'))

        email     = user_info.get('email')
        full_name = user_info.get('name', email)
        picture   = user_info.get('picture', '')

        # ── UPTM Domain Restriction ──────────────────────────
        ALLOWED_DOMAIN = '@student.uptm.edu.my'
        if not email.endswith(ALLOWED_DOMAIN):
            return render_template('login.html',
                error=f'❌ Access denied! Only UPTM student emails (@student.uptm.edu.my) are allowed to sign in with Google.')
        # ─────────────────────────────────────────────────────

        existing = query(
            "SELECT * FROM users WHERE email=%s", (email,), one=True
        )

        if existing:
            if existing['role'] == 'admin':
                return render_template('login.html',
                    error='Admin accounts cannot use Google Sign In. Please use email and password.')
            session['user_id']   = existing['id']
            session['username']  = existing['username']
            session['role']      = existing['role']
            session['full_name'] = existing['full_name'] or full_name
            session['picture']   = picture
        else:
            username = email.split('@')[0].replace('.', '_').replace('-', '_')
            base_username = username
            counter = 1
            while query("SELECT id FROM users WHERE username=%s", (username,), one=True):
                username = f"{base_username}{counter}"
                counter += 1

            new_id = execute(
                """INSERT INTO users (username, password, role, full_name, email)
                   VALUES (%s, %s, %s, %s, %s)""",
                (username, '', 'student', full_name, email)
            )
            session['user_id']   = new_id
            session['username']  = username
            session['role']      = 'student'
            session['full_name'] = full_name
            session['picture']   = picture

        return redirect(url_for('dashboard'))

    except Exception as e:
        return render_template('login.html', error=f'Google Sign In failed: {str(e)}')


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        existing = query(
            "SELECT id FROM users WHERE email=%s OR username=%s",
            (request.form['email'], request.form['username']),
            one=True
        )
        if existing:
            error = 'Email or username already registered.'
        elif not request.form['email'].endswith('@student.uptm.edu.my'):
            error = '❌ Only UPTM student emails (@student.uptm.edu.my) are allowed to register.'
        else:
            try:
                execute(
                    "INSERT INTO users (username,password,role,full_name,email) VALUES (%s,%s,%s,%s,%s)",
                    (request.form['username'], hash_pw(request.form['password']),
                     'student', request.form['full_name'], request.form['email'])
                )
                return redirect(url_for('login'))
            except Exception as ex:
                error = f'Registration failed: {ex}'
    return render_template('register.html', error=error)


# ──────────────────────────────────────────────────────────────
#  STUDENT ROUTES
# ──────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    exams = query("SELECT * FROM exams WHERE is_active=1 ORDER BY id DESC")
    sessions_list = query(
        "SELECT * FROM exam_sessions WHERE user_id=%s", (session['user_id'],)
    )
    exam_sessions = {s["exam_id"]: s for s in sessions_list}
    return render_template('dashboard.html', exams=exams, exam_sessions=exam_sessions)


@app.route('/exam/start/<int:exam_id>')
@login_required
def start_exam(exam_id):
    exam = query("SELECT * FROM exams WHERE id=%s AND is_active=1", (exam_id,), one=True)
    if not exam:
        return redirect(url_for('dashboard'))

    existing = query(
        "SELECT * FROM exam_sessions WHERE exam_id=%s AND user_id=%s",
        (exam_id, session['user_id']), one=True
    )
    if existing:
        if existing['terminated'] or existing['status'] == 'completed':
            return redirect(url_for('dashboard'))
        return redirect(url_for('take_exam', exam_id=exam_id))

    execute(
        "INSERT INTO exam_sessions (exam_id,user_id,start_time,status) VALUES (%s,%s,%s,'in_progress')",
        (exam_id, session['user_id'], now_str())
    )
    return redirect(url_for('take_exam', exam_id=exam_id))


@app.route('/exam/<int:exam_id>')
@login_required
def take_exam(exam_id):
    exam = query("SELECT * FROM exams WHERE id=%s", (exam_id,), one=True)
    if not exam:
        return redirect(url_for('dashboard'))

    es = query(
        "SELECT * FROM exam_sessions WHERE exam_id=%s AND user_id=%s",
        (exam_id, session['user_id']), one=True
    )
    if not es or es['terminated'] or es['status'] == 'completed':
        return redirect(url_for('dashboard'))

    start     = to_dt(es["start_time"])
    elapsed   = (datetime.datetime.now() - start).total_seconds()
    remaining = max(0, exam['duration_minutes'] * 60 - int(elapsed))
    if remaining == 0:
        return redirect(url_for('submit_exam', exam_id=exam_id))

    questions    = query("SELECT * FROM questions WHERE exam_id=%s ORDER BY order_num,id", (exam_id,))
    saved        = query("SELECT question_id,selected_answer FROM answers WHERE session_id=%s", (es['id'],))
    answers_map  = {a['question_id']: a['selected_answer'] for a in saved}

    questions_json = json.dumps([{
        'id':       q['id'],
        'text':     q['question_text'],
        'option_a': q['option_a'],
        'option_b': q['option_b'],
        'option_c': q['option_c'],
        'option_d': q['option_d'],
        'saved':    answers_map.get(q['id'], ''),
    } for q in questions])

    return render_template('take_exam.html',
        exam=exam, session_id=es['id'], remaining=remaining,
        question_count=len(questions), questions_json=questions_json,
        violation_count=es['violation_count'])


@app.route('/exam/submit/<int:exam_id>')
@login_required
def submit_exam(exam_id):
    es = query(
        "SELECT * FROM exam_sessions WHERE exam_id=%s AND user_id=%s",
        (exam_id, session['user_id']), one=True
    )
    if not es:
        return redirect(url_for('dashboard'))
    if es['status'] == 'completed':
        return redirect(url_for('view_result', session_id=es['id']))

    questions = query("SELECT * FROM questions WHERE exam_id=%s", (exam_id,))

    score = 0
    total = 0
    for q in questions:
        total += q['marks']

        # Get the LATEST saved answer for this question
        saved_answer = query(
            "SELECT selected_answer FROM answers WHERE session_id=%s AND question_id=%s",
            (es['id'], q['id']), one=True
        )
        selected = saved_answer['selected_answer'] if saved_answer else ''
        correct  = int(selected == q['correct_answer']) if selected else 0

        execute(
            """INSERT INTO answers (session_id,question_id,selected_answer,is_correct)
               VALUES (%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE selected_answer=VALUES(selected_answer), is_correct=VALUES(is_correct)""",
            (es['id'], q['id'], selected, correct)
        )
        if correct:
            score += q['marks']

    execute(
        "UPDATE exam_sessions SET status='completed',end_time=%s,score=%s,total_marks=%s WHERE id=%s",
        (now_str(), score, total, es['id'])
    )
    return redirect(url_for('view_result', session_id=es['id']))


@app.route('/results/<int:session_id>')
@login_required
def view_result(session_id):
    es = query("SELECT * FROM exam_sessions WHERE id=%s", (session_id,), one=True)
    if not es:
        return redirect(url_for('dashboard'))
    if session.get('role') != 'admin' and es['user_id'] != session['user_id']:
        return redirect(url_for('dashboard'))

    exam       = query("SELECT * FROM exams WHERE id=%s", (es['exam_id'],), one=True)
    questions  = query("SELECT * FROM questions WHERE exam_id=%s ORDER BY order_num,id", (es['exam_id'],))
    answers    = query("SELECT * FROM answers WHERE session_id=%s", (session_id,))
    violations = query("SELECT * FROM violations WHERE session_id=%s ORDER BY id", (session_id,))
    student    = query("SELECT * FROM users WHERE id=%s", (es['user_id'],), one=True)
    answers_map = {a['question_id']: a for a in answers}
    pct = round((float(es['score']) / float(es['total_marks'])) * 100) if es['total_marks'] and es['score'] is not None else 0

    for q in questions:
        ans = answers_map.get(q['id'])
        q['selected_answer'] = ans['selected_answer'] if ans else ''
        q['is_correct']      = ans['is_correct'] if ans else 0

    return render_template('result_detail.html',
        es=es, exam=exam, questions=questions,
        answers_map=answers_map, violations=violations,
        student=student, pct=pct)


@app.route('/results')
@login_required
def results():
    print("DEBUG user_id in session:", session['user_id'])  # ← add this
    sessions_list = query(
        """SELECT es.*, e.title FROM exam_sessions es
           JOIN exams e ON es.exam_id=e.id
           WHERE es.user_id=%s ORDER BY es.id DESC""",
        (session['user_id'],)
    )
    print("DEBUG sessions found:", len(sessions_list))  # ← add this
    return render_template('results.html', sessions=sessions_list)


# ──────────────────────────────────────────────────────────────
#  API ROUTES
# ──────────────────────────────────────────────────────────────
@app.route('/api/save_answer', methods=['POST'])
@login_required
def api_save_answer():
    data = request.get_json()
    es   = query("SELECT * FROM exam_sessions WHERE id=%s AND user_id=%s",
                 (data['session_id'], session['user_id']), one=True)
    if not es:
        return jsonify({'ok': False})

    existing = query("SELECT id FROM answers WHERE session_id=%s AND question_id=%s",
                     (data['session_id'], data['question_id']), one=True)
    if existing:
        execute("UPDATE answers SET selected_answer=%s WHERE id=%s",
                (data['answer'], existing['id']))
    else:
        execute("INSERT INTO answers (session_id,question_id,selected_answer) VALUES (%s,%s,%s)",
                (data['session_id'], data['question_id'], data['answer']))
    return jsonify({'ok': True})


@app.route('/api/violation', methods=['POST'])
@login_required
def api_violation():
    data = request.get_json()
    es   = query("SELECT * FROM exam_sessions WHERE id=%s AND user_id=%s",
                 (data['session_id'], session['user_id']), one=True)
    if not es:
        return jsonify({'count': 0, 'terminated': False})

    exam = query("SELECT * FROM exams WHERE id=%s", (es['exam_id'],), one=True)
    execute("INSERT INTO violations (session_id,violation_type,description) VALUES (%s,%s,%s)",
            (data['session_id'], data['type'], data['desc']))
    execute("UPDATE exam_sessions SET violation_count=violation_count+1 WHERE id=%s",
            (data['session_id'],))

    updated    = query("SELECT * FROM exam_sessions WHERE id=%s", (data['session_id'],), one=True)
    terminated = False
    if updated['violation_count'] >= exam['max_violations']:
        execute("UPDATE exam_sessions SET terminated=1,status='completed',end_time=%s WHERE id=%s",
                (now_str(), data['session_id']))
        terminated = True

    return jsonify({'count': updated['violation_count'], 'terminated': terminated})


# ──────────────────────────────────────────────────────────────
#  ADMIN ROUTES
# ──────────────────────────────────────────────────────────────
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    stats = {
        'exams':      query("SELECT COUNT(*) as c FROM exams", one=True)['c'],
        'students':   query("SELECT COUNT(*) as c FROM users WHERE role='student'", one=True)['c'],
        'completed':  query("SELECT COUNT(*) as c FROM exam_sessions WHERE status='completed'", one=True)['c'],
        'violations': query("SELECT COALESCE(SUM(violation_count),0) as c FROM exam_sessions", one=True)['c'],
    }
    recent = query(
        """SELECT es.*, u.full_name, e.title
           FROM exam_sessions es
           JOIN users u ON es.user_id=u.id
           JOIN exams e ON es.exam_id=e.id
           ORDER BY es.id DESC LIMIT 10"""
    )
    return render_template('admin_dashboard.html', stats=stats, recent=recent)


@app.route('/admin/exams')
@login_required
@admin_required
def admin_exams():
    exams = query(
        """SELECT e.*, (SELECT COUNT(*) FROM questions WHERE exam_id=e.id) as q_count
           FROM exams e ORDER BY e.id DESC"""
    )
    return render_template('admin_exams.html', exams=exams)


@app.route('/admin/exams/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_exam():
    if request.method == 'POST':
        execute(
            "INSERT INTO exams (title,description,duration_minutes,max_violations,created_by) VALUES (%s,%s,%s,%s,%s)",
            (request.form['title'], request.form['description'],
             int(request.form['duration']), int(request.form['max_violations']),
             session['user_id'])
        )
        return redirect(url_for('admin_exams'))
    return render_template('admin_exam_form.html')


@app.route('/admin/exams/<int:exam_id>/questions', methods=['GET', 'POST'])
@login_required
@admin_required
def exam_questions(exam_id):
    exam = query("SELECT * FROM exams WHERE id=%s", (exam_id,), one=True)
    if request.method == 'POST':
        execute(
            """INSERT INTO questions
               (exam_id,question_text,option_a,option_b,option_c,option_d,
                correct_answer,marks,order_num)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (exam_id, request.form['question_text'],
             request.form['option_a'], request.form['option_b'],
             request.form['option_c'], request.form['option_d'],
             request.form['correct_answer'],
             int(request.form['marks']),
             int(request.form.get('order_num', 0)))
        )
    questions = query("SELECT * FROM questions WHERE exam_id=%s ORDER BY order_num,id", (exam_id,))
    return render_template('admin_questions.html', exam=exam, questions=questions)


@app.route('/admin/questions/<int:qid>/delete')
@login_required
@admin_required
def delete_question(qid):
    q = query("SELECT exam_id FROM questions WHERE id=%s", (qid,), one=True)
    if q:
        execute("DELETE FROM questions WHERE id=%s", (qid,))
        return redirect(url_for('exam_questions', exam_id=q['exam_id']))
    return redirect(url_for('admin_exams'))


@app.route('/admin/exams/<int:exam_id>/toggle')
@login_required
@admin_required
def toggle_exam(exam_id):
    execute("UPDATE exams SET is_active=1-is_active WHERE id=%s", (exam_id,))
    return redirect(url_for('admin_exams'))


@app.route('/admin/exams/<int:exam_id>/delete')
@login_required
@admin_required
def delete_exam(exam_id):
    execute("DELETE FROM questions WHERE exam_id=%s", (exam_id,))
    execute("DELETE FROM exams WHERE id=%s", (exam_id,))
    return redirect(url_for('admin_exams'))


@app.route('/admin/students')
@login_required
@admin_required
def admin_students():
    students = query(
        """SELECT u.*,
               (SELECT COUNT(*) FROM exam_sessions WHERE user_id=u.id AND status='completed') as completed,
               (SELECT COALESCE(SUM(violation_count),0) FROM exam_sessions WHERE user_id=u.id) as total_violations
           FROM users u WHERE u.role='student' ORDER BY u.id"""
    )
    return render_template('admin_students.html', students=students)


@app.route('/admin/monitor')
@login_required
@admin_required
def admin_monitor():
    all_sessions = query(
        """SELECT es.*, u.full_name, u.username, e.title
           FROM exam_sessions es
           JOIN users u ON es.user_id=u.id
           JOIN exams e ON es.exam_id=e.id
           ORDER BY es.id DESC"""
    )
    return render_template('admin_monitor.html', all_sessions=all_sessions)


# ──────────────────────────────────────────────────────────────
#  ADMIN MANAGEMENT ROUTES
# ──────────────────────────────────────────────────────────────
@app.route('/admin/admins')
@login_required
@admin_required
def admin_admins():
    admins = query("SELECT * FROM users WHERE role='admin' ORDER BY id")
    return render_template('admin_admins.html', admins=admins)


@app.route('/admin/admins/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create_admin():
    error   = None
    success = None

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        username  = request.form.get('username', '').strip()
        email     = request.form.get('email', '').strip()
        password  = request.form.get('password', '').strip()
        confirm   = request.form.get('confirm_password', '').strip()

        if not all([full_name, username, email, password, confirm]):
            error = 'All fields are required.'
        elif password != confirm:
            error = 'Passwords do not match.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters.'
        else:
            existing = query(
                "SELECT id FROM users WHERE email=%s OR username=%s",
                (email, username), one=True
            )
            if existing:
                error = 'Email or username is already taken.'
            else:
                execute(
                    "INSERT INTO users (username, password, role, full_name, email) VALUES (%s,%s,%s,%s,%s)",
                    (username, hash_pw(password), 'admin', full_name, email)
                )
                success = f'Admin account for {full_name} created successfully!'

    return render_template('admin_create_admin.html', error=error, success=success)


@app.route('/admin/admins/<int:admin_id>/delete')
@login_required
@admin_required
def delete_admin(admin_id):
    if admin_id == session['user_id']:
        return redirect(url_for('admin_admins'))
    count = query("SELECT COUNT(*) as c FROM users WHERE role='admin'", one=True)['c']
    if count <= 1:
        return redirect(url_for('admin_admins'))
    execute("DELETE FROM users WHERE id=%s AND role='admin'", (admin_id,))
    return redirect(url_for('admin_admins'))


# ──────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 55)
    print("  ProctorAI  -  Online Exam Proctoring System")
    print("  Database  : MySQL  (proctorAI_db)")
    print("=" * 55)
    print("  URL     : http://localhost:5000")
    print("  Admin   : admin@proctor.edu  /  admin123")
    print("  Student : alex@student.edu   /  student123")
    print("=" * 55)
    print("  NOTE: Make sure XAMPP MySQL is running!")
    print("        Import proctorAI_db.sql in phpMyAdmin first.")
    print("=" * 55)
    app.run(debug=True, host='0.0.0.0', port=5000)