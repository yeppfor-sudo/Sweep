import os, ccxt, pandas as pd, requests, json, time, pytz
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
PKT = pytz.timezone('Asia/Karachi')
HIST_FILE = "alerts_history.json"
FRACTAL_LEN = 7
REQUIRE_BODY = True
COOLDOWN = 1  # 1 hour cooldown for 15m TF

def send_msg(t):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id":CHAT,"text":t,"parse_mode":"Markdown"}, timeout=20)
        print(t)
    except Exception as e:
        print(f"Send error: {e}")

def send_photo(p,c):
    try:
        with open(p,'rb') as f:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                data={"chat_id":CHAT,"caption":c,"parse_mode":"Markdown"}, files={"photo":f}, timeout=30)
    except Exception as e:
        print(f"Photo error: {e}")

def load_hist():
    try:
        with open(HIST_FILE,'r') as f: return json.load(f)
    except: return {}

def save_hist(d):
    with open(HIST_FILE,'w') as f: json.dump(d,f)

exchange = ccxt.mexc({'enableRateLimit': True, 'options':{'defaultType':'swap'}})
exchange.load_markets()

def fetch_15m(sym):
    try:
        ohlcv = exchange.fetch_ohlcv(sym, '15m', limit=500)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        df['time'] = pd.to_datetime(df['t'], unit='ms', utc=True)
        return df
    except:
        return None

def is_pivot_high(df, idx, length):
    if idx < length or idx >= len(df)-length: return False
    window = df['h'].iloc[idx-length:idx+length+1]
    return df['h'].iloc[idx] == window.max()

def is_pivot_low(df, idx, length):
    if idx < length or idx >= len(df)-length: return False
    window = df['l'].iloc[idx-length:idx+length+1]
    return df['l'].iloc[idx] == window.min()

def detect_choch(df):
    if len(df) < 100: return None
    upperLevel = None
    lowerLevel = None
    upperBroken = False
    lowerBroken = False
    marketDirection = 0
    choch_events = []
    
    for i in range(FRACTAL_LEN, len(df)-1):
        if is_pivot_high(df, i, FRACTAL_LEN):
            upperLevel = float(df['h'].iloc[i])
            upperBroken = False
        if is_pivot_low(df, i, FRACTAL_LEN):
            lowerLevel = float(df['l'].iloc[i])
            lowerBroken = False
        
        if upperLevel is None or lowerLevel is None:
            continue
            
        close = float(df['c'].iloc[i])
        
        breakUp = False
        breakDown = False
        if not upperBroken and upperLevel:
            if close > upperLevel and float(df['c'].iloc[i-1]) <= upperLevel:
                breakUp = True
        if not lowerBroken and lowerLevel:
            if close < lowerLevel and float(df['c'].iloc[i-1]) >= lowerLevel:
                breakDown = True
        
        if breakUp:
            upperBroken = True
            if marketDirection == -1:
                choch_events.append({
                    'type': 'BULL_CHOCH',
                    'bar': i,
                    'price': close,
                    'upper': upperLevel,
                    'lower': lowerLevel,
                    'eq': (float(df['h'].iloc[i])+lowerLevel)/2,
                    'rangeTop': float(df['h'].iloc[i]),
                    'rangeBottom': lowerLevel,
                    'fib_top': lowerLevel + (float(df['h'].iloc[i])-lowerLevel)*0.618,
                    'fib_bot': lowerLevel + (float(df['h'].iloc[i])-lowerLevel)*0.382,
                })
            marketDirection = 1
            
        if breakDown:
            lowerBroken = True
            if marketDirection == 1:
                choch_events.append({
                    'type': 'BEAR_CHOCH',
                    'bar': i,
                    'price': close,
                    'upper': upperLevel,
                    'lower': lowerLevel,
                    'eq': (upperLevel+float(df['l'].iloc[i]))/2,
                    'rangeTop': upperLevel,
                    'rangeBottom': float(df['l'].iloc[i]),
                    'fib_top': upperLevel - (upperLevel-float(df['l'].iloc[i]))*0.382,
                    'fib_bot': upperLevel - (upperLevel-float(df['l'].iloc[i]))*0.618,
                })
            marketDirection = -1
    
    if not choch_events:
        return None
    last_event = choch_events[-1]
    # MUST BE PREVIOUS CLOSED CANDLE - bar = len(df)-2 (previous closed)
    # Current forming is len(df)-1, so previous closed is len(df)-2
    if last_event['bar'] != len(df)-2:
        return None
    return last_event

def draw_choch(df, sym, sig):
    fig, ax = plt.subplots(figsize=(13,6), facecolor='black')
    ax.set_facecolor('black')
    view = df.tail(70).copy()
    for i,(_,r) in enumerate(view.iterrows()):
        col='#089981' if r['c']>=r['o'] else '#f23645'
        ax.plot([i,i],[r['l'],r['h']],color=col,lw=1)
        ax.plot([i,i],[r['o'],r['c']],color=col,lw=4)
    if sig.get('upper'):
        ax.axhline(sig['upper'], color='gray', ls=':', lw=1)
    if sig.get('lower'):
        ax.axhline(sig['lower'], color='gray', ls=':', lw=1)
    if sig['type']=='BULL_CHOCH':
        ax.axhspan(sig['rangeBottom'], sig['rangeTop'], color='#089981', alpha=0.15)
        ax.axhspan(sig['fib_bot'], sig['fib_top'], color='#089981', alpha=0.35)
    else:
        ax.axhspan(sig['rangeBottom'], sig['rangeTop'], color='#f23645', alpha=0.15)
        ax.axhspan(sig['fib_bot'], sig['fib_top'], color='#f23645', alpha=0.35)
    ax.set_title(f"{sym} 15m {sig['type']} {sig['price']:.6f} PKT {datetime.now(PKT).strftime('%H:%M')}", color='white')
    ax.grid(alpha=0.1)
    plt.tight_layout()
    path=f"chart_{sym.replace('/','')}_15m.png"
    plt.savefig(path,dpi=150,facecolor='black')
    plt.close()
    return path

hist=load_hist()
syms=[s for s in exchange.markets if s.endswith('/USDT:USDT')]
try:
    tickers=exchange.fetch_tickers()
    syms=[s for s in syms if tickers.get(s,{}).get('quoteVolume',0)>300_000]
except: pass
syms=syms[:150]
found=0
now=datetime.now(PKT)

for sym in syms:
    if sym in hist and time.time()-hist[sym] < COOLDOWN*3600:
        continue
    df=fetch_15m(sym)
    if df is None or len(df)<100: continue
    sig=detect_choch(df)
    if not sig: continue
    
    chart=draw_choch(df,sym,sig)
    if 'BULL' in sig['type']:
        cap=f"🟢 *{sig['type']}*\n\n*Pair:* {sym}\n*TF:* 15m CLOSED\n*Price:* `{sig['price']:.6f}`\n*BLVL:* `{sig['upper']:.6f}`\n*Buy Zone:* `{sig['fib_bot']:.6f}` - `{sig['fib_top']:.6f}`\n*SL:* `{sig['rangeBottom']:.6f}`\n*Candle Close:* {now.strftime('%Y-%m-%d %I:%M %p')} PKT"
    else:
        cap=f"🔴 *{sig['type']}*\n\n*Pair:* {sym}\n*TF:* 15m CLOSED\n*Price:* `{sig['price']:.6f}`\n*BLVL:* `{sig['lower']:.6f}`\n*Sell Zone:* `{sig['fib_bot']:.6f}` - `{sig['fib_top']:.6f}`\n*SL:* `{sig['rangeTop']:.6f}`\n*Candle Close:* {now.strftime('%Y-%m-%d %I:%M %p')} PKT"
    
    send_photo(chart,cap)
    hist[sym]=time.time()
    save_hist(hist)
    found+=1
    time.sleep(1)

if found==0:
    print("No CHoCH on 15m closed candle")
