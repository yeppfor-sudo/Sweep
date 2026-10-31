import os, ccxt, pandas as pd, requests, json, time, pytz
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
PKT = pytz.timezone('Asia/Karachi')
HIST_FILE = "alerts_history.json"
FRACTAL_LEN = 5  # smaller = earlier detection
COOLDOWN = 24
TOP_GAINERS = 30

BLOCK_ALL = {'BTC','ETH','SOL','BNB','TRX','XRP','ADA','DOGE','AVAX','DOT','LINK','LTC','BCH','XLM','ETC','HBAR','APT','NEAR','UNI','FIL','ARB','OP','ATOM','MATIC','POL','TON','SHIB','PEPE','CRO','LEO','OKB','BGB','SUI','LDO','RNDR','TAO','FET','WIF','ENA','JUP','SEI','TIA','ONDO','W','PYTH','STRK','JTO','ENS'}

def is_valid_crypto(sym):
    if not sym.endswith('USDT:USDT'): return False
    base=sym.split('/')[0].upper()
    if base in BLOCK_ALL: return False
    if len(base)<2 or len(base)>8: return False
    if any(c.isdigit() for c in base): return False
    if not base.isalpha(): return False
    return True

def send_msg(t):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":CHAT,"text":t,"parse_mode":"Markdown"}, timeout=20)
    except: pass
    print(t, flush=True)

def send_photo(p,c):
    try:
        with open(p,'rb') as f: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data={"chat_id":CHAT,"caption":c,"parse_mode":"Markdown"}, files={"photo":f}, timeout=30)
    except Exception as e: print(f"photo fail {e}", flush=True)

def load_hist():
    try: return json.load(open(HIST_FILE))
    except: return {}
def save_hist(d): json.dump(d, open(HIST_FILE,'w'))

def is_pivot_high(df,i,l): 
    if i<l or i>=len(df)-l: return False
    return df['h'].iloc[i]==df['h'].iloc[i-l:i+l+1].max()
def is_pivot_low(df,i,l):
    if i<l or i>=len(df)-l: return False
    return df['l'].iloc[i]==df['l'].iloc[i-l:i+l+1].min()

def detect_bearish_choch_early(df):
    """EARLY detection - alert as soon as CHoCH happens, not waiting for close"""
    if len(df)<80: return None
    upper=lower=None; direction=0; events=[]
    upB=lowB=False
    for i in range(FRACTAL_LEN,len(df)-1):
        if is_pivot_high(df,i,FRACTAL_LEN): upper=float(df['h'].iloc[i]); upB=False
        if is_pivot_low(df,i,FRACTAL_LEN): lower=float(df['l'].iloc[i]); lowB=False
        if upper is None or lower is None: continue
        c=float(df['c'].iloc[i]); pc=float(df['c'].iloc[i-1])
        if not lowB and c<lower and pc>=lower:
            lowB=True
            if direction==1:
                lb=float(df['l'].iloc[i])
                # This is the CHoCH point - at green circle
                events.append({'bar':i,'price':c,'upper':upper,'lower':lower,'rangeTop':upper,'rangeBottom':lb,'fib_top':upper-(upper-lb)*0.382,'fib_bot':upper-(upper-lb)*0.618,'eq':(upper+lb)/2})
            direction=-1
        if not upB and c>upper and pc<=upper: upB=True; direction=1
    if not events: return None
    # EARLY: if last CHoCH within last 5 bars (not just last bar) = alert at top
    if events[-1]['bar'] < len(df)-6: return None
    return events[-1]

def draw(df,sym,sig,exn,tf,gain):
    fig,ax=plt.subplots(figsize=(14,6),facecolor='black'); ax.set_facecolor('black')
    view=df.tail(80); live=float(view['c'].iloc[-1])
    for i,(_,r) in enumerate(view.iterrows()):
        col='#089981' if r['c']>=r['o'] else '#f23645'
        ax.plot([i,i],[r['l'],r['h']],color=col,lw=1); ax.plot([i,i],[r['o'],r['c']],color=col,lw=4)
    ax.axhline(sig['lower'],color='white',ls='--',lw=1.2,label=f"CHoCH BREAK {sig['lower']:.6f}")
    ax.axhspan(sig['fib_bot'],sig['fib_top'],color='#f23645',alpha=0.45,label="SHORT ZONE")
    ax.axhline(live,color='yellow',lw=1.2,label=f"LIVE {live:.6f}")
    ax.set_title(f"{sym} {exn} {tf} BEAR CHoCH EARLY | 24h +{gain:.1f}% | TOP GAINER",color='white',fontweight='bold')
    ax.legend(facecolor='black',labelcolor='white',fontsize=7); ax.grid(alpha=0.15); plt.tight_layout()
    p=f"chart_{sym.replace('/','').replace(':','')}_{tf}.png"; plt.savefig(p,dpi=150,facecolor='black'); plt.close(); return p,live

hist=load_hist()
now=datetime.now(PKT)
print("Starting EARLY TOP scan...", flush=True)

ex=ccxt.mexc({'enableRateLimit':True,'options':{'defaultType':'swap'}})
ex.load_markets()
tickers = ex.fetch_tickers()
print(f"Got {len(tickers)} tickers", flush=True)

gainers=[]
for sym,t in tickers.items():
    if not is_valid_crypto(sym): continue
    try:
        # Use LIVE 24h % - this is what you see in MEXC top gainers list
        ch = t.get('percentage')
        if ch is None: 
            ch = t.get('info',{}).get('riseFallRate')
            if ch: ch = float(ch)*100
        if ch is None or ch < 20: continue  # Only 20%+ LIVE gainers
        # Also check volume to avoid fake pumps
        vol_usd = t.get('quoteVolume',0) or t.get('baseVolume',0)*t.get('last',0)
        if vol_usd < 50000: continue
        gainers.append((sym,float(ch)))
    except: continue

gainers.sort(key=lambda x:x[1],reverse=True)
top=gainers[:TOP_GAINERS]
print(f"MEXC LIVE TOP {TOP_GAINERS} (>20%): {[(s.split('/')[0], f'{c:.1f}%') for s,c in top[:8]]}", flush=True)

found=0
for sym,gain in top:
    coin = sym.split('/')[0].upper()
    if coin in hist and time.time()-hist[coin] < COOLDOWN*3600:
        print(f"Skip {coin} - sent in 24h", flush=True)
        continue
    
    # CHECK 2 TIMEFRAMES FOR EARLY SIGNAL - 5m first (earliest), then 15m
    for tf in ['5m','15m']:
        try:
            ohlcv = ex.fetch_ohlcv(sym, tf, limit=300)
            df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            sig = detect_bearish_choch_early(df)
            if not sig:
                print(f"  No early CHoCH {coin} {tf}", flush=True)
                continue
            
            # FOUND at top - alert immediately
            chart,live = draw(df,sym,sig,'MEXC',tf,gain)
            cap = f"🔴 *BEAR CHoCH EARLY {tf} - TOP GAINER*\n\n*Pair:* `{sym}` | MEXC\n*24h LIVE:* `+{gain:.2f}%` - STILL TOP GAINER\n*CHoCH Break:* `{sig['lower']:.6f}`\n*Short Zone:* `{sig['fib_bot']:.6f}` - `{sig['fib_top']:.6f}`\n*SL:* `{sig['rangeTop']:.6f}`\n*Live:* `{live:.6f}`\n*Time:* {now.strftime('%H:%M PKT')}\n\n⚠️ *Alert at PEAK area, not after dump*"
            send_photo(chart,cap)
            hist[coin]=time.time()
            save_hist(hist)
            found+=1
            print(f"ALERT SENT {coin} at TOP +{gain:.1f}%", flush=True)
            break  # don't check other TF after found
        except Exception as e:
            print(f"  err {coin} {tf} {e}", flush=True)
            continue

print(f"Done. Found {found} early top CHoCH", flush=True)
