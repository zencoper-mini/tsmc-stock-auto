import requests
import pandas as pd
import sqlite3
import time
import random
import os
from datetime import datetime, timedelta

# GitHub 環境設定
STOCK_NO = "2330"
# GitHub Actions 每次執行都是乾淨環境，我們將資料庫存在當前目錄
DB_NAME = "tsmc_stock.db"
CSV_PATH = "tsmc_data_pivot.csv"
# 自動計算一年前日期
START_DATE_DT = datetime.now() - timedelta(days=365)

def safe_get_json(url, retries=2):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Referer': 'https://www.twse.com.tw/zh/page/trading/exchange/STOCK_DAY.html'
    }
    for i in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if "application/json" in response.headers.get("Content-Type", ""):
                return response.json()
            else:
                print(f"⚠️ 警告：證交所回傳了非資料內容。休息 5 分鐘...")
                time.sleep(300)
        except Exception as e:
            print(f"⚠️ 網路異常: {e}")
            time.sleep(10)
    return None

def update_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_data_v2 (
            日期 TEXT, 成交張數 INTEGER, 成交金額 TEXT, 收盤價 TEXT, 法人項目 TEXT, 買賣超股數 TEXT,
            PRIMARY KEY (日期, 法人項目)
        )
    ''')
    conn.commit()

    today = datetime.now()
    current_date = START_DATE_DT
    
    print(f"🚀 GitHub Actions 啟動 (目標: {START_DATE_DT.strftime('%Y-%m-%d')} 至今)")

    while current_date <= today:
        date_str = current_date.strftime("%Y%m%d")
        target_date = current_date.strftime("%Y-%m-%d")
        
        check_query = f"SELECT 1 FROM stock_data_v2 WHERE 日期 = '{target_date}' LIMIT 1"
        exists = pd.read_sql(check_query, conn)

        if exists.empty:
            stock_url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={date_str}&stockNo={STOCK_NO}"
            stock_data = safe_get_json(stock_url)
            
            if stock_data and stock_data.get("stat") == "OK":
                time.sleep(random.uniform(3, 6))
                inst_url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALLBUT0999"
                inst_data = safe_get_json(inst_url)
                
                if inst_data and inst_data.get("stat") == "OK":
                    df_s = pd.DataFrame(stock_data["data"], columns=stock_data["fields"])
                    df_s['日期'] = df_s['日期'].apply(lambda x: str(int(x.split('/')[0]) + 1911) + "-" + x.split('/')[1] + "-" + x.split('/')[2])
                    day_stock = df_s[df_s['日期'] == target_date]
                    
                    if not day_stock.empty:
                        df_i = pd.DataFrame(inst_data["data"], columns=inst_data["fields"])
                        tsmc_row = df_i[df_i['證券代號'] == STOCK_NO]
                        if not tsmc_row.empty:
                            day_stock_copy = day_stock.copy()
                            day_stock_copy['成交張數'] = day_stock_copy['成交股數'].str.replace(',', '').astype(float) // 1000
                            res = [
                                {'日期': target_date, '成交張數': int(day_stock_copy['成交張數'].values[0]), '成交金額': day_stock_copy['成交金額'].values[0], '收盤價': day_stock_copy['收盤價'].values[0], '法人項目': '外資', '買賣超股數': tsmc_row['外陸資買賣超股數(不含外資自營商)'].values[0]},
                                {'日期': target_date, '成交張數': int(day_stock_copy['成交張數'].values[0]), '成交金額': day_stock_copy['成交金額'].values[0], '收盤價': day_stock_copy['收盤價'].values[0], '法人項目': '投信', '買賣超股數': tsmc_row['投信買賣超股數'].values[0]},
                                {'日期': target_date, '成交張數': int(day_stock_copy['成交張數'].values[0]), '成交金額': day_stock_copy['成交金額'].values[0], '收盤價': day_stock_copy['收盤價'].values[0], '法人項目': '自營商', '買賣超股數': tsmc_row['自營商買賣超股數'].values[0]}
                            ]
                            pd.DataFrame(res).to_sql('stock_data_v2', conn, if_exists='append', index=False)
                            print(f"✅ {target_date} 更新成功")
            time.sleep(random.uniform(4, 8))
        current_date += timedelta(days=1)

    # 匯出 CSV
    raw_df = pd.read_sql("SELECT * FROM stock_data_v2", conn)
    if not raw_df.empty:
        raw_df['買賣超股數'] = raw_df['買賣超股數'].str.replace(',', '').astype(float)
        pivot_df = raw_df.pivot_table(index=['日期', '成交張數', '成交金額', '收盤價'], columns='法人項目', values='買賣超股數').reset_index()
        pivot_df.columns.name = None
        pivot_df = pivot_df.sort_values('日期', ascending=False)
        pivot_df.to_csv(CSV_PATH, index=False, encoding='utf-8-sig')
        print(f"📊 CSV 已更新。")
    conn.close()

if __name__ == "__main__":
    update_database()
