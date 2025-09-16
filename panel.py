import os
import json
import subprocess
from datetime import date, datetime, timedelta

import requests
from flask import Flask, request, redirect, url_for, render_template_string, session
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_ID  = int(os.getenv("GROUP_ID", "0"))
ADMINS    = {int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip().isdigit()}

PANEL_HOST   = os.getenv("PANEL_HOST", "0.0.0.0")
PANEL_PORT   = int(os.getenv("PANEL_PORT", "8000"))
PANEL_PASS   = os.getenv("ADMIN_PANEL_PASSWORD", "changeme")
PANEL_SECRET = os.getenv("PANEL_SECRET", "supersecret123")

STUDENTS_FILE   = os.path.join(BASE_DIR, "students.txt")
SCHEDULE_FILE   = os.path.join(BASE_DIR, "schedule.json")
START_DATE_FILE = os.path.join(BASE_DIR, "start_date.txt")
EXCEPTIONS_FILE = os.path.join(BASE_DIR, "exceptions.json")
DEBTORS_FILE    = os.path.join(BASE_DIR, "debtors.json")
SIM_DATE_FILE   = os.path.join(BASE_DIR, "sim_date.txt")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)
app.config["SECRET_KEY"] = PANEL_SECRET

def read_text(path: str) -> str:
    return open(path, "r", encoding="utf-8").read() if os.path.exists(path) else ""

def write_text(path: str, text: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def load_json(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_students() -> list[str]:
    text = read_text(STUDENTS_FILE)
    out, seen = [], set()
    for line in text.splitlines():
        s = line.strip()
        if not s: continue
        key = s.lower().replace("ё", "е")
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out

def load_start_date() -> date:
    s = read_text(START_DATE_FILE).strip()
    if s:
        return datetime.strptime(s, "%Y-%m-%d").date()
    return date.today()

def save_start_date(d: date):
    write_text(START_DATE_FILE, d.strftime("%Y-%m-%d"))

def load_sim_date() -> date | None:
    s = read_text(SIM_DATE_FILE).strip()
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()

def save_sim_date(d: date | None):
    if d is None:
        if os.path.exists(SIM_DATE_FILE):
            os.remove(SIM_DATE_FILE)
    else:
        write_text(SIM_DATE_FILE, d.strftime("%Y-%m-%d"))

def working_days_count(d0: date, d1: date) -> int:
    if d1 <= d0:
        return 0
    days = (d1 - d0).days
    full_weeks, rest = divmod(days, 7)
    cnt = full_weeks * 6
    for i in range(rest):
        wd = (d0.weekday() + i) % 7
        if wd != 6:
            cnt += 1
    return cnt

def get_base_pair(for_date: date, duty_list: list[str], start_date: date) -> list[str]:
    n = len(duty_list)
    if n == 0:
        return ["?", "?"]
    steps = working_days_count(start_date, for_date)
    pair_index = steps % ((n + 1) // 2)
    i = (2 * pair_index) % n
    j = (i + 1) % n
    return [duty_list[i], duty_list[j]]

def wd_key(d: date) -> str:
    return ["mon","tue","wed","thu","fri","sat","sun"][d.weekday()]

def get_schedule_for(d: date, schedule: dict) -> list[str]:
    dk = d.strftime("%Y-%m-%d")
    if dk in schedule:
        return schedule[dk]
    k = wd_key(d)
    return schedule.get(k, [])

def render_schedule(lines: list[str]) -> str:
    return "—" if not lines else "\n".join(f"• {x}" for x in lines)

def get_pair(for_date: date) -> list[str]:
    duty_list   = load_students()
    start_date  = load_start_date()
    exceptions  = load_json(EXCEPTIONS_FILE, {})
    key         = for_date.strftime("%Y-%m-%d")
    return exceptions.get(key, get_base_pair(for_date, duty_list, start_date))

def render_post(for_date: date) -> str:
    pair = get_pair(for_date)
    schedule = load_json(SCHEDULE_FILE, {"mon":[], "tue":[], "wed":[], "thu":[], "fri":[], "sat":[]})
    lines = get_schedule_for(for_date, schedule)
    return (
        f"📅 Сегодня {for_date.strftime('%d.%m.%Y')}\n"
        f"🧹 Дежурные: {pair[0]} и {pair[1]}\n\n"
        f"📚 Расписание:\n{render_schedule(lines)}"
    )

def tg_send_message(text: str) -> int:
    r = requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": GROUP_ID, "text": text, "parse_mode": "HTML"
    }, timeout=20)
    r.raise_for_status()
    return r.json()["result"]["message_id"]

def tg_pin(message_id: int):
    r = requests.post(f"{TELEGRAM_API}/pinChatMessage", json={
        "chat_id": GROUP_ID, "message_id": message_id, "disable_notification": True
    }, timeout=20)
    r.raise_for_status()

def service_restart():
    try:
        subprocess.run(["systemctl", "restart", "dutybot"], check=False)
    except Exception:
        pass

def login_required(fn):
    def wrapper(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper

PAGE = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>DutyBot Панель</title>
  <style>
    body { font-family: system-ui, Arial; margin: 24px; max-width: 900px }
    h1 { margin-top: 0 }
    form { margin: 12px 0; padding: 12px; border: 1px solid #ddd; border-radius: 8px; }
    input[type=text], textarea { width: 100%; padding: 8px; font-family: inherit }
    button { padding: 8px 14px; }
    .row { display:flex; gap:16px; flex-wrap:wrap }
    .col { flex:1; min-width: 260px }
    pre { background:#f7f7f7; padding:10px; border-radius:8px }
  </style>
</head>
<body>
  <h1>DutyBot — веб-панель</h1>
  <p>Сегодня: <b>{{ today }}</b> &nbsp;|&nbsp; Сим-дата: <b>{{ sim_date or "—" }}</b></p>
  <p>Текущая пара: <b>{{ pair[0] }}</b> и <b>{{ pair[1] }}</b></p>

  <div class="row">
    <div class="col">
      <form method="post" action="{{ url_for('post_today') }}">
        <h3>📌 Ежедневный пост (сегодня) + пин</h3>
        <button type="submit">Отправить и закрепить</button>
      </form>

      <form method="post" action="{{ url_for('post_on_date') }}">
        <h3>📌 Пост на дату + пин</h3>
        <input type="text" name="date" placeholder="YYYY-MM-DD">
        <button type="submit">Отправить</button>
      </form>

      <form method="post" action="{{ url_for('send_text') }}">
        <h3>📝 Сообщение в группу</h3>
        <textarea name="msg" rows="3" placeholder="Текст сообщения"></textarea><br>
        <button type="submit">Отправить</button>
      </form>
    </div>

    <div class="col">
      <form method="post" action="{{ url_for('next_day') }}">
        <h3>⏭ Сим-дата Next</h3>
        <button type="submit">Следующий рабочий день</button>
      </form>

      <form method="post" action="{{ url_for('prev_day') }}">
        <h3>⏮ Сим-дата Prev</h3>
        <button type="submit">Предыдущий рабочий день</button>
      </form>

      <form method="post" action="{{ url_for('skip_days') }}">
        <h3>⏩ Сдвиг очереди</h3>
        <input type="text" name="n" placeholder="Число рабочих дней, например 1">
        <button type="submit">Сдвинуть и перезапустить бота</button>
      </form>

      <form method="post" action="{{ url_for('seed_only') }}">
        <h3>🎯 Seed Only (разово)</h3>
        <input type="text" name="pair" placeholder="ФИО1;ФИО2">
        <input type="text" name="date" placeholder="YYYY-MM-DD (опц.)">
        <button type="submit">Зафиксировать пару</button>
      </form>

      <form method="post" action="{{ url_for('reset_all') }}">
        <h3>🧨 Полный ресет</h3>
        <button type="submit" onclick="return confirm('Точно очистить все данные и перезапустить бота?')">Сбросить всё</button>
      </form>
    </div>
  </div>

  <div class="row">
    <div class="col">
      <form method="get" action="{{ url_for('students_edit') }}">
        <h3>👥 База студентов</h3>
        <button type="submit">Открыть и редактировать</button>
      </form>
    </div>
    <div class="col">
      <form method="get" action="{{ url_for('schedule_edit') }}">
        <h3>📚 Расписание</h3>
        <button type="submit">Открыть и редактировать</button>
      </form>
    </div>
  </div>

  <h3>📋 Должники</h3>
  {% if debtors %}
    <pre>{{ debtors }}</pre>
  {% else %}
    <p>— пусто —</p>
  {% endif %}

  <p><a href="{{ url_for('logout') }}">Выйти</a></p>
</body>
</html>
"""

EDIT_TXT = """
<h2>{{ title }}</h2>
<form method="post">
  <textarea name="content" rows="18">{{ content }}</textarea><br>
  <button type="submit">Сохранить и перезапустить бота</button>
  <a href="{{ url_for('index') }}">Назад</a>
</form>
"""

EDIT_JSON = """
<h2>{{ title }}</h2>
<form method="post">
  <textarea name="content" rows="20">{{ content }}</textarea><br>
  <button type="submit">Сохранить и перезапустить бота</button>
  <a href="{{ url_for('index') }}">Назад</a>
</form>
"""

LOGIN_PAGE = """
<h2>Вход в панель</h2>
<form method="post">
  <input type="password" name="password" placeholder="Пароль администратора" style="width:320px">
  <button type="submit">Войти</button>
</form>
"""

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == PANEL_PASS:
            session["authed"] = True
            return redirect(url_for("index"))
        return "Неверный пароль", 403
    return render_template_string(LOGIN_PAGE)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def login_required(fn):
    def wrapper(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper

@app.route("/")
@login_required
def index():
    sim = load_sim_date()
    t = sim or date.today()
    pair = get_pair(t)
    debtors = "\n".join(load_json(DEBTORS_FILE, []))
    return render_template_string(
        PAGE,
        today=date.today().strftime("%d.%m.%Y"),
        sim_date=t.strftime("%d.%m.%Y") if sim else None,
        pair=pair,
        debtors=debtors
    )

@app.post("/post_today")
@login_required
def post_today():
    d = load_sim_date() or date.today()
    mid = tg_send_message(render_post(d))
    tg_pin(mid)
    return redirect(url_for("index"))

@app.post("/post_on_date")
@login_required
def post_on_date():
    ds = request.form.get("date", "").strip()
    try:
        d = datetime.strptime(ds, "%Y-%m-%d").date()
    except Exception:
        return "Формат даты: YYYY-MM-DD", 400
    mid = tg_send_message(render_post(d))
    tg_pin(mid)
    return redirect(url_for("index"))

@app.post("/send_text")
@login_required
def send_text():
    text = request.form.get("msg", "").strip()
    if text:
        tg_send_message(text)
    return redirect(url_for("index"))

def next_workday(d: date) -> date:
    t = d
    while True:
        t += timedelta(days=1)
        if t.weekday() != 6:
            return t

def prev_workday(d: date) -> date:
    t = d
    while True:
        t -= timedelta(days=1)
        if t.weekday() != 6:
            return t

@app.post("/next")
@login_required
def next_day():
    d = load_sim_date() or date.today()
    d = next_workday(d)
    save_sim_date(d)
    mid = tg_send_message(render_post(d))
    tg_pin(mid)
    return redirect(url_for("index"))

@app.post("/prev")
@login_required
def prev_day():
    d = load_sim_date() or date.today()
    d = prev_workday(d)
    save_sim_date(d)
    mid = tg_send_message(render_post(d))
    tg_pin(mid)
    return redirect(url_for("index"))

@app.post("/skip")
@login_required
def skip_days():
    n_s = request.form.get("n", "").strip()
    if not n_s or not n_s.lstrip("-").isdigit():
        return "Укажи целое число рабочих дней", 400
    n = int(n_s)
    d = load_start_date()
    step = -1 if n > 0 else 1
    k = abs(n)
    while k > 0:
        d = d + timedelta(days=step)
        if d.weekday() != 6:
            k -= 1
    save_start_date(d)
    service_restart()
    return redirect(url_for("index"))

def resolve_name(inp: str, duty_list: list[str]) -> str:
    def _first_two(s: str) -> str:
        parts = s.split()
        return " ".join(parts[:2])
    want = _first_two(inp).lower().replace("ё", "е")
    for name in duty_list:
        if _first_two(name).lower().replace("ё", "е") == want:
            return name
    fam = inp.split()[0].lower().replace("ё", "е")
    candidates = [n for n in duty_list if n.split()[0].lower().replace("ё","е")==fam]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(f"Не нашёл в списке: {inp}")

@app.post("/seed_only")
@login_required
def seed_only():
    pair = request.form.get("pair", "")
    ds = request.form.get("date", "").strip()
    d = date.today() if not ds else datetime.strptime(ds, "%Y-%m-%d").date()
    if ";" not in pair:
        return "Нужно ФИО1;ФИО2", 400
    raw1, raw2 = [x.strip() for x in pair.split(";", 1)]
    duty_list = load_students()
    try:
        n1 = resolve_name(raw1, duty_list)
        n2 = resolve_name(raw2, duty_list)
    except ValueError as e:
        return str(e), 400
    exc = load_json(EXCEPTIONS_FILE, {})
    exc[d.strftime("%Y-%m-%d")] = [n1, n2]
    save_json(EXCEPTIONS_FILE, exc)
    mid = tg_send_message(render_post(d))
    tg_pin(mid)
    return redirect(url_for("index"))

@app.post("/reset_all")
@login_required
def reset_all():
    save_start_date(date.today())
    save_json(EXCEPTIONS_FILE, {})
    save_json(DEBTORS_FILE, [])
    if os.path.exists(SIM_DATE_FILE):
        os.remove(SIM_DATE_FILE)
    service_restart()
    return redirect(url_for("index"))

@app.get("/students")
@login_required
def students_edit():
    return render_template_string(EDIT_TXT, title="Редактор students.txt", content=read_text(STUDENTS_FILE))

@app.post("/students")
@login_required
def students_save():
    content = request.form.get("content", "")
    write_text(STUDENTS_FILE, content.strip() + ("
" if content and not content.endswith("\n") else ""))
    service_restart()
    return redirect(url_for("index"))

@app.get("/schedule")
@login_required
def schedule_edit():
    return render_template_string(EDIT_JSON, title="Редактор schedule.json", content=json.dumps(load_json(SCHEDULE_FILE, {}), ensure_ascii=False, indent=2))

@app.post("/schedule")
@login_required
def schedule_save():
    raw = request.form.get("content", "")
    try:
        data = json.loads(raw)
    except Exception as e:
        return f"JSON ошибка: {e}", 400
    save_json(SCHEDULE_FILE, data)
    service_restart()
    return redirect(url_for("index"))

if __name__ == "__main__":
    if not BOT_TOKEN or not GROUP_ID or not ADMINS:
        raise RuntimeError("Заполни .env: BOT_TOKEN, GROUP_ID, ADMINS")
    app.run(host=PANEL_HOST, port=PANEL_PORT)
