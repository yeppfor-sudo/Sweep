import os, ccxt, pandas as pd, requests, json, time, pytz
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
PKT = pytz.timezone('Asia/Karachi')
HIST_FILE = "alerts_history_bear10m_fut.json"
TIMEFRAME = '10m'
FRACTAL_LEN = 5
COOLDOWN = 6
BLOCK = {'BTC','ETH','SOL','BNB','XRP','USDC','FDUSD','USDT','STOCK','ETF','GOLD','SILVER','OIL','USOIL','UKOIL','GAS','EUR','JPY'}
TOP_GAINERS_COUNT = 60
LEVERAGE = 5
RISK_PCT = 2.0
ACCOUNT_SIZE = 8.54

def send_msg(t):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":CHAT,"text":t,"parse_mode":"Markdown"}, timeout=20)
    except: print(t)
def send_photo(p,c):
    try:
        with open(p,'rb') as f:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data={"chat_id":CHAT,"caption":c,"parse_mode":"Markdown"}, files={"photo":f}, timeout=30)
    except Exception as e: print(f"photo fail {e}")
def load_hist():
    try:
        with open(HIST_FILE,'r') as f: return json.load(f)
    except: return {}
def save_hist(d):
    with open(HIST_FILE,'w') as f: json.dump(d,f)

exchange = ccxt.mexc({'enableRateLimit': True, 'options':{'defaultType':'swap'}})
exchange.load_markets()

def get_48h_gainers():
    print("Scanning 48h top gainers...")
    tickers = exchange.fetch_tickers()
    candidates=[]
    for sym,t in tickers.items():
        if not sym.endswith('USDT:USDT'): continue
        coin=sym.split('/')[0]
        if coin in BLOCK: continue
        if any(x in sym for x in ['ETF','STOCK','GOLD','SILVER','OIL']): continue
        try:
            ohlcv=exchange.fetch_ohlcv(sym,'1d',limit=3)
            if len(ohlcv)<3: continue
            change=(ohlcv[-1][4]-ohlcv[-3][4])/ohlcv[-3][4]*100
            vol=t.get('quoteVolume',0) or 0
            if vol<500_000: continue
            if change>2:
                candidates.append((sym,change,vol))
        except: continue
        time.sleep(0.05)
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[:TOP_GAINERS_COUNT]

def fetch_10m(sym):
    try:
        ohlcv=exchange.fetch_ohlcv(sym,'1m',limit=800)
        df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        df['time']=pd.to_datetime(df['t'], unit='ms', utc=True)
        df.set_index('time', inplace=True)
        df=df.resample('10min').agg({'o':'first','h':'max','l':'min','c':'last','v':'sum'}).dropna().reset_index()
        return df
    except: return None

def is_pivot_high(df, idx, length):
    if idx < length or idx >= len(df)-length: return False
    return df['h'].iloc[idx] == df['h'].iloc[idx-length:idx+length+1].max()
def is_pivot_low(df, idx, length):
    if idx < length or idx >= len(df)-length: return False
    return df['l'].iloc[idx] == df['l'].iloc[idx-length:idx+length+1].min()

def detect_bearish_choch_only(df):
    if len(df)<100: return None
    upperLevel=lowerLevel=None
    upperBroken=lowerBroken=False
    marketDirection=0
    events=[]
    for i in range(FRACTAL_LEN, len(df)-1):  # FIXED BRACKET
        if is_pivot_high(df,i,FRACTAL_LEN):
            upperLevel=float(df['h'].iloc[i]); upperBroken=False
        if is_pivot_low(df,i,FRACTAL_LEN):
            lowerLevel=float(df['l'].iloc[i]); lowerBroken=False
        if upperLevel is None or lowerLevel is None: continue
        close=float(df['c'].iloc[i]); prev_close=float(df['c'].iloc[i-1])
        breakUp=False; breakDown=False
        if not upperBroken and close>upperLevel and prev_close<=upperLevel:
            breakUp=True
        if not lowerBroken and close<lowerLevel and prev_close>=lowerLevel:
            breakDown=True
        if breakUp:
            upperBroken=True; marketDirection=1
        if breakDown:
            lowerBroken=True
            if marketDirection==1:
                rng=upperLevel-float(df['l'].iloc[i])
                events.append({
                    'type':'BEAR_CHOCH',
                    'bar':i,
                    'price':close,
                    'upper':upperLevel,
                    'lower':lowerLevel,
                    'rangeTop':upperLevel,
                    'rangeBottom':float(df['l'].iloc[i]),
                    'eq':(upperLevel+float(df['l'].iloc[i]))/2,
                    'fib_top':upperLevel-rng*0.382,
                    'fib_bot':upperLevel-rng*0.618,
                })
            marketDirection=-1
    if not events: return None
    last=events[-1]
    if last['bar']<len(df)-4: return None
    return last

def draw_futures_chart(df, sym, tf, sig, fp):
    fig, ax = plt.subplots(figsize=(14,7), facecolor='black')
    ax.set_facecolor('black')
    view=df.tail(80).copy()
    for i,(_,r) in enumerate(view.iterrows()):
        col='#089981' if r['c']>=r['o'] else '#f23645'
        ax.plot([i,i],[r['l'],r['h']],color=col,lw=1)
        ax.plot([i,i],[r['o'],r['c']],color=col,lw=4)
    ax.axhline(sig['upper'], color='white', ls=':', lw=1, label=f"Prev High {sig['upper']:.5f}")
    ax.axhspan(sig['rangeBottom'], sig['rangeTop'], color='#f23645', alpha=0.12)
    ax.axhline(sig['eq'], color='gray', ls='--', lw=1)
    ax.axhspan(fp['entry_low'], fp['entry_high'], color='#f23645', alpha=0.4, label=f"SHORT {fp['entry_low']:.5f}-{fp['entry_high']:.5f}")
    ax.axhline(fp['sl'], color='red', ls='-', lw=2, label=f"SL {fp['sl']:.5f}")
    ax.axhline(fp['tp1'], color='#089981', ls='--', label=f"TP1 {fp['tp1']:.5f}")
    ax.axhline(fp['tp2'], color='#089981', ls='--', label=f"TP2 {fp['tp2']:.5f}")
    last_idx=len(view)-1
    ax.scatter(last_idx, sig['price'], color='white', s=130, zorder=5, edgecolors='red', linewidths=2)
    ax.set_title(f"{sym} {tf} BEARISH SHORT | {LEVERAGE}X | PKT {datetime.now(PKT).strftime('%H:%M:%S')}", color='white')
    ax.legend(facecolor='black', labelcolor='white', fontsize=7, loc='upper left')
    ax.grid(alpha=0.1)
    plt.tight_layout()
    path=f"chart_{sym.replace('/','').replace(':','')}_{tf}_fut.png"
    plt.savefig(path,dpi=150,facecolor='black')
    plt.close()
    return path

hist=load_hist()
top_data=get_48h_gainers()
if not top_data:
    send_msg("⚠️ No 48h gainers"); exit()
found=0
now=datetime.now(PKT)
for sym, change48, vol in top_data:
    if sym in hist and time.time()-hist[sym] < COOLDOWN*3600: continue
    df=fetch_10m(sym)
    if df is None or len(df)<100: continue
    sig=detect_bearish_choch_only(df)
    if not sig: 
        time.sleep(0.2); continue
    entry_high=sig['fib_top']; entry_low=sig['fib_bot']; entry_mid=(entry_high+entry_low)/2
    sl=sig['rangeTop']*1.002; rng=sig['rangeTop']-sig['rangeBottom']
    tp1=sig['rangeTop']-rng*1.55; tp2=sig['rangeTop']-rng*2.68; tp3=sig['rangeTop']-rng*4.0
    sl_dist_pct=abs(sl-entry_mid)/entry_mid*100
    tp1_pct=abs(entry_mid-tp1)/entry_mid*100*LEVERAGE
    tp2_pct=abs(entry_mid-tp2)/entry_mid*100*LEVERAGE
    risk_usdt=ACCOUNT_SIZE*RISK_PCT/100; qty_usdt=(risk_usdt/(sl_dist_pct/100))
    fp={'entry_high':entry_high,'entry_low':entry_low,'entry_mid':entry_mid,'sl':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3}
    chart=draw_futures_chart(df,sym,TIMEFRAME,sig,fp)
    cap=f"🔴 *BEAR CHoCH 10m SHORT* 🔴\n\n*Pair:* {sym} | *48h:* +{change48:.1f}%\n*Entry:* `{entry_low:.6f}` - `{entry_high:.6f}`\n*SL:* `{sl:.6f}`\n*TP1:* `{tp1:.6f}` +{tp1_pct:.1f}%\n*TP2:* `{tp2:.6f}` +{tp2_pct:.1f}%\n*Time:* {now.strftime('%H:%M:%S')} PKT"
    send_photo(chart,cap)
    hist[sym]=time.time(); save_hist(hist); found+=1; time.sleep(1)
if found==0:
    send_msg(f"*10m Bear CHoCH* - No new SHORT in Top {TOP_GAINERS_COUNT} 48h gainers | PKT {now.strftime('%H:%M')}")
