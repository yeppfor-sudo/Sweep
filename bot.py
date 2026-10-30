# bot.py - BEARISH CHoCH 15m REAL TIME PHOTO + 24H TOP GAINERS + ALL CEX
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
    base = sym.split('/')[0].upper()
    if any(x in base for x in ['STOCK','ETF','SOX','QQQ','SPX','DJI','SKDD','XSOX','TLT','SPY','DIA','GDX','XAU','PAXG','GOLD','XAG','LEAD','COPPER','NICKEL','ZINC','TIN','GLD','SLV','ALUM']): return False
    if base in BLOCK_ALL: return False
    if len(base) < 2 or len(base) > 6: return False
    if any(c.isdigit() for c in base): return False
    if not base.isalpha(): return False
    return True

def send_msg(t):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":CHAT,"text":t,"parse_mode":"Markdown"}, timeout=20)

def send_photo(p,c):
    with open(p,'rb') as f:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data={"chat_id":CHAT,"caption":c,"parse_mode":"Markdown"}, files={"photo":f}, timeout=30)

def load_hist():
    try: 
        with open(HIST_FILE,'r') as f: return json.load(f)
    except: return {}
def save_hist(d):
    with open(HIST_FILE,'w') as f: json.dump(d,f)

def is_pivot_high(df, idx, length):
    if idx < length or idx >= len(df)-length: return False
    return df['h'].iloc[idx] == df['h'].iloc[idx-length:idx+length+1].max()

def is_pivot_low(df, idx, length):
    if idx < length or idx >= len(df)-length: return False
    return df['l'].iloc[idx] == df['l'].iloc[idx-length:idx+length+1].min()

def detect_bearish_choch_only(df):
    if len(df) < 100: return None
    upperLevel = None; lowerLevel = None; upperBroken=False; lowerBroken=False; marketDirection=0
    events=[]
    for i in range(FRACTAL_LEN, len(df)-1):
        if is_pivot_high(df,i,FRACTAL_LEN): upperLevel=float(df['h'].iloc[i]); upperBroken=False
        if is_pivot_low(df,i,FRACTAL_LEN): lowerLevel=float(df['l'].iloc[i]); lowerBroken=False
        if upperLevel is None or lowerLevel is None: continue
        close=float(df['c'].iloc[i])
        if not lowerBroken and lowerLevel:
            if close < lowerLevel and float(df['c'].iloc[i-1]) >= lowerLevel:
                lowerBroken=True
                if marketDirection==1:
                    events.append({'type':'BEAR_CHOCH','bar':i,'price':close,'upper':upperLevel,'lower':lowerLevel,'eq':(upperLevel+float(df['l'].iloc[i]))/2,'rangeTop':upperLevel,'rangeBottom':float(df['l'].iloc[i]),'fib_top':upperLevel-(upperLevel-float(df['l'].iloc[i]))*0.382,'fib_bot':upperLevel-(upperLevel-float(df['l'].iloc[i]))*0.618})
                marketDirection=-1
        if not upperBroken and upperLevel:
            if close > upperLevel and float(df['c'].iloc[i-1]) <= upperLevel:
                upperBroken=True; marketDirection=1
    if not events: return None
    last=events[-1]
    if last['bar'] != len(df)-2: return None
    return last

def draw_choch(df, sym, sig, exn, gain24, live_price):
    fig, ax = plt.subplots(figsize=(13,6), facecolor='black')
    ax.set_facecolor('black')
    view=df.tail(80).copy()
    for i,(_,r) in enumerate(view.iterrows()):
        col='#089981' if r['c']>=r['o'] else '#f23645'
        ax.plot([i,i],[r['l'],r['h']],color=col,lw=1)
        ax.plot([i,i],[r['o'],r['c']],color=col,lw=4)
    ax.axhline(sig['lower'], color='white', ls='--', lw=1, label=f"CHoCH Break {sig['lower']:.6f}")
    ax.axhline(sig['upper'], color='gray', ls=':', lw=1)
    ax.axhspan(sig['rangeBottom'], sig['rangeTop'], color='#f23645', alpha=0.12)
    ax.axhline(sig['eq'], color='#f23645', ls='--', lw=1, label=f"EQ {sig['eq']:.6f}")
    ax.axhspan(sig['fib_bot'], sig['fib_top'], color='#f23645', alpha=0.4, label="SHORT Zone 0.382-0.618")
    ax.axhline(live_price, color='yellow', ls='-', lw=1.2, label=f"LIVE {live_price:.6f}")
    ax.set_title(f"{sym} {exn} 15m BEAR_CHoCH | 24h {gain24:.1f}% | Closed {sig['price']:.6f} | Live {live_price:.6f}", color='white', fontweight='bold')
    ax.legend(facecolor='black', labelcolor='white', fontsize=7)
    ax.grid(alpha=0.1)
    plt.tight_layout()
    path=f"chart_{sym.replace('/','')}_{exn}_15m.png"
    plt.savefig(path,dpi=150,facecolor='black')
    plt.close()
    return path

EXS = [('BINANCE', ccxt.binanceusdm, {'enableRateLimit': True}),('MEXC', ccxt.mexc, {'enableRateLimit': True, 'options': {'defaultType':'swap'}}),('OKX', ccxt.okx, {'enableRateLimit': True, 'options': {'defaultType':'swap'}}),('GATE', ccxt.gate, {'enableRateLimit': True, 'options': {'defaultType':'swap'}}),('BITGET', ccxt.bitget, {'enableRateLimit': True, 'options': {'defaultType':'swap'}})]

hist=load_hist()
now=datetime.now(PKT)
total_found=0

for exn, cls, opts in EXS:
    try:
        ex=cls(opts); ex.load_markets()
        syms=[s for s in ex.markets if is_valid_crypto(s)]
        tickers=ex.fetch_tickers()
        gainers=[]
        for sym in syms:
            t=tickers.get(sym)
            if not t: continue
            ch=t.get('percentage',0); vol=t.get('quoteVolume',0)
            if ch is None or vol < 300_000: continue
            gainers.append((sym,ch))
        gainers.sort(key=lambda x: x[1], reverse=True)
        top=gainers[:TOP_GAINERS]
        for sym,ch24 in top:
            key=f"{exn}_{sym.split('/')[0]}"
            if key in hist and time.time()-hist[key] < COOLDOWN*3600: continue
            ohlcv=ex.fetch_ohlcv(sym,'15m',limit=500)
            if not ohlcv or len(ohlcv)<100: continue
            df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            df['time']=pd.to_datetime(df['t'], unit='ms', utc=True)
            sig=detect_bearish_choch_only(df)
            if not sig: continue
            live_price=float(df['c'].iloc[-1])
            chart=draw_choch(df,sym,sig,exn,ch24,live_price)
            cap=f"🔴 *BEAR_CHOCH 15m REAL TIME*\n\n*Pair:* {sym} | {exn}\n*24h Gainer:* `{ch24:.2f}%` TOP {TOP_GAINERS}\n*Closed Price:* `{sig['price']:.6f}`\n*Live Price:* `{live_price:.6f}`\n*Break Level:* `{sig['lower']:.6f}`\n*Short Zone:* `{sig['fib_bot']:.6f}` - `{sig['fib_top']:.6f}`\n*SL:* `{sig['rangeTop']:.6f}`\n*Time:* {now.strftime('%I:%M %p')} PKT - Previous Closed Candle"
            send_photo(chart,cap)
            hist[key]=time.time(); save_hist(hist); total_found+=1; time.sleep(1)
    except Exception as e:
        print(f"{exn} {e}"); continue

if total_found==0:
    send_msg(f"No BEAR_CHoCH 15m in TOP {TOP_GAINERS} gainers - {now.strftime('%H:%M PKT')}")
