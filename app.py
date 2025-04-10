from flask import Flask, request, render_template, redirect, url_for, session, jsonify
import json
import os
import redis
from datetime import datetime, timedelta
import logging

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", 'your-secret-key-here')  # Vercel 環境變數或預設值

# 配置日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 獲取 Redis URL
redis_url = os.getenv("REDIS_URL")
if redis_url:
    logger.info(f"Attempting to connect to Redis with URL: {redis_url[:20]}... (masked)")
    try:
        kv = redis.from_url(redis_url, decode_responses=True)  # 確保返回字串而非字節
        kv.ping()
        logger.info("Redis connection established successfully")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        kv = None
else:
    logger.error("REDIS_URL environment variable is missing")
    kv = None

# 若 Redis 不可用，啟動會失敗（Serverless 不適合記憶體模式）
if kv is None:
    raise RuntimeError("Redis connection required for server deployment")

def load_data():
    try:
        data = kv.get("lottery_data")
        return json.loads(data) if data else []
    except Exception as e:
        logger.error(f"Load data error: {e}")
        return []

def save_data(data):
    try:
        kv.set("lottery_data", json.dumps(data))
        logger.info("Data saved to Redis")
    except Exception as e:
        logger.error(f"Save data error: {e}")

def load_users():
    try:
        users = kv.get("users")
        return json.loads(users) if users else ["牙珍", "牙依"]  # 初始用戶
    except Exception as e:
        logger.error(f"Load users error: {e}")
        return ["牙珍", "牙依"]

def save_users(users):
    try:
        kv.set("users", json.dumps(users))
        logger.info("Users saved to Redis")
    except Exception as e:
        logger.error(f"Save users error: {e}")

BANKS = ["中國銀行", "大豐銀行", "廣發銀行", "工商銀行", "Mpay", "支付寶", "UEPAY", "國際銀行"]
VALUES = [0, 10, 20, 50, 100, 200]

def get_week_range(today):
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=4)
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')

def get_available_banks(data, user):
    used_banks = {entry['entries'][0]['bank'] for entry in data if entry['person'] == user}
    return [bank for bank in BANKS if bank not in used_banks]

def summarize_data(data, selected_user, start_date=None, end_date=None):
    summary = {bank: {'count': 0, 'total_value': 0} for bank in BANKS}
    for entry in data:
        entry_date = datetime.strptime(entry['date'], '%Y-%m-%d')
        if start_date and end_date:
            if not (start_date <= entry_date <= end_date):
                continue
        if entry['person'] != selected_user:
            continue
        bank = entry['entries'][0]['bank']
        total_value = sum(e['value'] for e in entry['entries'])
        summary[bank]['count'] += 3
        summary[bank]['total_value'] += total_value
    return summary

@app.route('/', methods=['GET', 'POST'])
def index():
    logger.info("Entering index route")
    data = load_data()
    users = load_users()
    selected_bank = request.args.get('selected_bank', None)
    selected_user_summary = request.args.get('selected_user_summary', users[0])
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    error_message = None

    last_user = session.get('last_user', users[0])
    current_user = request.args.get('person', last_user)
    available_banks = get_available_banks(data, current_user)

    if request.method == 'POST':
        try:
            person = request.form['person']
            date = request.form['date']
            bank = request.form['bank']
            if person not in users:
                raise ValueError("無效的使用者")
            if bank not in get_available_banks(data, person):
                raise ValueError("此銀行已被使用")
            value1 = int(request.form['value1'])
            value2 = int(request.form['value2'])
            value3 = int(request.form['value3'])
            entries = [
                {'bank': bank, 'value': value1},
                {'bank': bank, 'value': value2},
                {'bank': bank, 'value': value3}
            ]
            data.append({'date': date, 'entries': entries, 'person': person})
            save_data(data)
            session['last_user'] = person
            return redirect(url_for('index'))
        except KeyError as e:
            error_message = f"表單提交錯誤：缺少欄位 {e.args[0]}"
        except ValueError as e:
            error_message = str(e)

    filtered_data = [entry for entry in data if entry['entries'][0]['bank'] == selected_bank] if selected_bank else data
    today = datetime.now()
    week_start, week_end = get_week_range(today)

    if start_date and end_date:
        try:
            summary_start = datetime.strptime(start_date, '%Y-%m-%d')
            summary_end = datetime.strptime(end_date, '%Y-%m-%d')
            if summary_start > summary_end:
                error_message = "開始日期不能晚於結束日期"
            else:
                summary = summarize_data(data, selected_user_summary, summary_start, summary_end)
        except ValueError:
            error_message = "日期格式錯誤"
            summary = summarize_data(data, selected_user_summary)
    else:
        summary_start = datetime.strptime(week_start, '%Y-%m-%d')
        summary_end = datetime.strptime(week_end, '%Y-%m-%d')
        summary = summarize_data(data, selected_user_summary, summary_start, summary_end)

    today_str = today.strftime('%Y-%m-%d')
    return render_template('index.html', data=filtered_data, banks=BANKS, values=VALUES, users=users, today=today_str,
                           selected_bank=selected_bank, selected_user_summary=selected_user_summary, summary=summary,
                           week_start=week_start, week_end=week_end, start_date=start_date, end_date=end_date,
                           error_message=error_message, last_user=current_user, available_banks=available_banks)

@app.route('/manage_users', methods=['GET', 'POST'])
def manage_users():
    users = load_users()
    error_message = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            new_user = request.form.get('new_user')
            if new_user and new_user not in users:
                users.append(new_user)
                save_users(users)
            elif new_user in users:
                error_message = "用戶已存在"
            else:
                error_message = "請輸入用戶名"
        elif action == 'delete':
            user_to_delete = request.form.get('user_to_delete')
            if user_to_delete in users:
                users.remove(user_to_delete)
                save_users(users)
            else:
                error_message = "用戶不存在"
        return redirect(url_for('manage_users'))
    return render_template('manage_users.html', users=users, error_message=error_message)

@app.route('/api/summary', methods=['GET'])
def get_summary():
    data = load_data()
    users = load_users()
    selected_user = request.args.get('user', users[0])
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            summary = summarize_data(data, selected_user, start, end)
        except ValueError:
            summary = summarize_data(data, selected_user)
    else:
        today = datetime.now()
        week_start, week_end = get_week_range(today)
        summary = summarize_data(data, selected_user, datetime.strptime(week_start, '%Y-%m-%d'), datetime.strptime(week_end, '%Y-%m-%d'))
    return jsonify(summary)

@app.route('/api/history', methods=['GET'])
def get_history():
    data = load_data()
    selected_bank = request.args.get('bank', None)
    filtered_data = [entry for entry in data if entry['entries'][0]['bank'] == selected_bank] if selected_bank else data
    return jsonify(filtered_data)

@app.route('/delete/<int:index>', methods=['POST'])
def delete(index):
    data = load_data()
    if 0 <= index < len(data):
        data.pop(index)
        save_data(data)
    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))  # Vercel 用 PORT，本地預設 5000
    app.run(host='0.0.0.0', port=port)