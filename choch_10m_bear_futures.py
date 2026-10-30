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
REQUIRE_BODY = True
COOLDOWN = 6
BLOCK = {'BTC','ETH','SOL','BNB','XRP','USDC','FDUSD','USDT','STOCK','ETF','GOLD','SILVER','OIL','USOIL','UKOIL','GAS','EUR','JPY'}
TOP_GAINERS_COUNT = 60

# FUTURES CONFIG
LEVERAGE = 5
RISK_PCT = 2.0  # 2% risk per trade
ACCOUNT_SIZE = 8.54  # your $8.54

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
    top=candidates[:TOP_GAINERS_COUNT]
    print(f"Top gainers: {[(s.split('/')[0], f'{c:.1f}%') for s,c,_ in top[:10]]}")
    return top

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
    for i in range(FRACTAL_LEN, len(df)-1):
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
            if marketDirection==1: # Bearish CHoCH
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

def draw_futures_chart(df, sym, tf, sig, futures_plan):
    fig, ax = plt.subplots(figsize=(14,7), facecolor='black')
    ax.set_facecolor('black')
    view=df.tail(80).copy()
    for i,(_,r) in enumerate(view.iterrows()):
        col='#089981' if r['c']>=r['o'] else '#f23645'
        ax.plot([i,i],[r['l'],r['h']],color=col,lw=1)
        ax.plot([i,i],[r['o'],r['c']],color=col,lw=4)
    # Levels
    ax.axhline(sig['upper'], color='white', ls=':', lw=1, label=f"Prev High {sig['upper']:.5f}")
    ax.axhline(sig['lower'], color='orange', ls='--', lw=1)
    ax.axhspan(sig['rangeBottom'], sig['rangeTop'], color='#f23645', alpha=0.12)
    ax.axhline(sig['eq'], color='gray', ls='--', lw=1, label=f"EQ {sig['eq']:.5f}")
    # Futures Zones
    ax.axhspan(futures_plan['entry_low'], futures_plan['entry_high'], color='#f23645', alpha=0.4, label=f"SHORT Entry {futures_plan['entry_low']:.5f}-{futures_plan['entry_high']:.5f}")
    ax.axhline(futures_plan['sl'], color='red', ls='-', lw=2, label=f"SL {futures_plan['sl']:.5f} ({futures_plan['sl_pct']:.2f}%)")
    ax.axhline(futures_plan['tp1'], color='#089981', ls='--', lw=1.5, label=f"TP1 1.55 {futures_plan['tp1']:.5f} (+{futures_plan['tp1_pct']:.1f}%)")
    ax.axhline(futures_plan['tp2'], color='#089981', ls='--', lw=1.5, label=f"TP2 2.68 {futures_plan['tp2']:.5f} (+{futures_plan['tp2_pct']:.1f}%)")
    ax.axhline(futures_plan['tp3'], color='gold', ls=':', lw=1, label=f"TP3 Runner {futures_plan['tp3']:.5f}")
    last_idx=len(view)-1
    ax.scatter(last_idx, sig['price'], color='white', s=130, zorder=5, edgecolors='red', linewidths=2)
    ax.text(last_idx, sig['price'], f" BEAR CHoCH SHORT", color='white', weight='bold', fontsize=11)
    ax.set_title(f"{sym} {tf} BEARISH FUTURES SHORT | {LEVERAGE}X Isolated | PKT {datetime.now(PKT).strftime('%H:%M:%S')}", color='white')
    ax.legend(facecolor='black', labelcolor='white', fontsize=7, loc='upper left')
    ax.grid(alpha=0.1)
    plt.tight_layout()
    path=f"chart_{sym.replace('/','').replace(':','')}_{tf}_fut.png"
    plt.savefig(path,dpi=150,facecolor='black')
    plt.close()
    return path

# MAIN
hist=load_hist()
top_data=get_48h_gainers()
if not top_data:
    send_msg("⚠️ No 48h gainers")
    exit()

found=0
now=datetime.now(PKT)

for sym, change48, vol in top_data:
    if sym in hist and time.time()-hist[sym] < COOLDOWN*3600: continue
    df=fetch_10m(sym)
    if df is None or len(df)<100: continue
    sig=detect_bearish_choch_only(df)
    if not sig: 
        time.sleep(0.2)
        continue
    
    # FUTURES PLAN CALCULATION
    entry_high = sig['fib_top']
    entry_low = sig['fib_bot']
    entry_mid = (entry_high + entry_low)/2
    sl = sig['rangeTop'] * 1.002  # 0.2% above high = SL
    rng = sig['rangeTop'] - sig['rangeBottom']
    tp1 = sig['rangeTop'] - rng*1.55
    tp2 = sig['rangeTop'] - rng*2.68
    tp3 = sig['rangeTop'] - rng*4.0
    
    # Risk calc
    sl_dist_pct = abs(sl - entry_mid)/entry_mid*100
    tp1_pct = abs(entry_mid - tp1)/entry_mid*100 * LEVERAGE
    tp2_pct = abs(entry_mid - tp2)/entry_mid*100 * LEVERAGE
    risk_usdt = ACCOUNT_SIZE * RISK_PCT/100
    qty_usdt = (risk_usdt / (sl_dist_pct/100))  # position size based on SL
    
    futures_plan = {
        'entry_high': entry_high,
        'entry_low': entry_low,
        'entry_mid': entry_mid,
        'sl': sl,
        'sl_pct': sl_dist_pct * LEVERAGE,
        'tp1': tp1,
        'tp1_pct': tp1_pct,
        'tp2': tp2,
        'tp2_pct': tp2_pct,
        'tp3': tp3,
        'qty_usdt': qty_usdt,
        'risk_usdt': risk_usdt,
    }
    
    chart=draw_futures_chart(df,sym,TIMEFRAME,sig,futures_plan)
    
    cap=f"""🔴 *BEAR CHoCH 10m FUTURES SHORT* 🔴

*Pair:* {sym} | *48h:* +{change48:.1f}% | Vol ${vol/1e6:.1f}M
*TF:* {TIMEFRAME} | *Price:* `{sig['price']:.6f}`

*📉 FUTURES PLAN (SHORT)*
*Entry Zone:* `{entry_low:.6f}` - `{entry_high:.6f}`
*Mid Entry:* `{entry_mid:.6f}`
*Leverage:* `{LEVERAGE}X Isolated`

*🛑 SL:* `{sl:.6f}` (`{sl_dist_pct:.2f}% | {sl_dist_pct*LEVERAGE:.1f}% with Lev`)
*Risk:* ${risk_usdt:.2f} ({RISK_PCT}% of ${ACCOUNT_SIZE})

*🎯 TPs:*
*TP1 1.55:* `{tp1:.6f}` | `+{tp1_pct:.1f}%` (50% close)
*TP2 2.68:* `{tp2:.6f}` | `+{tp2_pct:.1f}%` (30% close)
*TP3 Runner:* `{tp3:.6f}` (20% trailing)

*💰 Size:* ~${qty_usdt:.2f} USDT (for ${risk_usdt:.2f} risk)
*Actual Use:* ${qty_usdt/LEVERAGE:.2f} margin

*Time PKT:* {now.strftime('%Y-%m-%d %I:%M:%S %p')} Real-Time
*⚠️ 48h Top Gainer Reversal - Bearish CHoCH*
"""
    send_photo(chart,cap)
    hist[sym]=time.time()
    save_hist(hist)
    found+=1
    time.sleep(1)

if found==0:
    send_msg(f"*10m Bear CHoCH Futures* - No new SHORT setup in Top {TOP_GAINERS_COUNT} 48h gainers | PKT {now.strftime('%H:%M')}")
