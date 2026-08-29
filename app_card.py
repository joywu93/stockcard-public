import streamlit as st
import yfinance as yf
import pandas as pd
import re
import altair as alt
import time
import requests
import os
import base64

# 嘗試載入富邦 SDK
try:
    from fubon_neo.sdk import FubonSDK
    FUBON_AVAILABLE = True
except ImportError:
    FUBON_AVAILABLE = False

# --- 網頁基礎設定 ---
st.set_page_config(page_title="📈 股市技術面短線圖卡", page_icon="💳", layout="centered")

# 📱 手機版視覺優化
st.markdown("<div style='text-align: center; font-size: 20px; font-weight: bold; margin-bottom: 2px; white-space: nowrap;'>💳 股市技術面短線圖卡</div>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: gray; font-size: 12px; margin-top: 4px;'>雙引擎架構：歷史均線 (Yahoo) ＋ 即時報價 (富邦)</p>", unsafe_allow_html=True)
st.write("---")

# 安全提取數值的 Helper 函式
def get_val(obj, key):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)

# 📖 建立自動字典：從政府公開資料抓取代號與名稱對照表
@st.cache_data(ttl=86400, show_spinner=False)
def get_stock_dict():
    name_to_code = {}
    code_to_name = {}
    try:
        twse = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=5).json()
        for item in twse:
            code = str(item.get('Code', '')).strip()
            name = str(item.get('Name', '')).strip()
            if code and name:
                name_to_code[name] = code
                code_to_name[code] = name
    except:
        pass
    try:
        tpex = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=5).json()
        for item in tpex:
            code = str(item.get('SecuritiesCompanyCode', '')).strip()
            name = str(item.get('CompanyName', '')).strip()
            if code and name:
                name_to_code[name] = code
                code_to_name[code] = name
    except:
        pass
    return name_to_code, code_to_name

# 🛡️ 核心雙引擎擷取功能 (含自動補幀 & 大盤+台積電雙引擎 & 指數支援)
@st.cache_data(ttl=60, show_spinner=False)
def fetch_stock_data(ticker):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    
    df = pd.DataFrame()
    data_source = "yahoo" 
    stock_name = ""
    index_data = {'TWSE': None, 'OTC': None, 'TSMC': None}
    
    # 判斷是否為指數通道
    is_index = ticker.startswith("^")
    
    # --- 1. 大盤指數與台積電 (Yahoo 備援引擎先打底) ---
    yahoo_twse_ref, yahoo_otc_ref, yahoo_tsmc_ref = None, None, None
    try:
        tw_df = yf.Ticker("^TWII", session=session).history(period="5d")
        if len(tw_df) >= 2:
            c, ref = tw_df['Close'].iloc[-1], tw_df['Close'].iloc[-2]
            yahoo_twse_ref = ref
            index_data['TWSE'] = {'price': c, 'change': c - ref, 'pct': (c - ref)/ref * 100}
            
        otc_df = yf.Ticker("^TWOII", session=session).history(period="5d")
        if len(otc_df) >= 2:
            c, ref = otc_df['Close'].iloc[-1], otc_df['Close'].iloc[-2]
            yahoo_otc_ref = ref
            index_data['OTC'] = {'price': c, 'change': c - ref, 'pct': (c - ref)/ref * 100}
            
        tsmc_df = yf.Ticker("2330.TW", session=session).history(period="5d")
        if len(tsmc_df) >= 2:
            c, ref = tsmc_df['Close'].iloc[-1], tsmc_df['Close'].iloc[-2]
            yahoo_tsmc_ref = ref
            index_data['TSMC'] = {'price': c, 'change': c - ref, 'pct': (c - ref)/ref * 100}
    except:
        pass

    # --- 2. 主角歷史資料 (Yahoo) ---
    if is_index:
        yahoo_sym = ticker
        fubon_sym = "TWSE.FS" if ticker == "^TWII" else "OTC.TW"
        try:
            df = yf.Ticker(yahoo_sym, session=session).history(period="2y", auto_adjust=False)
        except: pass
    else:
        fubon_sym = ticker
        try:
            df = yf.Ticker(f"{ticker}.TW", session=session).history(period="2y", auto_adjust=False)
        except: pass
        if df.empty:
            time.sleep(1)
            try:
                df = yf.Ticker(f"{ticker}.TWO", session=session).history(period="2y", auto_adjust=False)
            except: pass

    if not df.empty:
        df = df.dropna(subset=['Close'])
        df['Volume'] = df['Volume'].fillna(0)
        
        # --- 3. 🚀 渦輪引擎：富邦 API ---
        if FUBON_AVAILABLE and "fubon" in st.secrets:
            try:
                sdk = FubonSDK()
                if "cert_base64" in st.secrets["fubon"]:
                    cert_data = base64.b64decode(st.secrets["fubon"]["cert_base64"])
                    cert_path = "temp_cert.p12" 
                    with open(cert_path, "wb") as f:
                        f.write(cert_data)
                        
                    sdk.login(st.secrets["fubon"]["id"], st.secrets["fubon"]["password"], cert_path, st.secrets["fubon"]["cert_password"])
                    sdk.init_realtime() 
                    
                    # 抓取上方小字的大盤與台積電即時報價
                    try:
                        twse_info = sdk.marketdata.rest_client.stock.intraday.quote(symbol="TWSE.FS")
                        if twse_info:
                            c = float(get_val(twse_info, 'closePrice'))
                            ref = yahoo_twse_ref if yahoo_twse_ref else float(get_val(twse_info, 'previousClose') or get_val(twse_info, 'referencePrice') or c)
                            index_data['TWSE'] = {'price': c, 'change': c - ref, 'pct': ((c - ref)/ref * 100) if ref else 0}
                            
                        otc_info = sdk.marketdata.rest_client.stock.intraday.quote(symbol="OTC.TW")
                        if otc_info:
                            c = float(get_val(otc_info, 'closePrice'))
                            ref = yahoo_otc_ref if yahoo_otc_ref else float(get_val(otc_info, 'previousClose') or get_val(otc_info, 'referencePrice') or c)
                            index_data['OTC'] = {'price': c, 'change': c - ref, 'pct': ((c - ref)/ref * 100) if ref else 0}
                            
                        tsmc_info = sdk.marketdata.rest_client.stock.intraday.quote(symbol="2330")
                        if tsmc_info:
                            c = float(get_val(tsmc_info, 'closePrice'))
                            ref = yahoo_tsmc_ref if yahoo_tsmc_ref else float(get_val(tsmc_info, 'previousClose') or get_val(tsmc_info, 'referencePrice') or c)
                            index_data['TSMC'] = {'price': c, 'change': c - ref, 'pct': ((c - ref)/ref * 100) if ref else 0}
                    except:
                        pass
                    
                    # 抓取目前輸入的主角 (個股或大盤) 即時報價
                    stock_info = sdk.marketdata.rest_client.stock.intraday.quote(symbol=fubon_sym)
                    
                    c_price = get_val(stock_info, 'closePrice')
                    h_price = get_val(stock_info, 'highPrice')
                    l_price = get_val(stock_info, 'lowPrice')
                    o_price = get_val(stock_info, 'openPrice')
                    f_name = get_val(stock_info, 'name')
                    if f_name:
                        stock_name = f_name
                        
                    total_obj = get_val(stock_info, 'total')
                    t_vol = get_val(total_obj, 'tradeVolume')
                    f_date = get_val(stock_info, 'date')
                    
                    if c_price is not None and t_vol is not None:
                        if not o_price: o_price = c_price
                            
                        # 自動補幀
                        last_yahoo_date = df.index[-1].strftime("%Y-%m-%d")
                        if f_date and str(f_date) > last_yahoo_date:
                            new_idx = pd.to_datetime(f_date)
                            if df.index.tz is not None:
                                new_idx = new_idx.tz_localize(df.index.tz)
                            
                            df.loc[new_idx] = df.iloc[-1].copy()
                            df.loc[new_idx, 'Open'] = float(o_price)
                            df.loc[new_idx, 'High'] = float(h_price)
                            df.loc[new_idx, 'Low'] = float(l_price)
                            df.loc[new_idx, 'Close'] = float(c_price)
                            df.loc[new_idx, 'Volume'] = float(t_vol) * 1000
                        else:
                            df.iloc[-1, df.columns.get_loc('Close')] = float(c_price)
                            df.iloc[-1, df.columns.get_loc('High')] = float(h_price)
                            df.iloc[-1, df.columns.get_loc('Low')] = float(l_price)
                            df.iloc[-1, df.columns.get_loc('Volume')] = float(t_vol) * 1000
                            
                        data_source = "fubon" 
                        
                    if os.path.exists(cert_path):
                        os.remove(cert_path)
            except:
                pass
                
        return df, data_source, stock_name, index_data
    else:
        return None, None, "", index_data

# 📱 輸入區塊
ticker_input = st.text_input("🔍 請輸入代號或名稱 (例如: 2330, TSE, 大盤, OTC)", "2330").strip()
submit_btn = st.button("產生圖卡 🚀", use_container_width=True, type="primary")

st.write("") 

if submit_btn or ticker_input:
    name_to_code, code_to_name = get_stock_dict()
    
    index_map = {
        "大盤": "^TWII", "加權": "^TWII", "加權指數": "^TWII", "TSE": "^TWII", "TWII": "^TWII",
        "櫃買": "^TWOII", "櫃買指數": "^TWOII", "OTC": "^TWOII", "TWO": "^TWOII"
    }
    
    user_input_upper = ticker_input.upper()
    if user_input_upper in index_map:
        target_code = index_map[user_input_upper]
    elif re.match(r'^\d{4,5}$', ticker_input):
        target_code = ticker_input
    else:
        target_code = name_to_code.get(ticker_input)

    if not target_code:
        st.error(f"❌ 找不到「{ticker_input}」的代號，請確認名稱是否正確。")
    else:
        t = target_code
        with st.spinner(f"正在擷取戰略數據..."):
            
            df, data_source, stock_name, index_data = fetch_stock_data(t)
            
            # 設定顯示名稱與代號
            if t == "^TWII":
                stock_name = "加權指數"
                t_display = "TSE"
            elif t == "^TWOII":
                stock_name = "櫃買指數"
                t_display = "OTC"
            else:
                t_display = t
                if not stock_name:
                    stock_name = code_to_name.get(t, "")
            
            if df is None:
                st.error("⚠️ 資料庫目前過於繁忙或限制了連線。請稍等後再試！")
            elif df.empty or len(df) < 60:
                st.error(f"❌ 找不到資料或上市櫃時間不足 60 天。")
            else:
                # --- 核心數據計算 ---
                close = df['Close']
                volume = df['Volume']
                
                last_date_str = df.index[-1].strftime("%Y-%m-%d")
                curr_price = float(close.iloc[-1])
                prev_price = float(close.iloc[-2])
                price_change = curr_price - prev_price
                change_pct = (price_change / prev_price) * 100
                
                high_price = float(df['High'].iloc[-1])
                low_price = float(df['Low'].iloc[-1])
                avg_price = (curr_price + high_price + low_price) / 3
                
                sma3_series = close.rolling(3).mean()
                sma5_series = close.rolling(5).mean()
                sma10_series = close.rolling(10).mean()
                sma20_series = close.rolling(20).mean()
                sma60_series = close.rolling(60).mean()
                
                ma3, ma5, ma10, ma20, ma60 = [float(s.iloc[-1]) for s in (sma3_series, sma5_series, sma10_series, sma20_series, sma60_series)]
                ma3_prev, ma5_prev, ma10_prev, ma20_prev, ma60_prev = [float(s.iloc[-2]) for s in (sma3_series, sma5_series, sma10_series, sma20_series, sma60_series)]

                v_ma5 = float(volume.rolling(5).mean().iloc[-1]) / 1000
                
                # --- 💡 新增：未來三日扣抵價 ---
                turn_price_tomorrow = float(close.iloc[-5])
                turn_price_after_1 = float(close.iloc[-4]) # 後日
                turn_price_after_2 = float(close.iloc[-3]) # 大後日
                
                b3, b5, b10, b20, b60 = [((curr_price - m) / m) * 100 for m in (ma3, ma5, ma10, ma20, ma60)]
                
                # --- 📊 5日 KD 計算 ---
                low_min = df['Low'].rolling(window=5).min()
                high_max = df['High'].rolling(window=5).max()
                rsv = (df['Close'] - low_min) / (high_max - low_min) * 100
                
                rsv_list = rsv.fillna(50).tolist()
                k_list, d_list = [50.0] * len(df), [50.0] * len(df)
                
                for i in range(1, len(df)):
                    k_list[i] = (2/3) * k_list[i-1] + (1/3) * rsv_list[i]
                    d_list[i] = (2/3) * d_list[i-1] + (1/3) * k_list[i]
                    
                k_val, d_val = k_list[-1], d_list[-1]
                prev_k_val, prev_d_val = k_list[-2], d_list[-2] 
                
                # --- 動態顯示資料來源警告 ---
                if data_source == "yahoo":
                    st.warning("⚠️ **目前顯示為 Yahoo 基礎報價**：非即時連線，可能有時間落差。")
                
                # --- 圖卡視覺化呈現 ---
                display_title = f"【代號：{t_display} {stock_name}】" if stock_name else f"【代號：{t_display}】"
                st.markdown(f"""
                <div style="background-color: #d1e7dd; border: 1px solid #badbcc; border-radius: 8px; padding: 12px; text-align: center; margin-bottom: 16px;">
                    <div style="color: #0f5132; font-size: 18px; font-weight: bold;">{display_title}</div>
                    <div style="color: #0f5132; font-size: 18px; font-weight: bold; margin-top: 4px;">最新戰略圖卡</div>
                    <div style="color: #0f5132; font-size: 12px; margin-top: 6px; font-weight: normal;">🔄 數據含 {last_date_str} 最新價，SMA動態滾動中</div>
                </div>
                """, unsafe_allow_html=True)
                
                # --- 📈 大盤與台積電即時指數動態呈現 ---
                idx_html = ""
                if index_data['TWSE']:
                    p = index_data['TWSE']
                    color = "#d9534f" if p['change'] >= 0 else "#5cb85c"
                    icon = "↑" if p['change'] >= 0 else "↓"
                    idx_html += f"<span style='white-space: nowrap;'>加權 <span style='color:{color}; font-weight:bold;'>{p['price']:,.2f} ({icon}{abs(p['change']):.2f} / {p['pct']:+.2f}%)</span></span>"
                    
                if index_data['TSMC']:
                    p = index_data['TSMC']
                    color = "#d9534f" if p['change'] >= 0 else "#5cb85c"
                    icon = "↑" if p['change'] >= 0 else "↓"
                    idx_html += f"<span style='margin-left: 8px; white-space: nowrap;'>台積電 <span style='color:{color}; font-weight:bold;'>{p['price']:,.0f} ({icon}{abs(p['change']):.0f} / {p['pct']:+.2f}%)</span></span>"

                if index_data['OTC']:
                    p = index_data['OTC']
                    color = "#d9534f" if p['change'] >= 0 else "#5cb85c"
                    icon = "↑" if p['change'] >= 0 else "↓"
                    idx_html += f"<span style='margin-left: 8px; white-space: nowrap;'>櫃買 <span style='color:{color}; font-weight:bold;'>{p['price']:,.2f} ({icon}{abs(p['change']):.2f} / {p['pct']:+.2f}%)</span></span>"

                st.markdown(f"""
                <style>
                .market-header-container {{
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-end;
                    margin-bottom: 10px;
                    border-bottom: 1px solid #e9ecef;
                    padding-bottom: 8px;
                }}
                .market-header-title {{
                    font-size: 1.25rem; 
                    font-weight: 600;
                    white-space: nowrap;
                }}
                .market-header-indices {{
                    font-size: 0.82rem; 
                    color: #6c757d; 
                    text-align: right;
                }}
                @media (max-width: 650px) {{
                    .market-header-container {{
                        flex-direction: column;
                        align-items: flex-start;
                        gap: 6px;
                    }}
                    .market-header-indices {{
                        text-align: left;
                    }}
                }}
                </style>
                <div class="market-header-container">
                    <div class="market-header-title">🎯 短線動能觀測</div>
                    <div class="market-header-indices">{idx_html}</div>
                </div>
                """, unsafe_allow_html=True)
                
                c1, c2, c3, c4 = st.columns([1.5, 1, 1, 1])
                
                with c1:
                    c1_html = f"""
                    <div style="padding-top: 0.2rem; padding-bottom: 0.5rem;">
                        <div style="font-size: 13px; color: var(--text-color); opacity: 0.7; margin-bottom: 4px;">最新價 / 即時量</div>
                        <div style="font-size: 1.8rem; font-weight: 700; color: var(--text-color); margin-bottom: 2px;">
                            ${curr_price:.2f} <span style="font-size: 1.1rem; opacity: 0.7; font-weight: 400;">/ {int(volume.iloc[-1] / 1000):,}</span>
                        </div>
                        <div style="font-size: 14px; color: {'#d9534f' if price_change >=0 else '#5cb85c'};">
                            {'↑' if price_change >=0 else '↓'} {abs(price_change):.2f} ({change_pct:+.2f}%)
                        </div>
                    </div>
                    """
                    st.markdown(c1_html, unsafe_allow_html=True)
                    
                    st.markdown(f"""
                    <div style="display: flex; justify-content: space-between; font-size: 11px; color: #6c757d; background-color: #f8f9fa; padding: 4px; border-radius: 4px; margin-top: 2px; border: 1px solid #e9ecef;">
                        <span>高 <span style="color:#333; font-weight:bold;">{high_price:.1f}</span></span>
                        <span>均 <span style="color:#333; font-weight:bold;">{avg_price:.1f}</span></span>
                        <span>低 <span style="color:#333; font-weight:bold;">{low_price:.1f}</span></span>
                    </div>
                    """, unsafe_allow_html=True)
                    
                with c2:
                    c2_html = f"""
                    <div style="padding-top: 0.2rem; padding-bottom: 0.5rem;">
                        <div style="font-size: 13px; color: var(--text-color); opacity: 0.7; margin-bottom: 4px;">5日均量</div>
                        <div style="font-size: 1.8rem; font-weight: 700; color: var(--text-color); margin-bottom: 2px;">
                            {int(v_ma5):,}
                        </div>
                        <div style="font-size: 14px; opacity: 0;">-</div> 
                    </div>
                    """
                    st.markdown(c2_html, unsafe_allow_html=True)
                    
                with c3:
                    if ma5 > ma5_prev:
                        turn_status, turn_color, turn_icon = "向上", "#d9534f", "↑"
                        strategy_text = f"💡 **均線戰略**：5日線目前 **向上**。明天只要站穩 **${turn_price_tomorrow:.2f}**，就能繼續維持強勢。"
                    elif ma5 < ma5_prev:
                        turn_status, turn_color, turn_icon = "下彎", "#5cb85c", "↓"
                        strategy_text = f"💡 **均線戰略**：5日線目前 **下彎**。明天必須大於 **${turn_price_tomorrow:.2f}**，才能扭轉向上翻揚。"
                    else:
                        turn_status, turn_color, turn_icon = "持平", "gray", "-"
                        strategy_text = f"💡 **均線戰略**：5日線目前 **持平**。明天需大於 **${turn_price_tomorrow:.2f}**，才會向上翻揚。"
                    
                    # 💡 修正：加入未來兩天扣抵，保持精緻排版
                    c3_html = f"""
                    <div style="padding-top: 0.2rem; padding-bottom: 0.5rem;">
                        <div style="font-size: 13px; color: var(--text-color); opacity: 0.7; margin-bottom: 4px;">明日5日扣抵</div>
                        <div style="font-size: 1.8rem; font-weight: 700; color: var(--text-color); margin-bottom: 2px;">
                            ${turn_price_tomorrow:.2f}
                        </div>
                        <div style="font-size: 14px; color: {turn_color};">
                            {turn_icon} 5均線 {turn_status}
                            <div style="font-size: 12px; color: #6c757d; margin-top: 3px;">(5SMA {ma5:.2f} / 10SMA {ma10:.2f})</div>
                            <div style="font-size: 12px; color: #0288d1; margin-top: 3px; font-weight: bold;">
                                ⏭️ 後日 {turn_price_after_1:.2f} / 大後 {turn_price_after_2:.2f}
                            </div>
                        </div>
                    </div>
                    """
                    st.markdown(c3_html, unsafe_allow_html=True)

                with c4:
                    if k_val >= 80:
                        kd_status, kd_desc = "🔥 高檔超買", f"K值來到 {k_val:.1f}，短線有過熱跡象，需留意獲利了結賣壓。"
                    elif k_val <= 20:
                        kd_status, kd_desc = "❄️ 低檔超賣", f"K值來到 {k_val:.1f}，短線跌幅已深，隨時可能醞釀技術性反彈。"
                    elif k_val > d_val:
                        kd_status, kd_desc = "📈 短線偏多", "K值大於D值 (黃金交叉)，動能偏向多方，適合順勢操作。"
                    else:
                        kd_status, kd_desc = "📉 短線偏弱", "K值小於D值 (死亡交叉)，動能偏向空方，需提高風險意識。"
                    
                    k_icon = "↑" if k_val >= prev_k_val else "↓"
                    k_color = "#d9534f" if k_val >= prev_k_val else "#5cb85c"
                    d_icon = "↑" if d_val >= prev_d_val else "↓"
                    d_color = "#d9534f" if d_val >= prev_d_val else "#5cb85c"
                    kd_status_color = "#d9534f" if k_val >= d_val else "#5cb85c"
                    
                    c4_html = f"""
                    <div style="padding-top: 0.2rem; padding-bottom: 0.5rem;">
                        <div style="font-size: 13px; color: var(--text-color); opacity: 0.7; margin-bottom: 4px;">5日 K/D 值</div>
                        <div style="font-size: 1.8rem; font-weight: 700; color: var(--text-color); margin-bottom: 2px;">
                            {k_val:.1f} <span style="font-size: 1.1rem; color: {k_color}; font-weight: 700;">{k_icon}</span>
                            <span style="font-size: 1.1rem; opacity: 0.7; font-weight: 400;">/ {d_val:.1f} <span style="color: {d_color}; font-weight: 700;">{d_icon}</span></span>
                        </div>
                        <div style="font-size: 14px; color: {kd_status_color};">
                            {kd_status}
                        </div>
                    </div>
                    """
                    st.markdown(c4_html, unsafe_allow_html=True)

                st.info(strategy_text)
                st.info(f"💡 **KD 戰略**：{kd_status}。{kd_desc}")
                
                # 💡 若是看大盤與櫃買，自動在下方補充說明單位
                if t in ["^TWII", "^TWOII"]:
                    st.info("💡 **量能說明**：上方顯示之數據為「一般股票」之成交數量（單位：千張）。")
                
                st.write("---")
                st.markdown("##### 📈 近三個月均線糾結與走勢")
                
                chart_df = pd.DataFrame({
                    '收盤價': close,
                    '5SMA': sma5_series,
                    '10SMA': sma10_series,
                    '20SMA': sma20_series,
                    '60SMA': sma60_series
                }).tail(60).reset_index()
                
                chart_df.rename(columns={chart_df.columns[0]: '日期'}, inplace=True)
                melted_df = chart_df.melt(id_vars=['日期'], var_name='線型', value_name='價位')
                
                line_order = ['收盤價', '5SMA', '10SMA', '20SMA', '60SMA']
                color_scale = alt.Scale(domain=line_order, range=['red', 'blue', 'green', 'orange', 'lightblue'])
                
                fixed_chart = alt.Chart(melted_df).mark_line().encode(
                    x=alt.X('日期:T', title=None, axis=alt.Axis(format='%m/%d', labelAngle=-45, grid=False)),
                    y=alt.Y('價位:Q', title=None, scale=alt.Scale(zero=False)),
                    color=alt.Color('線型:N', title=None, sort=line_order, scale=color_scale, legend=alt.Legend(orient='bottom', columns=3, labelFontSize=12))
                ).properties(height=280)
                
                st.altair_chart(fixed_chart, use_container_width=True)
                
                st.write("---")
                st.markdown("##### 🛡️ 中長期防守均線位階")
                
                def format_bias(b):
                    color = "#d9534f" if b >= 0 else "#5cb85c"
                    return f"<span style='color:{color}; font-size:11px;'>{b:+.1f}%</span>"

                def get_trend_icon(curr_ma, prev_ma):
                    if curr_ma > prev_ma: return "<span style='color:#d9534f; font-size: 13px; margin-left: 2px;'>↑</span>"
                    elif curr_ma < prev_ma: return "<span style='color:#5cb85c; font-size: 13px; margin-left: 2px;'>↓</span>"
                    else: return "<span style='color:gray; font-size: 13px; margin-left: 2px;'>-</span>"

                ma_html = f"""
                <div style="display: flex; justify-content: space-between; align-items: center; background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 8px 1px; text-align: center;">
                    <div style="flex: 1; border-right: 1px solid #dee2e6; padding: 0 1px;">
                        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">3SMA</div>
                        <div style="font-size: 13px; font-weight: bold; margin: 2px 0;">${ma3:.2f}{get_trend_icon(ma3, ma3_prev)}</div>
                        <div>{format_bias(b3)}</div>
                    </div>
                    <div style="flex: 1; border-right: 1px solid #dee2e6; padding: 0 1px;">
                        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">5SMA</div>
                        <div style="font-size: 13px; font-weight: bold; margin: 2px 0;">${ma5:.2f}{get_trend_icon(ma5, ma5_prev)}</div>
                        <div>{format_bias(b5)}</div>
                    </div>
                    <div style="flex: 1; border-right: 1px solid #dee2e6; padding: 0 1px;">
                        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">10SMA</div>
                        <div style="font-size: 13px; font-weight: bold; margin: 2px 0;">${ma10:.2f}{get_trend_icon(ma10, ma10_prev)}</div>
                        <div>{format_bias(b10)}</div>
                    </div>
                    <div style="flex: 1; border-right: 1px solid #dee2e6; padding: 0 1px;">
                        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">20SMA</div>
                        <div style="font-size: 13px; font-weight: bold; margin: 2px 0;">${ma20:.2f}{get_trend_icon(ma20, ma20_prev)}</div>
                        <div>{format_bias(b20)}</div>
                    </div>
                    <div style="flex: 1; padding: 0 1px;">
                        <div style="font-size: 11px; color: #6c757d; font-weight: bold;">60SMA</div>
                        <div style="font-size: 13px; font-weight: bold; margin: 2px 0;">${ma60:.2f}{get_trend_icon(ma60, ma60_prev)}</div>
                        <div>{format_bias(b60)}</div>
                    </div>
                </div>
                """
                st.markdown(ma_html, unsafe_allow_html=True)
                
                st.write("")
                trend_msg = "目前位階： "
                if curr_price > ma60 and curr_price > ma20: trend_msg += "🔥 **多頭排列** (站上月線與季線，趨勢偏多)"
                elif curr_price < ma60 and curr_price < ma20: trend_msg += "❄️ **空方修正** (跌破月線與季線，需等待築底)"
                else: trend_msg += "🌊 **震盪整理** (夾在月線與季線之間，方向待確認)"
                
                if len(close) >= 240:
                    ma240 = float(close.rolling(240).mean().iloc[-1])
                    if curr_price >= ma240: trend_msg += f"<br>🛡️ **長線多方基準**：維持在 240SMA(年線 {ma240:.2f}) 之上，長線保護短線。"
                    else: trend_msg += f"<br>⚠️ **長線空方基準**：目前低於 240SMA(年線 {ma240:.2f})，上方有長線蓋頭反壓。"
                
                st.markdown(trend_msg, unsafe_allow_html=True)

# --- 以上為原有的圖卡程式碼 ---
                
                st.write("---")
                
                # ==========================================
                # 🚀 新增：呼叫前日轉折名單區塊
                # ==========================================
                st.markdown("### 📡 戰情雷達：盤後主力動能名單")
                
                # 請將下方的網址替換成您 Google Sheet 發佈為 CSV 的連結
                GOOGLE_SHEET_CSV_URL = "請填入您的_Google_Sheet_CSV_連結"
                
                if st.button("🚀 呼叫前日轉折名單", use_container_width=True):
                    with st.spinner("正在讀取雲端名單..."):
                        try:
                            # 如果您還沒填入真實網址，這裡先做個防呆提示
                            if GOOGLE_SHEET_CSV_URL == "請填入您的_Google_Sheet_CSV_連結":
                                st.warning("⚠️ 請先在程式碼中填入您的 Google Sheet CSV 連結喔！")
                                # 以下為預覽用的假資料，等您填入真實網址後可刪除這段假資料
                                mock_data = pd.DataFrame({
                                    "代號": ["3526", "3147"],
                                    "名稱": ["凡甲", "大綜"],
                                    "收盤價": [286.0, 220.0],
                                    "5SMA乖離率": ["1.2%", "0.8%"],
                                    "量能放大倍數": ["1.5倍", "1.4倍"]
                                })
                                st.dataframe(mock_data, use_container_width=True, hide_index=True)
                            else:
                                # 瞬間讀取 Google Sheet CSV 
                                sheet_df = pd.read_csv(GOOGLE_SHEET_CSV_URL)
                                
                                # 顯示資料表
                                st.success("✅ 讀取成功！以下為符合【均線糾結 < 4%】且【量大於 5日均量 1.3 倍】之標的：")
                                st.dataframe(sheet_df, use_container_width=True, hide_index=True)
                                
                        except Exception as e:
                            st.error(f"❌ 讀取失敗，請確認 Google Sheet 連結是否正確或已公開發佈。錯誤訊息：{e}")
