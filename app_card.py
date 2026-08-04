import streamlit as st
import yfinance as yf
import pandas as pd
import re
import altair as alt
import time
import requests
import os
import base64  # 👈 新增這行：負責解碼憑證

# 嘗試載入富邦 SDK
try:
    from fubon_neo.sdk import FubonSDK
    FUBON_AVAILABLE = True
except ImportError:
    FUBON_AVAILABLE = False

# --- 網頁基礎設定 ---
st.set_page_config(page_title="📈 股市技術面短線圖卡", page_icon="💳", layout="centered")
st.markdown("<div style='text-align: center; font-size: 20px; font-weight: bold; margin-bottom: 2px; white-space: nowrap;'>💳 股市技術面短線圖卡</div>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: gray; font-size: 12px; margin-top: 4px;'>雙引擎架構：歷史均線 (Yahoo) ＋ 即時報價 (富邦)</p>", unsafe_allow_html=True)
st.write("---")

def get_val(obj, key):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)

@st.cache_data(ttl=60, show_spinner=False)
def fetch_stock_data(ticker):
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    df = pd.DataFrame()
    data_source = "yahoo"
    
    # 基礎引擎：Yahoo
    try:
        df = yf.Ticker(f"{ticker}.TW", session=session).history(period="2y", auto_adjust=False)
    except Exception:
        pass
    if df.empty:
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
                
                # 👈 隱身術核心：從保險箱讀取文字，瞬間還原成憑證檔案
                if "cert_base64" in st.secrets["fubon"]:
                    cert_data = base64.b64decode(st.secrets["fubon"]["cert_base64"])
                    cert_path = "temp_cert.p12" # 產生暫時的憑證檔
                    with open(cert_path, "wb") as f:
                        f.write(cert_data)
                        
                    # 使用暫時憑證登入並點火
                    sdk.login(st.secrets["fubon"]["id"], st.secrets["fubon"]["password"], cert_path, st.secrets["fubon"]["cert_password"])
                    sdk.init_realtime()
                    
                    # 抓取報價並拆解
                    stock_info = sdk.marketdata.rest_client.stock.intraday.quote(symbol=ticker)
                    c_price = get_val(stock_info, 'closePrice')
                    h_price = get_val(stock_info, 'highPrice')
                    l_price = get_val(stock_info, 'lowPrice')
                    t_vol = get_val(get_val(stock_info, 'total'), 'tradeVolume')
                    
                    if c_price is not None and t_vol is not None:
                        df.iloc[-1, df.columns.get_loc('Close')] = float(c_price)
                        df.iloc[-1, df.columns.get_loc('High')] = float(h_price)
                        df.iloc[-1, df.columns.get_loc('Low')] = float(l_price)
                        df.iloc[-1, df.columns.get_loc('Volume')] = float(t_vol) * 1000
                        data_source = "fubon"
                        
                    # 用完即丟：刪除暫時的憑證檔案，確保雲端不殘留
                    if os.path.exists(cert_path):
                        os.remove(cert_path)
                        
            except Exception:
                pass
                
        return df, data_source
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
            
            if df is None or df.empty:
                st.error("⚠️ 找不到資料，或上市時間不足。")
            elif len(df) < 60:
                st.warning("⚠️ 歷史資料不足 60 天。")
            else:
                close, volume = df['Close'], df['Volume']
                last_date_str = df.index[-1].strftime("%Y-%m-%d")
                
                curr_price, prev_price = float(close.iloc[-1]), float(close.iloc[-2])
                price_change = curr_price - prev_price
                change_pct = (price_change / prev_price) * 100
                avg_price = (curr_price + float(df['High'].iloc[-1]) + float(df['Low'].iloc[-1])) / 3
                
                ma3, ma5, ma10, ma20, ma60 = [float(close.rolling(i).mean().iloc[-1]) for i in (3, 5, 10, 20, 60)]
                ma5_prev = float(close.rolling(5).mean().iloc[-2])
                
                v_ma5 = float(volume.rolling(5).mean().iloc[-1]) / 1000
                turn_price_tomorrow = float(close.iloc[-5])
                
                b3, b5, b10, b20, b60 = [((curr_price - m) / m) * 100 for m in (ma3, ma5, ma10, ma20, ma60)]
                
                if data_source == "yahoo":
                    st.warning("⚠️ **目前顯示為 Yahoo 基礎報價**：非即時連線，可能有時間落差。")
                
                st.markdown(f"""
                <div style="background-color: #d1e7dd; border: 1px solid #badbcc; border-radius: 8px; padding: 12px; text-align: center; margin-bottom: 16px;">
                    <div style="color: #0f5132; font-size: 18px; font-weight: bold;">【代號：{t}】</div>
                    <div style="color: #0f5132; font-size: 18px; font-weight: bold; margin-top: 4px;">最新戰略圖卡</div>
                    <div style="color: #0f5132; font-size: 12px; margin-top: 6px;">🔄 數據含 {last_date_str} 最新價，SMA動態滾動中</div>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("##### 🎯 短線動能觀測")
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("最新收盤價", f"${curr_price:.2f}", f"{price_change:+.2f} ({change_pct:+.2f}%)")
                with c2:
                    st.metric("5日均量 (張)", f"{int(v_ma5):,} 張")
                with c3:
                    turn_status = "向上" if ma5 > ma5_prev else "下彎" if ma5 < ma5_prev else "持平"
                    st.metric("明日5日扣抵價", f"${turn_price_tomorrow:.2f}", f"5均線 {turn_status}", delta_color="normal" if turn_status=="向上" else "inverse" if turn_status=="下彎" else "off")

                st.write("---")
                st.markdown("##### 📈 近三個月均線糾結與走勢")
                
                chart_df = pd.DataFrame({'收盤價': close, '5SMA': close.rolling(5).mean(), '10SMA': close.rolling(10).mean(), '20SMA': close.rolling(20).mean(), '60SMA': close.rolling(60).mean()}).tail(60).reset_index()
                chart_df.rename(columns={chart_df.columns[0]: '日期'}, inplace=True)
                melted_df = chart_df.melt(id_vars=['日期'], var_name='線型', value_name='價位')
                
                fixed_chart = alt.Chart(melted_df).mark_line().encode(
                    x=alt.X('日期:T', title=None, axis=alt.Axis(format='%m/%d', labelAngle=-45, grid=False)),
                    y=alt.Y('價位:Q', title=None, scale=alt.Scale(zero=False)),
                    color=alt.Color('線型:N', title=None, scale=alt.Scale(domain=['收盤價', '5SMA', '10SMA', '20SMA', '60SMA'], range=['red', 'blue', 'green', 'orange', 'lightblue']), legend=alt.Legend(orient='bottom', columns=3))
                ).properties(height=280)
                st.altair_chart(fixed_chart, use_container_width=True)
                
                st.write("---")
                st.markdown("##### 🛡️ 中長期防守均線位階")
                
                def fmt_b(b): return f"<span style='color:{'#d9534f' if b>=0 else '#5cb85c'}; font-size:11px;'>{b:+.1f}%</span>"
                def fmt_m(m): return f"${m:.2f}"
                
                st.markdown(f"""
                <div style="display: flex; justify-content: space-between; text-align: center; background-color: #f8f9fa; padding: 8px; border-radius: 8px; border: 1px solid #e9ecef;">
                    <div style="flex: 1;"><b>3SMA</b><br>{fmt_m(ma3)}<br>{fmt_b(b3)}</div>
                    <div style="flex: 1;"><b>5SMA</b><br>{fmt_m(ma5)}<br>{fmt_b(b5)}</div>
                    <div style="flex: 1;"><b>10SMA</b><br>{fmt_m(ma10)}<br>{fmt_b(b10)}</div>
                    <div style="flex: 1;"><b>20SMA</b><br>{fmt_m(ma20)}<br>{fmt_b(b20)}</div>
                    <div style="flex: 1;"><b>60SMA</b><br>{fmt_m(ma60)}<br>{fmt_b(b60)}</div>
                </div>
                """, unsafe_allow_html=True)
