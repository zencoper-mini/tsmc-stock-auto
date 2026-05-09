import requests
import pandas as pd
import sqlite3
import time
import random
import os
from datetime import datetime, timedelta

# GitHub 環境設定
STOCK_NO = "2330"
DB_NAME = "tsmc_stock.db"
CSV_PATH = "tsmc_data_pivot.csv"
# 追蹤過去 365 天
START_DATE_DT = datetime.now() - timedelta(days=365)

def safe_get_json(url, retries=2):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Referer': 'https://twse.com.tw'
    }
    for i in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code == 200 and "application/json" in response.headers.get("Content-Type", "").lower():
                return response.json()
            else:
                print(f"⚠️ 伺服器回應異常 (Status: {response.status_code})。休息中...")
                time.sleep(300)
        except Exception as e:
            print(f"⚠️ 網路異常: {e}")
            time.sleep(10)
    return None

def clean_val(val):
    """清理數值字串中的逗號，並處理無資料情況"""
    v_str = str(val).replace(',', '').strip()
    if v_str in ['', '--', 'None']:
        return 0.0
    try:
        return float(v_str)
    except:
        return 0.0

def update_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # 建立表格，標題設為「成交股數」
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_data_v2 (
            日期 TEXT,
            成交股數 INTEGER,
            成交金額 TEXT,
            收盤價 TEXT,
            法人項目 TEXT,
            買賣超股數 REAL,
            PRIMARY KEY (日期, 法人項目)
        )
    ''')
    conn.commit()

    today = datetime.now()
    current_date = START_DATE_DT
    print(f"🚀 啟動更新 (目標: {START_DATE_DT.strftime('%Y-%m-%d')} 至今)")

    while current_date <= today:
        date_str = current_date.strftime("%Y%m%d")
        target_date = current_date.strftime("%Y-%m-%d")
        
        # 檢查是否已存在
        check_query = f"SELECT 1 FROM stock_data_v2 WHERE 日期 = '{target_date}' LIMIT 1"
        exists = pd.read_sql(check_query, conn)

        if exists.empty:
            # --- 修正後的 URL 拼接 (確保路徑完整) ---
            stock_url = f"https://twse.com.tw{date_str}&stockNo={STOCK_NO}"
            stock_data = safe_get_json(stock_url)
            
            if stock_data and stock_data.get("stat") == "OK":
                time.sleep(random.uniform(3, 6))
                inst_url = f"https://twse.com.tw{date_str}&selectType=ALLBUT0999"
                inst_data = safe_get_json(inst_url)
                
                if inst_data and inst_data.get("stat") == "OK":
                    # 解析個股基本資料
                    df_s = pd.DataFrame(stock_data["data"], columns=stock_data["fields"])
                    # 民國轉西元
                    df_s['日期'] = df_s['日期'].apply(lambda x: str(int(x.split('/')[0]) + 1911) + "-" + x.split('/')[1] + "-" + x.split('/')[2])
                    day_stock = df_s[df_s['日期'] == target_date]
                    
                    if not day_stock.empty:
                        # 擷取原始成交股數 (不除以 1000)
                        raw_vol = int(clean_val(day_stock['成交股數'].values[0]))
                        raw_amt = day_stock['成交金額'].values[0]
                        raw_price = day_stock['收盤價'].values[0]

                        # 解析法人買賣超資料
                        fields_i = inst_data["fields"]
                        data_i = inst_data["data"]
                        df_i = pd.DataFrame(data_i, columns=fields_i)

                        # 篩選台積電列
                        tsmc_row = df_i[df_i['證券代號'] == STOCK_NO]

                        if not tsmc_row.empty:
                            # 取得各法人數據
                            f_net = clean_val(tsmc_row["外陸資買賣超股數(不含外資自營商)"].values[0] if "外陸資買賣超股數(不含外資自營商)" in fields_i else tsmc_row["外陸資買賣超股數"].values[0])
                            it_net = clean_val(tsmc_row["投信買賣超股數"].values[0])
                            
                            # 自營商處理 (自行買賣 + 避險)
                            if "自營商買賣超股數(自行買賣)" in fields_i:
                                d_net = clean_val(tsmc_row["自營商買賣超股數(自行買賣)"].values[0]) + clean_val(tsmc_row["自營商買賣超股數(避險)"].values[0])
                            else:
                                d_net = clean_val(tsmc_row["自營商買賣超股數"].values[0])

                            res = [
                                {'日期': target_date, '成交股數': raw_vol, '成交金額': raw_amt, '收盤價': raw_price, '法人項目': '外資', '買賣超股數': f_net},
                                {'日期': target_date, '成交股數': raw_vol, '成交金額': raw_amt, '收盤價': raw_price, '法人項目': '投信', '買賣超股數': it_net},
                                {'日期': target_date, '成交股數': raw_vol, '成交金額': raw_amt, '收盤價': raw_price, '法人項目': '自營商', '買賣超股數': d_net}
                            ]
                            pd.DataFrame(res).to_sql('stock_data_v2', conn, if_exists='append', index=False)
                            print(f"✅ {target_date} 資料寫入成功")
                            time.sleep(random.uniform(4, 8))
        
        current_date += timedelta(days=1)

    # 匯出 CSV 並轉置表格
    raw_df = pd.read_sql("SELECT * FROM stock_data_v2", conn)
    if not raw_df.empty:
        pivot_df = raw_df.pivot_table(index=['日期', '成交股數', '成交金額', '收盤價'], columns='法人項目', values='買賣超股數').reset_index()
        pivot_df.columns.name = None
        pivot_df = pivot_df.sort_values('日期', ascending=False)
        pivot_df.to_csv(CSV_PATH, index=False, encoding='utf-8-sig')
        print(f"📊 CSV 檔案已產出：{CSV_PATH}")
    
    conn.close()

if __name__ == "__main__":
    update_database()

