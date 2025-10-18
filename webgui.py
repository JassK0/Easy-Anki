from flask import Flask, render_template, request, redirect, url_for, session, flash
import uuid
import os
from werkzeug.security import generate_password_hash, check_password_hash
from main import load_questions, load_progress, save_progress, choose_exam_set, filter_questions, parse_chapter_filter, CardState, BUILTIN, log_event
from datetime import datetime, date, timedelta
from typing import Tuple

app = Flask(__name__)
# For production, read secret key from environment. Fallback to random for dev.
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24)

# In-memory server-side storage for session state to avoid large cookies
app_state = {}

PROGRESS_FILE = "course_progress.json"
LOG_FILE = "session_log.jsonl"
POOLS_META = "data/pools.json"
DATA_DIR = "data"
USERS_FILE = os.path.join(DATA_DIR, 'users.json')

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(POOLS_META):
        with open(POOLS_META, 'w', encoding='utf-8') as f:
            json = __import__('json')
            f.write(json.dumps([]))

def read_pools():
    ensure_data_dir()
    import json as _json
    try:
        pools = []
        # global pools
        if os.path.exists(POOLS_META):
            try:
                with open(POOLS_META, 'r', encoding='utf-8') as f:
                    pools = _json.load(f) or []
            except Exception:
                pools = []
        # user-specific pools override/append
        username = session.get('username')
        if username:
            upath = os.path.join(DATA_DIR, f"pools_{username}.json")
            if os.path.exists(upath):
                try:
                    userp = _json.load(open(upath, 'r', encoding='utf-8')) or []
                    # merge: user pools after global
                    pools = pools + userp
                except Exception:
                    pass
        return pools
    except Exception:
        return []


def read_users():
    ensure_data_dir()
    import json as _json
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return _json.load(f)
    except Exception:
        return {}


def write_users(users):
    ensure_data_dir()
    import json as _json
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        _json.dump(users, f, indent=2)

def write_pools(pools):
    ensure_data_dir()
    import json as _json
    # If user signed in, write to their pools file; otherwise write global pools
    username = session.get('username')
    if username:
        upath = os.path.join(DATA_DIR, f"pools_{username}.json")
        with open(upath, 'w', encoding='utf-8') as f:
            _json.dump(pools, f, indent=2)
    else:
        with open(POOLS_META, 'w', encoding='utf-8') as f:
            _json.dump(pools, f, indent=2)

def compute_stats_for_pool(pool_meta):
    # pool_meta: {id,path,orig_name}
    # Support builtin pool (id == 'builtin') which uses the BUILTIN list
    if pool_meta.get('id') == 'builtin':
        qs = BUILTIN[:]
    else:
        qpath = pool_meta['path']
        qs = load_questions(qpath)
    qmap = {q.id: q for q in qs}
    prog_fp = f"{DATA_DIR}/progress_{pool_meta['id']}.json"
    prog = {}
    if os.path.exists(prog_fp):
        try:
            prog = __import__('json').load(open(prog_fp, 'r', encoding='utf-8'))
        except Exception:
            prog = {}
    # compute stats
    total = len(qs)
    answered = len(prog)
    correct_streaks = {qid: v.get('correct_streak', 0) for qid, v in prog.items()}
    incorrect_counts = {qid: v.get('incorrect_count', 0) for qid, v in prog.items()}
    wrong_count = sum(1 for v in prog.values() if v.get('incorrect_count', 0) > 0)
    most_correct = None
    most_wrong = None
    if correct_streaks:
        mcid = max(correct_streaks, key=lambda k: correct_streaks[k])
        most_correct = {'id': mcid, 'streak': correct_streaks[mcid], 'prompt': qmap.get(mcid).prompt if qmap.get(mcid) else ''}
    if incorrect_counts:
        mwid = max(incorrect_counts, key=lambda k: incorrect_counts[k])
        most_wrong = {'id': mwid, 'count': incorrect_counts[mwid], 'prompt': qmap.get(mwid).prompt if qmap.get(mwid) else ''}
    # additional metrics
    incorrect_total = sum(v.get('incorrect_count', 0) for v in prog.values())
    # average box (estimate of mastery)
    boxes = [v.get('box', 1) for v in prog.values()]
    avg_box = round((sum(boxes) / len(boxes)), 2) if boxes else 1.0
    # due count
    due_count = 0
    for v in prog.values():
        d = v.get('due')
        if d:
            try:
                due_dt = datetime.fromisoformat(d)
                if datetime.utcnow() >= due_dt:
                    due_count += 1
            except Exception:
                pass

    return {
        'total': total,
        'answered': answered,
        'wrong_count': wrong_count,
        'most_correct': most_correct,
        'most_wrong': most_wrong,
        'incorrect_total': incorrect_total,
        'avg_box': avg_box,
        'due_count': due_count,
    }


def compute_progress_timeseries(pool_meta):
    # Build a simple cumulative timeseries of questions with a last_seen date
    prog_fp = PROGRESS_FILE if pool_meta.get('id') == 'builtin' else f"{DATA_DIR}/progress_{pool_meta['id']}.json"
    times = {}
    if os.path.exists(prog_fp):
        try:
            import json as _json
            raw = _json.load(open(prog_fp, 'r', encoding='utf-8'))
            for qid, v in raw.items():
                last = v.get('last_seen')
                if not last:
                    continue
                try:
                    d = last.split('T', 1)[0]
                except Exception:
                    d = last
                times.setdefault(d, 0)
                times[d] += 1
        except Exception:
            times = {}
    # create sorted cumulative lists
    if not times:
        return {'labels': [], 'values': []}
    dates = sorted(times.keys())
    cum = []
    total = 0
    labels = []
    for d in dates:
        total += times[d]
        labels.append(d)
        cum.append(total)
    return {'labels': labels, 'values': cum}


def _gamestate_path(user_id=None):
    ensure_data_dir()
    if user_id:
        return os.path.join(DATA_DIR, f"gamestate_{user_id}.json")
    return os.path.join(DATA_DIR, "gamestate.json")


def load_gamestate(user_id=None):
    import json as _json
    fp = _gamestate_path(user_id)
    if os.path.exists(fp):
        try:
            gs = _json.load(open(fp, 'r', encoding='utf-8'))
            # ensure numeric points and up-to-date rank
            try:
                # coerce points to int when possible
                if 'points' in gs:
                    gs['points'] = int(gs.get('points', 0))
            except Exception:
                gs['points'] = 0
            # recalc rank from points to keep consistency
            check_and_award_badges(gs)
            # persist any change
            try:
                _json.dump(gs, open(fp, 'w', encoding='utf-8'), indent=2)
            except Exception:
                pass
            return gs
        except Exception:
            pass
    # default gamestate
    gs = {
        'points': 0,
        'rank': 'Unranked',
        'answer_streak': 0,  # positive = correct streak length, negative = wrong streak length
        'daily_streak': 0,
        'last_active': None,
        'history': []
    }
    try:
        _json.dump(gs, open(fp, 'w', encoding='utf-8'), indent=2)
    except Exception:
        pass
    return gs


def save_gamestate(gs, user_id=None):
    import json as _json
    fp = _gamestate_path(user_id)
    try:
        _json.dump(gs, open(fp, 'w', encoding='utf-8'), indent=2)
    except Exception:
        pass


def update_daily_streak(gs):
    # gs['last_active'] stores ISO datetime string; update daily_streak based on date change
    today = date.today()
    last = gs.get('last_active')
    if last:
        try:
            last_date = datetime.fromisoformat(last).date()
        except Exception:
            last_date = None
    else:
        last_date = None

    if last_date == today:
        # already updated today
        return gs
    # if last active was yesterday, increment streak; otherwise reset to 1
    if last_date and (today - last_date).days == 1:
        gs['daily_streak'] = gs.get('daily_streak', 0) + 1
    else:
        gs['daily_streak'] = 1
    gs['last_active'] = datetime.utcnow().isoformat(timespec='seconds')
    # check badges after streak update
    check_and_award_badges(gs)
    return gs


def award_points(gs, amount, reason=None, user_id=None):
    # Record a points change in gamestate
    gs['points'] = gs.get('points', 0) + amount
    rec = {'ts': datetime.utcnow().isoformat(timespec='seconds'), 'delta': amount, 'reason': reason}
    gs.setdefault('history', []).append(rec)
    check_and_award_badges(gs)
    save_gamestate(gs, user_id)
    return gs


def check_and_award_badges(gs):
    # Update rank based on points thresholds
    p = gs.get('points', 0)
    # New rank tiers
    if p >= 1500:
        r = 'Grand Master'
    elif p >= 1000:
        r = 'Master'
    elif p >= 700:
        r = 'Diamond'
    elif p >= 500:
        r = 'Gold'
    elif p >= 300:
        r = 'Silver'
    elif p >= 100:
        r = 'Bronze'
    else:
        r = 'Unranked'
    gs['rank'] = r
    return r


def get_user_id():
    # ensure a per-session user id for session-scoped gamestate
    uid = session.get('user_id')
    if not uid:
        uid = uuid.uuid4().hex
        session['user_id'] = uid
    return uid


def current_user():
    # return username if signed in
    return session.get('username')


def all_user_points():
    """Return a dict username -> points by reading users.json and per-user gamestate files."""
    users = read_users()
    res = {}
    import json as _json
    for u in users.keys():
        try:
            gp = _gamestate_path(u)
            if os.path.exists(gp):
                data = _json.load(open(gp, 'r', encoding='utf-8'))
                res[u] = (int(data.get('points', 0)), data.get('rank','Unranked'))
            else:
                res[u] = (0, 'Unranked')
        except Exception:
            res[u] = 0
    return res


@app.route('/leaderboard')
def leaderboard():
    # compute leaderboard. support tabs: 'points' (default) or 'rank'
    pts = all_user_points()
    # pts: username -> (points, rank)
    tab = request.args.get('tab', 'points')
    # define rank ordering for sorting when tab='rank'
    RANK_ORDER = {
        'Grand Master': 6,
        'Master': 5,
        'Diamond': 4,
        'Gold': 3,
        'Silver': 2,
        'Bronze': 1,
        'Unranked': 0,
    }

    if tab == 'rank':
        # sort primarily by rank value, then by points, then username
        sorted_users = sorted(pts.items(), key=lambda x: (-RANK_ORDER.get(x[1][1], 0), -x[1][0], x[0]))
    else:
        # default: sort by points
        sorted_users = sorted(pts.items(), key=lambda x: (-x[1][0], x[0]))

    top10 = [(u, p[0], p[1]) for u, p in sorted_users[:10]]
    cur = current_user()
    user_place = None
    user_points = 0
    if cur:
        for i, (u, p) in enumerate(sorted_users, start=1):
            if u == cur:
                user_place = i
                user_points = p[0]
                break
    return render_template('leaderboard.html', top10=top10, user_place=user_place, user_points=user_points, current_user=cur, tab=tab)


def is_strong_password(pw: str) -> Tuple[bool, list]:
    """Return (True, []) if password is strong, otherwise (False, reasons list).

    Requirements enforced:
    - at least 8 characters
    - at least one uppercase letter
    - at least one lowercase letter
    - at least one digit
    - at least one special character (non-alphanumeric)
    """
    reasons = []
    if len(pw) < 8:
        reasons.append('at least 8 characters')
    if not any(c.islower() for c in pw):
        reasons.append('a lowercase letter')
    if not any(c.isupper() for c in pw):
        reasons.append('an uppercase letter')
    if not any(c.isdigit() for c in pw):
        reasons.append('a digit')
    if not any(not c.isalnum() for c in pw):
        reasons.append('a special character (e.g. !@#$%)')
    return (len(reasons) == 0, reasons)


def choose_special_set(qs, n, prog):
    # choose questions most in need: use incorrect_count and low box as signals
    scored = []
    for q in qs:
        st = prog.get(q.id, CardState())
        score = st.incorrect_count * 3 + (6 - st.box)
        # overdue bonus
        if st.due:
            try:
                from datetime import datetime
                due = datetime.fromisoformat(st.due)
                if datetime.utcnow() >= due:
                    score += 2
            except Exception:
                pass
        scored.append((score, q))
    scored.sort(key=lambda x: x[0], reverse=True)
    chosen = [q for _, q in scored[:min(n, len(scored))]]
    # if not enough high-score items, fill with srs-weighted selection
    if len(chosen) < n:
        needed = n - len(chosen)
        remaining = [q for q in qs if q not in chosen]
        chosen += choose_exam_set(remaining, needed, prog)
    return chosen

# Templates are stored in templates/*.html and static assets in static/

@app.route('/', methods=['GET'])
def index():
    # show pools and upload on the main page for convenience
    ensure_data_dir()
    pools = read_pools()
    builtin_meta = {'id': 'builtin', 'path': None, 'orig_name': 'Built-in pool'}
    pools_display = [builtin_meta] + pools
    stats = []
    for p in pools_display:
        s = compute_stats_for_pool(p)
        t = compute_progress_timeseries(p)
        stats.append({'meta': p, 'stats': s, 'times': t})
    uid = get_user_id()
    user = current_user()
    gs = load_gamestate(user or uid)
    # update daily streak on each visit
    gs = update_daily_streak(gs)
    save_gamestate(gs, user or uid)
    # prepare leaderboard summary for embedding on the main page
    pts = all_user_points()
    # pts: username -> (points, rank)
    sorted_users = sorted(pts.items(), key=lambda x: (-x[1][0], x[0]))
    # sorted_users: list of (username, (points, rank))
    top10 = [(u, v[0], v[1]) for u, v in sorted_users[:10]]
    user_place = None
    user_points = 0
    if user:
        for i, (u, p) in enumerate(sorted_users, start=1):
            if u == user:
                user_place = i
                user_points = p[0]
                break
    leaderboard = {'top10': top10, 'user_place': user_place, 'user_points': user_points}
    return render_template('index.html', pools=stats, points=gs.get('points',0), daily_streak=gs.get('daily_streak', 0), rank=gs.get('rank','Unranked'), current_user=user, leaderboard=leaderboard)

@app.route('/start', methods=['POST'])
def start():
    # Support file upload from home page: if user uploads a file, save it as a new pool
    f = request.files.get('file')
    src = None
    if f:
        # only allow uploads from signed-in users
        if not current_user():
            flash('Please sign in to upload pools', 'error')
            return redirect(url_for('login'))
        pid = uuid.uuid4().hex
        filename = f"{pid}_{f.filename}"
        dest = os.path.join(DATA_DIR, filename)
        ensure_data_dir()
        f.save(dest)
        pname = request.form.get('pool_name') or f.filename
        pools = read_pools()
        meta = {'id': pid, 'path': dest, 'orig_name': pname}
        pools.append(meta)
        write_pools(pools)
        src = dest
    else:
        src = request.form.get('source') or None
    num = int(request.form.get('num') or 10)
    ch = request.form.get('chapters')
    tg = request.form.get('tags')

    all_qs = load_questions(src)
    chapters = parse_chapter_filter(ch)
    tags = [t.strip().lower() for t in tg.split(',') if t.strip()] if tg else None
    pool = filter_questions(all_qs, chapters, tags)
    if not pool:
        return "No questions in pool. Go <a href='/'>back</a>."
    sid = uuid.uuid4().hex
    app_state[sid] = {
        'pool': [q.__dict__ for q in pool],
        'num': num,
        'index': 0,
        'set': [q.__dict__ for q in choose_exam_set(pool, num, load_progress(PROGRESS_FILE))],
        'wrong': [],
        'progress': {k: v.__dict__ for k,v in load_progress(PROGRESS_FILE).items()},
    }
    session['sid'] = sid
    return redirect(url_for('question'))

@app.route('/pool')
def pool_preview():
    sid = session.get('sid')
    # If there is an active session, use its pool. Otherwise allow preview via query params
    if sid and sid in app_state:
        pool = app_state[sid]['pool']
        return render_template('pool.html', qs=pool, count=len(pool))

    # No session: build pool from optional GET args (or default built-in pool)
    src = request.args.get('source') or None
    ch = request.args.get('chapters')
    tg = request.args.get('tags')
    all_qs = load_questions(src)
    chapters = parse_chapter_filter(ch)
    tags = [t.strip().lower() for t in tg.split(',') if t.strip()] if tg else None
    pool = filter_questions(all_qs, chapters, tags)
    return render_template('pool.html', qs=pool, count=len(pool))


@app.route('/pools', methods=['GET', 'POST'])
def pools():
    ensure_data_dir()
    pools = read_pools()
    # prepend built-in pool meta so it's always visible
    builtin_meta = {'id': 'builtin', 'path': None, 'orig_name': 'Built-in pool'}
    pools_display = [builtin_meta] + pools
    if request.method == 'POST':
        # handle file upload - only signed-in users may upload
        if not current_user():
            flash('Please sign in to upload pools', 'error')
            return redirect(url_for('login'))
        f = request.files.get('file')
        if not f:
            return redirect(url_for('pools'))
        pid = uuid.uuid4().hex
        filename = f"{pid}_{f.filename}"
        dest = os.path.join(DATA_DIR, filename)
        f.save(dest)
        pname = request.form.get('pool_name') or f.filename
        meta = {'id': pid, 'path': dest, 'orig_name': pname}
        pools.append(meta)
        write_pools(pools)
        return redirect(url_for('pools'))
    # GET
    stats = []
    for p in pools_display:
        s = compute_stats_for_pool(p)
        stats.append({'meta': p, 'stats': s})
    return render_template('pools.html', pools=stats, current_user=current_user())


@app.route('/pools/<pid>/delete', methods=['POST'])
def pools_delete(pid):
    # remove pool metadata, delete uploaded file and per-pool progress
    pools = read_pools()
    meta = next((p for p in pools if p['id']==pid), None)
    if not meta:
        return redirect(url_for('pools'))
    # delete file if it exists and looks like an uploaded file
    try:
        fp = meta.get('path')
        if fp and os.path.exists(fp):
            os.remove(fp)
    except Exception:
        pass
    # delete per-pool progress file
    try:
        prog_fp = f"{DATA_DIR}/progress_{pid}.json"
        if os.path.exists(prog_fp):
            os.remove(prog_fp)
    except Exception:
        pass
    # remove from pools list
    pools = [p for p in pools if p['id'] != pid]
    write_pools(pools)
    return redirect(url_for('pools'))


@app.route('/pools/<pid>/rename', methods=['GET', 'POST'])
def pools_rename(pid):
    pools = read_pools()
    if pid == 'builtin':
        # cannot rename builtin
        return redirect(url_for('pools'))
    meta = next((p for p in pools if p['id']==pid), None)
    if not meta:
        return redirect(url_for('pools'))
    if request.method == 'POST':
        newname = request.form.get('name')
        if newname:
            meta['orig_name'] = newname
            write_pools(pools)
        return redirect(url_for('pools'))
    return f"<form method='post'>New name: <input name='name' value='{meta.get('orig_name','')}'><button>Save</button></form>"


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password:
            flash('Username and password required', 'error')
            return redirect(url_for('signup'))
        users = read_users()
        if username in users:
            flash('Username already exists', 'error')
            return redirect(url_for('signup'))
        strong, reasons = is_strong_password(password)
        if not strong:
            flash('Password too weak; please include: ' + ', '.join(reasons), 'error')
            return redirect(url_for('signup'))
        # store user with secure hash
        users[username] = {'pw': generate_password_hash(password)}
        write_users(users)
        # migrate guest gamestate if exists
        guest_id = session.get('user_id')
        if guest_id:
            try:
                gp = _gamestate_path(guest_id)
                up = _gamestate_path(username)
                if os.path.exists(gp) and not os.path.exists(up):
                    open(up, 'wb').write(open(gp, 'rb').read())
            except Exception:
                pass
        session['username'] = username
        flash('Account created and signed in', 'success')
        return redirect(url_for('index'))

    # GET: provide header context
    uid = get_user_id()
    user = current_user()
    gs = load_gamestate(user or uid)
    return render_template('signup.html', current_user=user, points=gs.get('points',0), rank=gs.get('rank','Unranked'), daily_streak=gs.get('daily_streak', 0))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        users = read_users()
        if username not in users or not check_password_hash(users.get(username, {}).get('pw',''), password):
            flash('Invalid credentials', 'error')
            return redirect(url_for('login'))
        # user authenticated
        # migrate guest gamestate if present
        guest_id = session.get('user_id')
        if guest_id:
            try:
                gp = _gamestate_path(guest_id)
                up = _gamestate_path(username)
                if os.path.exists(gp) and not os.path.exists(up):
                    open(up, 'wb').write(open(gp, 'rb').read())
            except Exception:
                pass
        session['username'] = username
        flash('Signed in', 'success')
        return redirect(url_for('index'))
    uid = get_user_id()
    user = current_user()
    gs = load_gamestate(user or uid)
    return render_template('login.html', current_user=user, points=gs.get('points',0), rank=gs.get('rank','Unranked'), daily_streak=gs.get('daily_streak', 0))


@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('Signed out', 'info')
    return redirect(url_for('index'))


@app.route('/pools/<pid>/special')
def pools_special(pid):
    pools = read_pools()
    if pid == 'builtin':
        meta = {'id': 'builtin', 'path': None, 'orig_name': 'Built-in pool'}
    else:
        meta = next((p for p in pools if p['id']==pid), None)
    if not meta:
        return redirect(url_for('pools'))
    # check per-pool wrong_count and don't start if there are none
    s = compute_stats_for_pool(meta)
    if s.get('wrong_count', 0) == 0:
        # nothing to review
        return redirect(url_for('pools'))
    # load questions and per-pool progress
    if meta.get('id') == 'builtin':
        qs = load_questions(None)
        prog = load_progress(PROGRESS_FILE)
    else:
        qs = load_questions(meta['path'])
        prog = {}
        prog_fp = f"{DATA_DIR}/progress_{meta['id']}.json"
        if os.path.exists(prog_fp):
            try:
                import json as _json
                raw = _json.load(open(prog_fp, 'r', encoding='utf-8'))
                prog = {k: CardState(**v) for k,v in raw.items()}
            except Exception:
                prog = {}
    sid = uuid.uuid4().hex
    app_state[sid] = {
        'pool': [q.__dict__ for q in qs],
        'num': 10,
        'index': 0,
        'set': [q.__dict__ for q in choose_special_set(qs, 10, prog)],
        'wrong': [],
        'progress': {k: v.__dict__ for k, v in prog.items()},
    }
    session['sid'] = sid
    session['pool_id'] = pid
    return redirect(url_for('question'))


@app.route('/pools/<pid>/start', methods=['GET', 'POST'])
def pools_start(pid):
    pools = read_pools()
    if pid == 'builtin':
        meta = {'id': 'builtin', 'path': None, 'orig_name': 'Built-in pool'}
    else:
        meta = next((p for p in pools if p['id']==pid), None)
    if not meta:
        return redirect(url_for('pools'))
    if request.method == 'POST':
        num = int(request.form.get('num') or 10)
        # load questions for builtin vs uploaded
        if meta.get('id') == 'builtin':
            pool = BUILTIN[:]
        else:
            all_qs = load_questions(meta['path'])
            pool = all_qs
        # load per-pool progress if available (so choose_exam_set uses it)
        prog = {}
        if meta.get('id') == 'builtin':
            # fall back to global progress file for builtin
            prog = load_progress(PROGRESS_FILE)
        else:
            prog_fp = f"{DATA_DIR}/progress_{meta['id']}.json"
            if os.path.exists(prog_fp):
                try:
                    import json as _json
                    raw = _json.load(open(prog_fp, 'r', encoding='utf-8'))
                    prog = {k: CardState(**v) for k, v in raw.items()}
                except Exception:
                    prog = {}

        sid = uuid.uuid4().hex
        app_state[sid] = {
            'pool': [q.__dict__ for q in pool],
            'num': num,
            'index': 0,
            'set': [q.__dict__ for q in choose_exam_set(pool, num, prog)],
            'wrong': [],
            'progress': {k: v.__dict__ for k, v in prog.items()},
        }
        session['sid'] = sid
        # remember current pool id for saving progress to per-pool file
        session['pool_id'] = pid
        return redirect(url_for('question'))
    return render_template('pools_start.html', meta=meta, current_user=current_user())


@app.route('/pools/<pid>/stats')
def pools_stats(pid):
    # allow builtin
    if pid == 'builtin':
        meta = {'id': 'builtin', 'path': None, 'orig_name': 'Built-in pool'}
    else:
        pools = read_pools()
        meta = next((p for p in pools if p['id']==pid), None)
        if not meta:
            return redirect(url_for('pools'))
    stats = compute_stats_for_pool(meta)
    times = compute_progress_timeseries(meta)
    uid = get_user_id()
    gs = load_gamestate(uid)
    # update daily streak when viewing stats
    gs = update_daily_streak(gs)
    save_gamestate(gs, uid)
    # build extra summary: correct / incorrect counts and accuracy% from per-pool progress
    extra = {'correct': 0, 'incorrect': 0, 'accuracy': 0}
    prog_fp = PROGRESS_FILE if meta.get('id') == 'builtin' else f"{DATA_DIR}/progress_{meta['id']}.json"
    if os.path.exists(prog_fp):
        try:
            import json as _json
            raw = _json.load(open(prog_fp, 'r', encoding='utf-8'))
            correct = sum(int(v.get('correct_streak', 0)) for v in raw.values())
            incorrect = sum(int(v.get('incorrect_count', 0)) for v in raw.values())
            denom = correct + incorrect
            acc = int((correct * 100) / denom) if denom else 0
            extra = {'correct': correct, 'incorrect': incorrect, 'accuracy': acc}
        except Exception:
            extra = {'correct': 0, 'incorrect': 0, 'accuracy': 0}

    return render_template('pool_stats.html', meta=meta, stats=stats, times=times, extra=extra, points=gs.get('points',0), rank=gs.get('rank','Unranked'), daily_streak=gs.get('daily_streak', 0), current_user=current_user())

@app.route('/question', methods=['GET', 'POST'])
def question():
    sid = session.get('sid')
    if not sid or sid not in app_state:
        return redirect(url_for('index'))
    state = app_state[sid]
    s = state['set']
    idx = state.get('index', 0)
    if idx >= len(s):
        # review wrong if any
        if state.get('wrong'):
            state['set'] = state['wrong']
            state['wrong'] = []
            state['index'] = 0
            return redirect(url_for('question'))
        return "Session complete. <a href='/end'>End and Save</a>"

    qd = s[idx]
    # convert dict back to simple object-like for template
    class Q:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    q = Q(**qd)

    if request.method == 'POST':
        choice = request.form.get('choice')
        prog_raw = state.get('progress', {})
        # restore CardState objects
        prog = {k: CardState(**v) for k,v in prog_raw.items()}
        ok = (choice == q.answer)
        st = prog.get(q.id, CardState())
        if ok:
            st.promote()
        else:
            st.demote()
            # append to wrong
            state['wrong'].append(q.__dict__)
        prog[q.id] = st
        # write back
        state['progress'] = {k:v.__dict__ for k,v in prog.items()}
        state['index'] = idx + 1

        # gamification: award points (per-user) after answering
        user = current_user()
        uid = user or get_user_id()
        gs = load_gamestate(uid)
        # ensure daily streak is current for this activity
        gs = update_daily_streak(gs)
        # implement streak-based doubling: correct streak doubles points each successive correct
        # and wrong streak doubles negative penalty similarly. We store answer_streak in gamestate
        streak = gs.get('answer_streak', 0) or 0
        if ok:
            # if previous streak was negative (wrong streak), reset
            if streak < 0:
                streak = 0
            # next point value: base 10, doubles each correct in streak: 10 * (2 ** streak)
            delta = 10 * (2 ** streak)
            streak = streak + 1
            reason = 'correct'
        else:
            # if previous streak was positive (correct streak), reset
            if streak > 0:
                streak = 0
            # wrong penalties: -2, then -4, -8, ...
            delta = - (2 * (2 ** abs(streak))) if streak < 0 else -2
            streak = streak - 1
            reason = 'incorrect'
        gs['answer_streak'] = streak
        award_points(gs, delta, reason, user_id=uid)
        # render result page
    return render_template('result.html', ok=ok, q=q, points_delta=delta, points=gs.get('points',0), rank=gs.get('rank','Unranked'), daily_streak=gs.get('daily_streak', 0), current_user=current_user())

    # GET: build letter-option pairs for template
    letters = ['A', 'B', 'C', 'D']
    pairs = list(zip(letters, q.options))
    # load points for signed-in user if available
    user = current_user()
    pts = load_gamestate(user or get_user_id()).get('points', 0)
    return render_template('question.html', q=q, pairs=pairs, pool_name=session.get('pool_id'), points=pts, current_user=user)

@app.route('/end')
def end():
    # persist progress
    sid = session.get('sid')
    if sid and sid in app_state:
        state = app_state.pop(sid)
        prog = {k: CardState(**v) for k, v in state.get('progress', {}).items()}
        # save global progress file (for legacy/global usage)
        save_progress(PROGRESS_FILE, prog)
        # also save per-pool progress if this session came from a specific pool
        pool_id = session.get('pool_id')
        if pool_id:
            ensure_data_dir()
            prog_fp = f"{DATA_DIR}/progress_{pool_id}.json"
            try:
                import json as _json
                existing = {}
                if os.path.exists(prog_fp):
                    try:
                        existing = _json.load(open(prog_fp, 'r', encoding='utf-8'))
                    except Exception:
                        existing = {}
                # merge/overwrite with latest progress
                new_prog = {k: v.__dict__ for k, v in prog.items()}
                existing.update(new_prog)
                with open(prog_fp, 'w', encoding='utf-8') as f:
                    _json.dump(existing, f, indent=2)
            except Exception:
                pass

        log_event(LOG_FILE, {"mode": "web", "count_pool": len(state.get('pool', []))})
        # update last_active for gamestate on session end
        try:
            uid = session.get('user_id')
            if uid:
                gs = load_gamestate(uid)
                gs['last_active'] = datetime.utcnow().isoformat(timespec='seconds')
                save_gamestate(gs, uid)
        except Exception:
            pass
        # clear session pool id
        session.pop('pool_id', None)
        session.pop('sid', None)
    return "Saved progress. <a href='/'>Back to home</a>"

if __name__ == '__main__':
    app.run(port=5004, debug=True)
