from flask import Flask, request, render_template, redirect, url_for
import json
from datetime import datetime, timedelta
from werkzeug.exceptions import BadRequestKeyError

app = Flask(__name__)

BANKS = ["中國銀行", "大豐銀行", "廣發銀行", "工商銀行", "Mpay", "支付寶", "UEPAY", "國際銀行"]
VALUES = [0, 10, 20, 50, 100, 200]

def load_data():
    try:
        with open('lottery_data.json', 'r') as f:
            return json.load(f)
    except:
        return []

def save_data(data):
    with open('lottery_data.json', 'w') as f:
        json.dump(data, f)

def get_week_range(today):
    start = today - timedelta(days=today.weekday())  # 週一
    end = start + timedelta(days=4)  # 週五
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')

def summarize_data(data, start_date=None, end_date=None):
    summary = {bank: {'count': 0, 'total_value': 0} for bank in BANKS}
    for entry in data:
        entry_date = datetime.strptime(entry['date'], '%Y-%m-%d')
        if start_date and end_date:
            if not (start_date <= entry_date <= end_date):
                continue
        bank = entry['entries'][0]['bank']
        total_value = sum(e['value'] for e in entry['entries'])
        if bank in summary:
            summary[bank]['count'] += 3
            summary[bank]['total_value'] += total_value
        else:
            print(f"警告：找到未知銀行 '{bank}'，已忽略")
    return summary

@app.route('/', methods=['GET', 'POST'])
def index():
    data = load_data()
    selected_bank = request.args.get('selected_bank', None)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    error_message = None  # 用於顯示錯誤訊息
    
    if request.method == 'POST':
        try:
            date = request.form['date']
            bank = request.form['bank']
            value1 = int(request.form['value1'])
            value2 = int(request.form['value2'])
            value3 = int(request.form['value3'])
            entries = [
                {'bank': bank, 'value': value1},
                {'bank': bank, 'value': value2},
                {'bank': bank, 'value': value3}
            ]
            data.append({'date': date, 'entries': entries})
            save_data(data)
            return redirect(url_for('index'))
        except BadRequestKeyError as e:
            error_message = f"表單提交錯誤：缺少欄位 {e.args[0]}"
        except ValueError:
            error_message = "面值必須是數字"
    
    # 篩選歷史記錄
    filtered_data = [entry for entry in data if entry['entries'][0]['bank'] == selected_bank] if selected_bank else data
    
    # 計算本週範圍
    today = datetime.now()  # 2025-04-01
    week_start, week_end = get_week_range(today)
    
    # 匯總時間範圍
    if start_date and end_date:
        try:
            summary_start = datetime.strptime(start_date, '%Y-%m-%d')
            summary_end = datetime.strptime(end_date, '%Y-%m-%d')
            if summary_start > summary_end:
                error_message = "開始日期不能晚於結束日期"
            else:
                summary = summarize_data(data, summary_start, summary_end)
        except ValueError:
            error_message = "日期格式錯誤"
            summary = summarize_data(data)  # 回退到全部數據
    else:
        summary_start = datetime.strptime(week_start, '%Y-%m-%d')
        summary_end = datetime.strptime(week_end, '%Y-%m-%d')
        summary = summarize_data(data, summary_start, summary_end)
    
    today_str = today.strftime('%Y-%m-%d')
    return render_template('index.html', data=filtered_data, banks=BANKS, values=VALUES, today=today_str, 
                           selected_bank=selected_bank, summary=summary, week_start=week_start, week_end=week_end,
                           start_date=start_date, end_date=end_date, error_message=error_message)

@app.route('/delete/<int:index>', methods=['POST'])
def delete(index):
    data = load_data()
    if 0 <= index < len(data):
        data.pop(index)
        save_data(data)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)