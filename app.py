from flask import Flask, request, render_template, redirect, url_for, session, jsonify
import json
import os
import redis
from werkzeug.exceptions import BadRequestKeyError
from datetime import datetime, timedelta
import logging

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", 'your-secret-key-here')

# 配置日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 檢查並組合 Redis URL
redis_url = os.getenv("UPSTASH_REDIS_REST_URL")
redis_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
if redis_url and redis_token:
    # 移除 https://，組合為 rediss://token@host 格式
    redis_full_url = f"rediss://{redis_token}@{redis_url.replace('https://', '')}"
    try:
        kv = redis.from_url(redis_full_url)
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        kv = None
else:
    logger.warning("Redis URL or Token missing, using in-memory fallback")
    kv = None

BANKS = ["中國銀行", "大豐銀行", "廣發銀行", "工商銀行", "Mpay", "支付寶", "UEPAY", "國際銀行"]
VALUES = [0, 10, 20, 50, 100, 200]
USERS = ["牙珍", "牙依"]

def get_week_range(today):
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=4)
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')

def load_data():
    if kv is None:
        logger.warning("Redis unavailable, returning empty data")
        return []
    try:
        data = kv.get("lottery_data")
        return json.loads(data) if data else []
    except Exception as e:
        logger.error(f"Load data error: {e}")
        return []

def save_data(data):
    if kv is None:
        logger.warning("Redis unavailable, data not saved")
        return
    try:
        kv.set("lottery_data", json.dumps(data))
    except Exception as e:
        logger.error(f"Save data error: {e}")

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
    selected_bank = request.args.get('selected_bank', None)
    selected_user_summary = request.args.get('selected_user_summary', USERS[0])
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    error_message = None

    last_user = session.get('last_user', USERS[0])
    current_user = request.args.get('person', last_user)
    available_banks = get_available_banks(data, current_user)

    if request.method == 'POST':
        try:
            person = request.form['person']
            date = request.form['date']
            bank = request.form['bank']
            if person not in USERS:
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
        except BadRequestKeyError as e:
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
    return render_template('index.html', data=filtered_data, banks=BANKS, values=VALUES, users=USERS, today=today_str,
                           selected_bank=selected_bank, selected_user_summary=selected_user_summary, summary=summary,
                           week_start=week_start, week_end=week_end, start_date=start_date, end_date=end_date,
                           error_message=error_message, last_user=current_user, available_banks=available_banks)

@app.route('/api/summary', methods=['GET'])
def get_summary():
    data = load_data()
    selected_user = request.args.get('user', USERS[0])
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
    port = int(os.getenv("PORT", 3000))
    app.run(host='0.0.0.0', port=port)