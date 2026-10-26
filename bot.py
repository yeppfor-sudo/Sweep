import os, ccxt, pandas as pd, requests, json, time, pytz
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
PKT = pytz.timezone('Asia/Karachi')
HIST_FILE = "alerts_history.json"
TIMEFRAMES = ['2h','4h','6h','8h','12h','1d','3d','5d','7d','30d']
PIVOT_LEN = 5
COOLDOWN = 24

def send_msg(t):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id":CHAT,"text":t,"parse_mode":"Markdown"}, timeout=20)
def send_photo(p,c):
    with open(p,'rb') as f:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            data={"chat_id":CHAT,"caption":c,"parse_mode":"Markdown"}, files={"photo":f}, timeout=30)
def load_hist():
    try:
        with open(HIST_FILE,'r') as f: return json.load(f)
    except: return {}
def save_hist(d):
    with open(HIST_FILE,'w') as f: json.dump(d,f)

exchange = ccxt.mexc({'enableRateLimit': True, 'options':{'defaultType':'swap'}})
exchange.load_markets()

def fetch_tf(sym, tf):
    try:
        if tf in ['2h','4h','6h','8h','12h']:
            h=int(tf.replace('h',''))
            ohlcv=exchange.fetch_ohlcv(sym,'1h',limit=500)
            df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            df['time']=pd.to_datetime(df['t'], unit='ms', utc=True)
            df.set_index('time', inplace=True)
            df=df.resample(f'{h}h').agg({'o':'first','h':'max','l':'min','c':'last','v':'sum'}).dropna().reset_index()
            return df
        elif tf=='1d':
            ohlcv=exchange.fetch_ohlcv(sym,'1d',limit=300)
            df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            df['time']=pd.to_datetime(df['t'], unit='ms', utc=True)
            return df
        else:
            rule={'3d':'3D','5d':'5D','7d':'7D','30d':'30D'}[tf]
            need=900 if tf=='30d' else 500
            ohlcv=exchange.fetch_ohlcv(sym,'1d',limit=need)
            df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            df['time']=pd.to_datetime(df['t'], unit='ms', utc=True)
            df.set_index('time', inplace=True)
            df=df.resample(rule).agg({'o':'first','h':'max','l':'min','c':'last','v':'sum'}).dropna().reset_index()
            return df
    except: return None

def get_last_pivots(df, pivot_len=5):
    last_high = None
    last_high_idx = None
    last_low = None
    last_low_idx = None
    # Scan for pivots excluding last pivot_len bars (need confirmation)
    for i in range(len(df)-pivot_len-1, pivot_len-1, -1):
        # High pivot
        window_h = df['h'].iloc[i-pivot_len:i+pivot_len+1]
        if df['h'].iloc[i] == window_h.max():
            if last_high is None:
                last_high = float(df['h'].iloc[i])
                last_high_idx = i
        # Low pivot
        window_l = df['l'].iloc[i-pivot_len:i+pivot_len+1]
        if df['l'].iloc[i] == window_l.min():
            if last_low is None:
                last_low = float(df['l'].iloc[i])
                last_low_idx = i
        if last_high is not None and last_low is not None:
            break
    return last_high, last_high_idx, last_low, last_low_idx

def check_sweep(df):
    if len(df) < 30: return None
    last_high, high_idx, last_low, low_idx = get_last_pivots(df, PIVOT_LEN)
    if last_high is None and last_low is None: return None
    
    last = df.iloc[-1] # confirmed closed candle
    
    bull_sweep = False
    bear_sweep = False
    
    # Bull Sweep: Sweep below swing low, then close back above it
    if last_low is not None:
        if last['l'] < last_low and last['c'] > last_low:
            bull_sweep = True
    
    # Bear Sweep: Sweep above swing high, then close back below it
    if last_high is not None:
        if last['h'] > last_high and last['c'] < last_high:
            bear_sweep = True
    
    if not bull_sweep and not bear_sweep: return None
    
    return {
        'bull': bull_sweep,
        'bear': bear_sweep,
        'last_high': last_high,
        'last_low': last_low,
        'high_idx': high_idx,
        'low_idx': low_idx,
        'price': float(last['c']),
        'high': float(last['h']),
        'low': float(last['l']),
    }

def draw_chart(df, sym, tf, sig):
    fig, ax = plt.subplots(figsize=(12,6), facecolor='black')
    ax.set_facecolor('black')
    view = df.tail(60).copy()
    x = range(len(view))
    # Candles
    for i,(_,r) in enumerate(view.iterrows()):
        col='#00ff88' if r['c']>=r['o'] else '#ff4444'
        ax.plot([i,i],[r['l'],r['h']],color=col,lw=1)
        ax.plot([i,i],[r['o'],r['c']],color=col,lw=4)
    # Liquidity levels - dashed lines like Pine
    if sig['last_high'] is not None:
        # Find where in view
        ax.axhline(sig['last_high'], color='red', ls='--', lw=1.2, label=f"LIQ High {sig['last_high']:.5f}")
    if sig['last_low'] is not None:
        ax.axhline(sig['last_low'], color='lime', ls='--', lw=1.2, label=f"LIQ Low {sig['last_low']:.5f}")
    
    # Mark sweep candle
    last_idx = len(view)-1
    if sig['bull']:
        ax.scatter(last_idx, view.iloc[-1]['l'], color='lime', s=200, marker='^', zorder=5)
        ax.text(last_idx, view.iloc[-1]['l']*0.995, " BULL SWEEP", color='lime', weight='bold')
    if sig['bear']:
        ax.scatter(last_idx, view.iloc[-1]['h'], color='red', s=200, marker='v', zorder=5)
        ax.text(last_idx, view.iloc[-1]['h']*1.005, " BEAR SWEEP", color='red', weight='bold')
    
    title_type = "BULL SWEEP" if sig['bull'] else "BEAR SWEEP"
    ax.set_title(f"{sym} {tf} | {title_type} | Close {sig['price']:.5f} | PKT {datetime.now(PKT).strftime('%Y-%m-%d %H:%M')}", color='white')
    ax.legend(facecolor='black', labelcolor='white')
    ax.grid(alpha=0.15)
    plt.tight_layout()
    path = f"chart_{sym.replace('/','')}_{tf}.png"
    plt.savefig(path, dpi=150, facecolor='black')
    plt.close()
    return path

hist = load_hist()
syms = [s for s in exchange.markets if s.endswith('/USDT:USDT')]
try:
    tickers = exchange.fetch_tickers()
    syms = [s for s in syms if tickers.get(s,{}).get('quoteVolume',0) > 300_000]
except: pass
syms = syms[:150]
found = 0
now = datetime.now(PKT)

for sym in syms:
    if sym in hist and time.time()-hist[sym] < COOLDOWN*3600:
        continue
    for tf in TIMEFRAMES:
        df = fetch_tf(sym, tf)
        if df is None or len(df)<30: continue
        sig = check_sweep(df)
        if not sig: continue
        
        chart = draw_chart(df, sym, tf, sig)
        if sig['bull']:
            caption = f"🟢 *BULLISH LIQUIDITY SWEEP*\n\n*Pair:* {sym}\n*TF:* {tf} Closed\n*Sweep Low:* `{sig['last_low']:.6f}`\n*Trigger:* Low `{sig['low']:.6f}` < Liquidity then Close `{sig['price']:.6f}` > Liquidity\n*Signal:* BULL SWEEP - Liquidity Grab + Reclaim\n*Time PKT:* {now.strftime('%I:%M %p')}"
        else:
            caption = f"🔴 *BEARISH LIQUIDITY SWEEP*\n\n*Pair:* {sym}\n*TF:* {tf} Closed\n*Sweep High:* `{sig['last_high']:.6f}`\n*Trigger:* High `{sig['high']:.6f}` > Liquidity then Close `{sig['price']:.6f}` < Liquidity\n*Signal:* BEAR SWEEP - Liquidity Grab + Rejection\n*Time PKT:* {now.strftime('%I:%M %p')}"
        
        send_photo(chart, caption)
        hist[sym] = time.time()
        save_hist(hist)
        found+=1
        time.sleep(1)
        break # once per pair

if found==0:
    send_msg("*please patience* No Liquidity Sweep - Scan done")
