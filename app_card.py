import streamlit as st
import yfinance as yf
import pandas as pd
import re
import altair as alt
import time
import requests
import os
import base64

# 嘗試載入富邦 SDK，若無安裝則標記為不可用
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

# 🛡️ 核心雙引擎擷取功能
@st.cache_data(ttl=60, show_spinner=False)
def fetch_stock_data(ticker):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    
    df = pd.DataFrame()
    data_source = "yahoo" # 預設資料來源為 Yahoo
    
    # 基礎引擎：Yahoo 歷史 K 線
    try:
        df = yf.Ticker(f"{ticker}.TW", session=session).history(period="2y", auto_adjust=False)
    except Exception:
        pass
        
    if df.empty:
        time.sleep(1)
        try:
            df = yf.Ticker(f"{ticker}.TWO", session=session).history(period="2y", auto_adjust=False)
        except Exception:
            pass

    if not df.empty:
        df = df.dropna(subset=['Close'])
        df['Volume'] = df['Volume'].fillna(0)
        
        # 🚀 渦輪引擎：富邦 API (憑證隱身術版本)
        if FUBON_AVAILABLE and "fubon" in st.secrets:
            try:
                sdk = FubonSDK()
                
                # 從保險箱讀取文字並還原成憑證檔案
                if "cert_base64" in st.secrets["fubon"]:
                    cert_data = base64.b64decode(st.secrets["fubon"]["cert_base64"])
                    cert_path = "temp_cert.p12" 
                    with open(cert_path, "wb") as f:
                        f.write(cert_data)
                        
                    # 登入與點火
                    sdk.login(st.secrets["fubon"]["id"], st.secrets["fubon"]["password"], cert_path, st.secrets["fubon"]["cert_password"])
                    sdk.init_realtime() 
                    
                    # 抓取即時報價並精準拆解
                    stock_info = sdk.marketdata.rest_client.stock.intraday.quote(symbol=ticker)
                    c_price = get_val(stock_info, 'closePrice')
                    h_price = get_val(stock_info, 'highPrice')
                    l_price = get_val(stock_info, 'lowPrice')
                    
                    total_obj = get_val(stock_info, 'total')
                    t_vol = get_val(total_obj, 'tradeVolume')
                    
                    if c_price is not None and t_vol is not None:
                        df.iloc[-1, df.columns.get_loc('Close')] = float(c_price)
                        df.iloc[-1, df.columns.get_loc('High')] = float(h_price)
                        df.iloc[-1, df.columns.get_loc('Low')] = float(l_price)
                        df.iloc[-1, df.columns.get_loc('Volume')] = float(t_vol) * 1000
                        data_source = "fubon" 
                        
                    # 刪除暫時憑證檔
                    if os.path.exists(cert_path):
                        os.remove(cert_path)
            except Exception:
                pass
                
        return df, data_source
    else:
        return None, None

# 📱 輸入區塊
ticker_input = st.text_input("🔍 請輸入台股代號 (例如: 2330, 0050, 00929)", "2330").strip()
submit_btn = st.button("產生圖卡 🚀", use_container_width=True, type="primary")

st.write("") 

if submit_btn or ticker_input:
    match = re.search(r'\d{4,5}', ticker_input)
    if not match:
        st.warning("⚠️ 請輸入正確的 4~5 碼台股代號！")
    else:
        t = match.group()
        with st.spinner(f"正在擷取 {t} 戰略數據..."):
            
            df, data_source = fetch_stock_data(t)
            
            if df is None:
                st.error("⚠️ 資料庫目前過於繁忙或限制了連線。請稍等 1~2 分鐘後，再重新整理網頁試試看！")
            elif df.empty:
                st.error(f"❌ 找不到代號 {t} 的資料，或該股票上市櫃時間不足 60 天。")
            else:
                if len(df) < 60:
                    st.warning(f"⚠️ 代號 {t} 的歷史資料不足 60 天，無法計算完整長天期均線。")
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
                    
                    ma3 = float(sma3_series.iloc[-1])
                    ma5 = float(sma5_series.iloc[-1])
                    ma10 = float(sma10_series.iloc[-1])
                    ma20 = float(sma20_series.iloc[-1])
                    ma60 = float(sma60_series.iloc[-1])

                    ma3_prev = float(sma3_series.iloc[-2])
                    ma5_prev = float(sma5_series.iloc[-2])
                    ma10_prev = float(sma10_series.iloc[-2])
                    ma20_prev = float(sma20_series.iloc[-2])
                    ma60_prev = float(sma60_series.iloc[-2])

                    v_ma5 = float(volume.rolling(5).mean().iloc[-1]) / 1000
                    turn_price_tomorrow = float(close.iloc[-5])
                    
                    b3 = ((curr_price - ma3) / ma3) * 100
                    b5 = ((curr_price - ma5) / ma5) * 100
                    b10 = ((curr_price - ma10) / ma10) * 100
                    b20 = ((curr_price - ma20) / ma20) * 100
                    b60 = ((curr_price - ma60) / ma60) * 100
                    
                    # --- 動態顯示資料來源警告 ---
                    if data_source == "yahoo":
                        st.warning("⚠️ **目前顯示為 Yahoo 基礎報價**：非即時連線，股價與實際盤中狀態可能會有時間落差。")
                    
                    # --- 圖卡視覺化呈現 ---
                    success_html = f"""
                    <div style="background-color: #d1e7dd; border: 1px solid #badbcc; border-radius: 8px; padding: 12px; text-align: center; margin-bottom: 16px;">
                        <div style="color: #0f5132; font-size: 18px; font-weight: bold;">【代號：{t}】</div>
                        <div style="color: #0f5132; font-size: 18px; font-weight: bold; margin-top: 4px;">最新戰略圖卡</div>
                        <div style="color: #0f5132; font-size: 12px; margin-top: 6px; font-weight: normal;">🔄 數據含 {last_date_str} 最新價，SMA動態滾動中</div>
                    </div>
                    """
                    st.markdown(success_html, unsafe_allow_html=True)
                    
                    st.markdown("##### 🎯 短線動能觀測")
                    c1, c2, c3 = st.columns(3)
                    
                    with c1:
                        st.metric("最新收盤價", f"${curr_price:.2f}", f"{price_change:+.2f} ({change_pct:+.2f}%)")
                        # 補回：高低均價小區塊
                        st.markdown(f"""
                        <div style="display: flex; justify-content: space-between; font-size: 11px; color: #6c757d; background-color: #f8f9fa; padding: 4px; border-radius: 4px; margin-top: -10px; border: 1px solid #e9ecef;">
                            <span>高 <span style="color:#333; font-weight:bold;">{high_price:.1f}</span></span>
                            <span>均 <span style="color:#333; font-weight:bold;">{avg_price:.1f}</span></span>
                            <span>低 <span style="color:#333; font-weight:bold;">{low_price:.1f}</span></span>
                        </div>
                        """, unsafe_allow_html=True)
                        
                    with c2:
                        st.metric("5日均量 (張)", f"{int(v_ma5):,} 張")
                        
                    with c3:
                        if ma5 > ma5_prev:
                            turn_status = "向上"
                            delta_color = "normal"
                            strategy_text = f"💡 **戰略解說**：5日線目前 **{turn_status}**。明天收盤價只要站穩 **${turn_price_tomorrow:.2f}**，5日線就能繼續**維持向上**；反之則會下彎。"
                        elif ma5 < ma5_prev:
                            turn_status = "下彎"
                            delta_color = "inverse"
                            strategy_text = f"💡 **戰略解說**：5日線目前處於 **{turn_status}** 修正。明天收盤價必須大於 **${turn_price_tomorrow:.2f}**，5日線才能**扭轉向上翻揚**；否則將持續弱勢。"
                        else:
                            turn_status = "持平"
                            delta_color = "off"
                            strategy_text = f"💡 **戰略解說**：5日線目前 **{turn_status}**。明天收盤價需大於 **${turn_price_tomorrow:.2f}**，5日線才會**向上翻揚**。"
                        
                        st.metric("明日5日扣抵價", f"${turn_price_tomorrow:.2f}", f"目前5均線 {turn_status}", delta_color=delta_color)

                    # 補回：戰略解說區塊
                    st.info(strategy_text)
                    
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
                    
                    color_scale = alt.Scale(
                        domain=line_order,
                        range=['red', 'blue', 'green', 'orange', 'lightblue'] 
                    )
                    
                    fixed_chart = alt.Chart(melted_df).mark_line().encode(
                        x=alt.X('日期:T', title=None, axis=alt.Axis(format='%m/%d', labelAngle=-45, grid=False)),
                        y=alt.Y('價位:Q', title=None, scale=alt.Scale(zero=False)),
                        color=alt.Color(
                            '線型:N', 
                            title=None, 
                            sort=line_order, 
                            scale=color_scale, 
                            legend=alt.Legend(
                                orient='bottom', 
                                columns=3, 
                                labelFontSize=12
                            )
                        )
                    ).properties(
                        height=280
                    )
                    
                    st.altair_chart(fixed_chart, use_container_width=True)
                    
                    st.write("---")
                    st.markdown("##### 🛡️ 中長期防守均線位階")
                    
                    def format_bias(b):
                        color = "#d9534f" if b >= 0 else "#5cb85c"
                        return f"<span style='color:{color}; font-size:11px;'>{b:+.1f}%</span>"

                    def get_trend_icon(curr_ma, prev_ma):
                        if curr_ma > prev_ma:
                            return "<span style='color:#d9534f; font-size: 13px; margin-left: 2px;'>↑</span>"
                        elif curr_ma < prev_ma:
                            return "<span style='color:#5cb85c; font-size: 13px; margin-left: 2px;'>↓</span>"
                        else:
                            return "<span style='color:gray; font-size: 13px; margin-left: 2px;'>-</span>"

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
                    
                    # 補回：最下方的中長線位階判定
                    trend_msg = "目前股價位階： "
                    if curr_price > ma60 and curr_price > ma20:
                        trend_msg += "🔥 **多頭排列** (站上月線與季線，趨勢偏多)"
                    elif curr_price < ma60 and curr_price < ma20:
                        trend_msg += "❄️ **空方修正** (跌破月線與季線，需等待築底)"
                    else:
                        trend_msg += "🌊 **震盪整理** (夾在月線與季線之間，方向待確認)"
                    
                    if len(close) >= 240:
                        ma240 = float(close.rolling(240).mean().iloc[-1])
                        if curr_price >= ma240:
                            trend_msg += f"<br>🛡️ **長線多方基準**：維持在 240SMA(年線 {ma240:.2f}) 之上，長線保護短線。"
                        else:
                            trend_msg += f"<br>⚠️ **長線空方基準**：目前低於 240SMA(年線 {ma240:.2f})，上方有長線蓋頭反壓。"
                    
                    st.markdown(trend_msg, unsafe_allow_html=True)
