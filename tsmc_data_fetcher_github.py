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
            if response.status_code == 200 and "application/json" in response.headers.get("Content-Type", ""):
                return response.json()
            else:
                print(f"⚠️ 警告：證交所回應異常 (Status: {response.status_code})。休息中...")
                time.sleep(300)
        except Exception as e:
            print(f"⚠️ 網路異常: {e}")
            time.sleep(10)
    return None

def update_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # 確保標題為「成交股數」
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
    print(f"🚀 GitHub Actions 啟動 (目標日期範圍: {START_DATE_DT.strftime('%Y-%m-%d')} 至今)")

    while current_date <= today:
        date_str = current_date.strftime("%Y%m%d")
        target_date = current_date.strftime("%Y-%m-%d")
        
        check_query = f"SELECT 1 FROM stock_data_v2 WHERE 日期 = '{target_date}' LIMIT 1"
        exists = pd.read_sql(check_query, conn)

        if exists.empty:
            # --- 修正後的 URL 拼接 ---
            stock_url = f"https://twse.com.tw{date_str}&stockNo={STOCK_NO}"
            stock_data = safe_get_json(stock_url)
            
            if stock_data and stock_data.get("stat") == "OK":
                time.sleep(random.uniform(3, 6))
                inst_url = f"https://twse.com.tw{date_str}&selectType=ALLBUT0999"
                inst_data = safe_get_json(inst_url)
                
                if inst_data and inst_data.get("stat") == "OK":
                    fields_i = inst_data["fields"]
                    data_i = inst_data["data"]
                    df_i = pd.DataFrame(data_i, columns=fields_i)

                    # 找到正確的法人買賣欄位索引
                    def find_idx(name):
                        for i, f in enumerate(fields_i):
                            if name in f: return i
                        return None

                    idx_no = find_idx("證券代號")
                    idx_foreign = find_idx("外陸資買賣超股數")
                    idx_trust = find_idx("投信買賣超股數")
                    idx_dealer_self = find_idx("自營商買賣超股數(自行買賣)")
                    idx_dealer_hedge = find_idx("自營商買賣超股數(避險)")
                    idx_dealer_total = find_idx("自營商買賣超股數")

                    tsmc_row = df_i[df_i.iloc[:, idx_no] == STOCK_NO] if idx_no is not None else pd.DataFrame()

                    if not tsmc_row.empty:
                        df_s = pd.DataFrame(stock_data["data"], columns=stock_data["fields"])
                        # 轉換民國日期為西元日期
                        df_s['日期'] = df_s['日期'].apply(lambda x: str(int(x.split('/')[0]) + 1911) + "-" + x.split('/')[1] + "-" + x.split('/')[2])
                        day_stock = df_s[df_s['日期'] == target_date]
                        
                        if not day_stock.empty:
                            day_stock_copy = day_stock.copy()
                            # 保留原始成交股數 (不除以 1000)
                            stock_volume = int(str(day_stock_copy['成交股數'].values[0]).replace(',', ''))

                            def clean_val(val):
                                v = str(val).replace(',', '').strip()
                                return float(v) if v not in ['', '--'] else 0.0

                            # 自營商合併計算
                            if idx_dealer_self is not None and idx_dealer_hedge is not None:
                                d_net = clean_val(tsmc_row.iloc[0, idx_dealer_self]) + clean_val(tsmc_row.iloc[0, idx_dealer_hedge])
                            else:
                                d_net = clean_val(tsmc_row.iloc[0, idx_dealer_total])

                            res = [
                                {'日期': target_date, '成交股數': stock_volume, '成交金額': day_stock_copy['成交金額'].values[0], '收盤價': day_stock_copy['收盤價'].values[0], '法人項目': '外資', '買賣超股數': clean_val(tsmc_row.iloc[0, idx_foreign])},
                                {'日期': target_date, '成交股數': stock_volume, '成交金額': day_stock_copy['成交金額'].values[0], '收盤價': day_stock_copy['收盤價'].values[0], '法人項目': '投信', '買賣超股數': clean_val(tsmc_row.iloc[0, idx_trust])},
                                {'日期': target_date, '成交股數': stock_volume, '成交金額': day_stock_copy['成交金額'].values[0], '收盤價': day_stock_copy['收盤價'].values[0], '法人項目': '自營商', '買賣超股數': d_net}
                            ]
                            pd.DataFrame(res).to_sql('stock_data_v2', conn, if_exists='append', index=False)
                            print(f"✅ {target_date} 資料更新成功")
                            time.sleep(random.uniform(4, 7))
        
        current_date += timedelta(days=1)

    # 匯出資料並轉置
    raw_df = pd.read_sql("SELECT * FROM stock_data_v2", conn)
    if not raw_df.empty:
        pivot_df = raw_df.pivot_table(index=['日期', '成交股數', '成交金額', '收盤價'], columns='法人項目', values='買賣超股數').reset_index()
        pivot_df.columns.name = None
        pivot_df = pivot_df.sort_values('日期', ascending=False)
        pivot_df.to_csv(CSV_PATH, index=False, encoding='utf-8-sig')
        print(f"📊 CSV 檔案已產出: {CSV_PATH} (標題已設為成交股數)")
    
    conn.close()

if __name__ == "__main__":
    update_database()
