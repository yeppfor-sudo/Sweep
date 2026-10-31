import os, ccxt, pandas as pd, requests, json, time, pytz
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
PKT = pytz.timezone('Asia/Karachi')
HIST_FILE = "alerts_history.json"
FRACTAL_LEN = 5
COOLDOWN = 24  # BLOCK SPAM 24h
TOP_GAINERS = 30
TIMEFRAMES = ['5m','10m','15m']

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
                events.append({'bar':i,'price':c,'upper':upper,'lower':lower,'rangeTop':upper,'rangeBottom':lb,'fib_top':upper-(upper-lb)*0.382,'fib_bot':upper-(upper-lb)*0.618,'eq':(upper+lb)/2})
            direction=-1
        if not upB and c>upper and pc<=upper: upB=True; direction=1
    if not events: return None
    if events[-1]['bar'] < len(df)-6: return None
    return events[-1]

def draw(df,sym,sig,exn,tf,gain48):
    fig,ax=plt.subplots(figsize=(14,6),facecolor='black'); ax.set_facecolor('black')
    view=df.tail(80); live=float(view['c'].iloc[-1])
    for i,(_,r) in enumerate(view.iterrows()):
        col='#089981' if r['c']>=r['o'] else '#f23645'
        ax.plot([i,i],[r['l'],r['h']],color=col,lw=1); ax.plot([i,i],[r['o'],r['c']],color=col,lw=4)
    ax.axhline(sig['lower'],color='white',ls='--',lw=1.2,label=f"BREAK {sig['lower']:.6f}")
    ax.axhspan(sig['fib_bot'],sig['fib_top'],color='#f23645',alpha=0.45,label="SELL ZONE")
    ax.axhline(live,color='yellow',lw=1.2,label=f"LIVE {live:.6f}")
    ax.set_title(f"{sym} {exn} {tf} EARLY CHoCH | LIVE 48h +{gain48:.1f}% | 24h block",color='white',fontweight='bold')
    ax.legend(facecolor='black',labelcolor='white',fontsize=7); ax.grid(alpha=0.15); plt.tight_layout()
    p=f"chart_{sym.replace('/','').replace(':','')}_{tf}.png"; plt.savefig(p,dpi=150,facecolor='black'); plt.close(); return p,live

hist=load_hist()
now=datetime.now(PKT)
print(f"Scan Started LAST 48h LIVE >15% | Block 24h | {now.strftime('%H:%M PKT')}", flush=True)

ex=ccxt.mexc({'enableRateLimit':True,'options':{'defaultType':'swap'}})
ex.load_markets()
tickers = ex.fetch_tickers()
valid_syms = [s for s in tickers if is_valid_crypto(s)]
print(f"Valid: {len(valid_syms)}", flush=True)

gainers48=[]
for sym in valid_syms:
    try:
        t = tickers.get(sym,{})
        last_price = t.get('last') or t.get('close')
        if not last_price: continue
        vol = t.get('quoteVolume',0) or 0
        if vol < 30000: continue
        # 48h LIVE gain = live price / close 2 days ago
        ohlcv = ex.fetch_ohlcv(sym, '1d', limit=3)
        if len(ohlcv)<3: continue
        close_2d_ago = float(ohlcv[-3][4])
        if close_2d_ago==0: continue
        gain48_live = (float(last_price) / close_2d_ago - 1) * 100
        if gain48_live < 15: continue
        gainers48.append((sym, gain48_live))
    except:
        continue

gainers48.sort(key=lambda x:x[1],reverse=True)
top=gainers48[:TOP_GAINERS]

top_list=[f"{s.split('/')[0]} {c:.1f}%" for s,c in top[:10]]
print(f"LAST 48h LIVE TOP {TOP_GAINERS} (>15%): {top_list}", flush=True)

found=0
for sym,gain48 in top:
    coin = sym.split('/')[0].upper()
    if coin in hist and time.time()-hist[coin] < COOLDOWN*3600:
        print(f"Skip {coin} - 24h block", flush=True)
        continue
    for tf in TIMEFRAMES:
        try:
            print(f"Checking {coin} {tf} LIVE48h +{gain48:.1f}%", flush=True)
            ohlcv=ex.fetch_ohlcv(sym,tf,limit=300)
            df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            sig=detect_bearish_choch_early(df)
            if not sig: continue
            chart,live=draw(df,sym,sig,'MEXC',tf,gain48)
            cap=f"🔴 *BEAR CHoCH EARLY {tf} - LAST 48h LIVE TOP*\n\n*Pair:* `{sym}` | MEXC\n*LIVE 48h:* `+{gain48:.2f}%` (>15%)\n*Break:* `{sig['lower']:.6f}`\n*Short Zone:* `{sig['fib_bot']:.6f}` - `{sig['fib_top']:.6f}`\n*SL:* `{sig['rangeTop']:.6f}`\n*Live:* `{live:.6f}`\n*Time:* {now.strftime('%H:%M PKT')}\n*Block 24h 1x*"
            send_photo(chart,cap)
            hist[coin]=time.time()
            save_hist(hist)
            found+=1
            print(f"ALERT {coin} LIVE48h +{gain48:.1f}%", flush=True)
            break
        except Exception as e:
            print(f"err {coin} {e}", flush=True)
            continue

print(f"Done. Found {found} | LAST 48h LIVE >15%", flush=True)
