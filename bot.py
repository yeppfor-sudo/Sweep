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
COOLDOWN = 2
TOP_GAINERS = 30

BLOCK_ALL = {'BTC','ETH','SOL','BNB','TRX','XRP','ADA','DOGE','AVAX','DOT','LINK','LTC','BCH','XLM','ETC','HBAR','APT','NEAR','UNI','FIL','ARB','OP','ATOM','MATIC','POL','TON','SHIB','PEPE','CRO','LEO','OKB','BGB','SUI','LDO','RNDR','TAO','FET','WIF','ENA','JUP','SEI','TIA','ONDO','W','PYTH','STRK','JTO','ENS','TLT','TLH','IEF','SHY','INDA','EWJ','EWA','EWZ','KWEB','QQQ','SPY','DIA','IWM','EWW','EWC','MCHI','INDY','STRC','OURA','SPX','SPX500','NAS100','DJI','US30','UK100','GER40','RKLB','NVDA','AAPL','TSLA','MSFT','STOCK','ETF','OIL','SILVER','GOLD','XAU','XAG','XAUT','PAXG','KAU','TRY','EUR','GBP','JPY','AUD','CAD','CHF','NZD','USDC','BUSD','FDUSD','TUSD','DAI','USDE','USDP','GUSD','PYUSD','EURI','EURC','XLU','XLP','XLE','XLF','XLB','XLI','XLY','XLK','XLV','GLD','SLV','GDX','GDXJ','COPX','LIT','URA','SQQQ','TQQQ','SOXS','SOXL','SPXS','SPXL','SKDD','XSOXS','XSOX','LABU','LABD','TECL','TECS','UPRO','SPXU','TZA','TNA','FAS','FAZ','SDOW','UDOW','LEAD','COPPER','NICKEL','ZINC','TIN','ALUM'}

def is_valid_crypto(sym):
    if not sym.endswith('USDT:USDT'): return False
    base=sym.split('/')[0].upper()
    if any(x in base for x in ['STOCK','ETF','SOX','QQQ','SPX','DJI','SKDD','XSOX','TLT','SPY','DIA','GDX','XAU','PAXG','GOLD','XAG','LEAD','COPPER','NICKEL','ZINC','TIN','GLD','SLV','ALUM']): return False
    if base in BLOCK_ALL: return False
    if len(base)<2 or len(base)>6: return False
    if any(c.isdigit() for c in base): return False
    if not base.isalpha(): return False
    return True

def send_msg(t):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":CHAT,"text":t,"parse_mode":"Markdown"}, timeout=20)
    except: pass

def send_photo(p,c):
    try:
        with open(p,'rb') as f:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data={"chat_id":CHAT,"caption":c,"parse_mode":"Markdown"}, files={"photo":f}, timeout=30)
    except: pass

def load_hist():
    try:
        with open(HIST_FILE,'r') as f: return json.load(f)
    except: return {}
def save_hist(d):
    with open(HIST_FILE,'w') as f: json.dump(d,f)

def get_48h_gain(ex, sym):
    try:
        ohlcv=ex.fetch_ohlcv(sym,'1d',limit=5)
        if not ohlcv or len(ohlcv)<3: return -999
        # Previous closed 2d gain: close yesterday / close 2 days ago - 1 (true 48h closed)
        # Use -2 = yesterday closed, -3 = 2 days ago closed
        c_yesterday=float(ohlcv[-2][4])
        c_2d_ago=float(ohlcv[-3][4])
        if c_2d_ago<=0: return -999
        return (c_yesterday/c_2d_ago-1)*100
    except: return -999

def is_pivot_high(df, idx, length):
    if idx < length or idx >= len(df)-length: return False
    return df['h'].iloc[idx] == df['h'].iloc[idx-length:idx+length+1].max()

def is_pivot_low(df, idx, length):
    if idx < length or idx >= len(df)-length: return False
    return df['l'].iloc[idx] == df['l'].iloc[idx-length:idx+length+1].min()

def detect_bearish_choch(df):
    if len(df)<100: return None
    upper=None; lower=None; upBroken=False; lowBroken=False; direction=0
    events=[]
    for i in range(FRACTAL_LEN, len(df)-1):
        if is_pivot_high(df,i,FRACTAL_LEN): upper=float(df['h'].iloc[i]); upBroken=False
        if is_pivot_low(df,i,FRACTAL_LEN): lower=float(df['l'].iloc[i]); lowBroken=False
        if upper is None or lower is None: continue
        close=float(df['c'].iloc[i])
        if not lowBroken and lower:
            if close < lower and float(df['c'].iloc[i-1]) >= lower:
                lowBroken=True
                if direction==1:
                    low_val=float(df['l'].iloc[i])
                    events.append({'type':'BEAR_CHOCH','bar':i,'price':close,'upper':upper,'lower':lower,'eq':(upper+low_val)/2,'rangeTop':upper,'rangeBottom':low_val,'fib_top':upper-(upper-low_val)*0.382,'fib_bot':upper-(upper-low_val)*0.618})
                direction=-1
        if not upBroken and upper:
            if close > upper and float(df['c'].iloc[i-1]) <= upper:
                upBroken=True; direction=1
    if not events: return None
    last=events[-1]
    if last['bar'] != len(df)-2: return None
    return last

def draw_real_time(df, sym, sig, exn, gain48):
    fig, ax = plt.subplots(figsize=(14,6), facecolor='black')
    ax.set_facecolor('black')
    view=df.tail(80).copy()
    live=float(view['c'].iloc[-1])
    for i,(_,r) in enumerate(view.iterrows()):
        col='#089981' if r['c']>=r['o'] else '#f23645'
        ax.plot([i,i],[r['l'],r['h']],color=col,lw=1)
        ax.plot([i,i],[r['o'],r['c']],color=col,lw=4)
    ax.axhline(sig['lower'], color='white', ls='--', lw=1.2, label=f"CHoCH BREAK {sig['lower']:.6f}")
    ax.axhline(sig['upper'], color='gray', ls=':', lw=1)
    ax.axhspan(sig['rangeBottom'], sig['rangeTop'], color='#f23645', alpha=0.12)
    ax.axhline(sig['eq'], color='#f23645', ls='--', lw=1, label=f"EQ {sig['eq']:.6f}")
    ax.axhspan(sig['fib_bot'], sig['fib_top'], color='#f23645', alpha=0.45, label=f"SELL ZONE")
    ax.axhline(live, color='yellow', lw=1.5, label=f"LIVE {live:.6f}")
    ax.scatter(len(view)-2, sig['price'], color='white', s=150, zorder=5, marker='v')
    ax.set_title(f"{sym} {exn} 15m BEAR_CHoCH | 48h +{gain48:.1f}% | Closed {sig['price']:.6f} | Live {live:.6f}", color='white', fontweight='bold', fontsize=11)
    ax.legend(facecolor='black', labelcolor='white', fontsize=7)
    ax.grid(alpha=0.15)
    plt.tight_layout()
    path=f"chart_{sym.replace('/','')}_{exn}.png"
    plt.savefig(path,dpi=150,facecolor='black')
    plt.close()
    return path, live

EXS=[('BINANCE',ccxt.binanceusdm,{'enableRateLimit':True}),('MEXC',ccxt.mexc,{'enableRateLimit':True,'options':{'defaultType':'swap'}}),('OKX',ccxt.okx,{'enableRateLimit':True,'options':{'defaultType':'swap'}}),('GATE',ccxt.gate,{'enableRateLimit':True,'options':{'defaultType':'swap'}}),('BITGET',ccxt.bitget,{'enableRateLimit':True,'options':{'defaultType':'swap'}})]

hist=load_hist()
now=datetime.now(PKT)
send_msg(f"🚀 *Scan Started* 15m BEAR_CHoCH | 48H TOP {TOP_GAINERS} | ALL CEX | {now.strftime('%H:%M PKT')}")
found=0

for exn,cls,opts in EXS:
    try:
        ex=cls(opts); ex.load_markets()
        syms=[s for s in ex.markets if is_valid_crypto(s)]
        # 48H TOP GAINERS - Previous closed 48h gain
        gainers=[]
        for sym in syms:
            g=get_48h_gain(ex,sym)
            if g>-999 and g>=10:  # Only 10%+ in 48h
                gainers.append((sym,g))
        gainers.sort(key=lambda x: x[1], reverse=True)
        top=gainers[:TOP_GAINERS]
        if not top: continue
        send_msg(f"🏆 *{exn} 48H TOP {TOP_GAINERS}:* " + ", ".join([f"{s.split('/')[0]} {c:.1f}%" for s,c in top[:6]]))

        for sym,gain48 in top:
            key=f"{exn}_{sym.split('/')[0]}"
            if key in hist and time.time()-hist[key] < COOLDOWN*3600: continue
            ohlcv=ex.fetch_ohlcv(sym,'15m',limit=500)
            if not ohlcv or len(ohlcv)<120: continue
            df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            sig=detect_bearish_choch(df)
            if not sig: continue
            chart,live=draw_real_time(df,sym,sig,exn,gain48)
            cap=f"🔴 *BEAR_CHOCH 15m REAL TIME*\n\n*Pair:* `{sym}` | {exn}\n*48h Gainer:* `+{gain48:.2f}%` TOP {TOP_GAINERS}\n*Closed CHoCH:* `{sig['price']:.6f}`\n*Live:* `{live:.6f}`\n*Break Level:* `{sig['lower']:.6f}`\n*Short Zone:* `{sig['fib_bot']:.6f}` - `{sig['fib_top']:.6f}`\n*SL:* `{sig['rangeTop']:.6f}`\n*Time:* {now.strftime('%Y-%m-%d %I:%M %p')} PKT\n*48H Top Gainer + Bearish CHoCH Previous Closed*"
            send_photo(chart,cap)
            hist[key]=time.time(); save_hist(hist); found+=1; time.sleep(1.2)
    except Exception as e:
        print(f"{exn} {e}"); continue

if found==0:
    send_msg(f"No BEAR_CHoCH in 48H TOP {TOP_GAINERS}")
else:
    send_msg(f"✅ Found {found} BEAR_CHoCH 48H gainers")
