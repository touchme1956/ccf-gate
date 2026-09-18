# night/etf_beat_spy.py — 楽天で買える米国上場ETF全数を「S&P500に勝ったか」で測る（2026-08-24新設）
#
# 【この道具が答えられること / 答えられないこと】
#   答えられない: **今後どのETFが勝つか**（予測）。
#   答えられる: (1)同じ窓でSPYに勝ったETFはどれで、何本あるか
#             (2)勝った群に共通する「観測できる特徴」（費用・分類・集中の系譜・設定年）
#             (3)勝ちは持続するか（5年の脚をまたいだ persistence・転がる10年の勝率）
#
# 【母集団】out/broker_lineup.json（楽天証券の海外ETF取扱一覧・742本）
#   ＝「今日 買えるもの」。⚠償還・上場廃止・取扱終了は最初から居ない＝**生存バイアスは構造的**。
#   勝率は上へ偏る。率ではなく「同じ母集団の中の比較」でだけ読むこと。
#
# 【窓】アンカー固定（2006-08 / 2011-08 / 2016-08 / 2021-08 → 直近の完全な月）。
#   各窓は**その窓の全月を持つETFだけ**で比較する＝設定日の罠（URA/URNM型）を構造で防ぐ。
#   全期間の年率を並べない（etf_returns.py で実証済みの「基準の違う二つ」型）。
#
# 【通貨】USDどうしの比較。円換算は全銘柄に同じ係数が掛かるので相対比較には効かない。
#
# 実行: python3 night/etf_beat_spy.py [--fetch] [--json]
#   --fetch はYahooから取り直す（キャッシュ out/_etf_beat_cache.json.gz・gitignore）。
import json, os, sys, gzip, re, time
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "night"))
import etf_theme as T   # fetch()（gmtoffsetで月を揃える）を再実装しない（v9.9.65）

OUT = os.path.join(BASE, "out", "etf_beat_spy.json")
CACHE = os.path.join(BASE, "out", "_etf_beat_cache.json.gz")

LEV = re.compile(r"(?i)\b(2x|3x|-1x|ultrapro|ultrashort|inverse|leveraged|yieldboost|weeklypay)\b"
                 r"|(?i:\bultra\b(?![- ]short))"
                 r"|(?i:(?<!ultra-)(?<!ultra )\bshort\b(?![- ]?term|[- ]?duration|[- ]?maturity|[- ]?treasury|[- ]?income))"
                 r"|(?i:daily .*\b(?:bull|bear|target)\b)|(?i:\b(?:bull|bear)\b.*\bdaily\b)")
# ⚠JPST『Ultra-Short Income』=短期債は除外しない（反証で誤除外を検出）／ProShares『Short S&P500』(-1x)は除外する
CLS = [
    ("レバ・インバース", LEV),
    ("債券", re.compile(r'(?i)\b(bond|treasury|aggregate|corporate|municipal|tips|floating|credit|high yield|fallen)\b')),
    ("商品", re.compile(r'(?i)\b(gold|silver|oil|commodit|copper|palladium|platinum|natural gas|agricult)\b')),
    ("半導体", re.compile(r'(?i)semiconductor')),
    ("テック", re.compile(r'(?i)\b(technology|tech|internet|software|nasdaq[- ]?100|qqq)\b')),
    ("ヘルスケア", re.compile(r'(?i)\b(health|biotech|pharma|medical|genomic)\b')),
    ("金融", re.compile(r'(?i)\b(financ|bank|insurance)\b')),
    ("エネルギー", re.compile(r'(?i)\b(energy|mlp|pipeline|solar|clean|wind|uranium|nuclear)\b')),
    ("素材・資源", re.compile(r'(?i)\b(materials|mining|miners|steel|timber|lithium)\b')),
    ("公益", re.compile(r'(?i)\butilit\b|\butilities\b')),
    ("生活必需品", re.compile(r'(?i)\b(staples|consumer staples)\b')),
    ("一般消費財", re.compile(r'(?i)\b(discretionary|retail|homebuild|leisure)\b')),
    ("資本財・防衛", re.compile(r'(?i)\b(industrial|aerospace|defen[cs]e|infrastructure)\b')),
    ("不動産", re.compile(r'(?i)\b(real estate|reit)\b')),
    ("配当・インカム", re.compile(r'(?i)\b(dividend|income|covered call|buywrite)\b')),
    ("因子", re.compile(r'(?i)\b(momentum|quality|value|low vol|min vol|growth|equal weight|buyback|moat)\b')),
    ("国際", re.compile(r'(?i)\b(emerging|eafe|ex[- ]?us|international|china|japan|india|brazil|korea|taiwan|europe|germany|mexico|africa|vietnam|global|world|acwi|frontier)\b')),
    ("小型・中型", re.compile(r'(?i)\b(small|mid[- ]?cap|micro)\b')),
    ("米国広域", re.compile(r'(?i)\b(s&p 500|total (stock )?market|russell [13]000|dow jones industrial|core s&p)\b')),
]
def classify(nm):
    # ⚠参考のみ。反証(2026-08-24)で死文字5本(financ/commodit/agricult/utilit/pharma)と略記の取りこぼし
    #   (XLY『Consumer Disc』等)が判明＝beat行の18%が「その他テーマ」。勝者の構成は名前を手で読むこと。
    #   beat/cagr/maxdd は classify と独立で、111本の全数再計算で食い違い0を確認済み。
    for k, rx in CLS:
        if rx.search(nm or ""): return k
    return "その他テーマ"

def load_cache():
    if os.path.exists(CACHE):
        with gzip.open(CACHE, "rt") as f: return json.load(f)
    return {}

def save_cache(c):
    with gzip.open(CACHE, "wt") as f: json.dump(c, f)

def fetch_all(tickers):
    cache = load_cache(); miss = [t for t in tickers if t not in cache]
    print(f"fetch: cache {len(cache)} / 取りに行く {len(miss)}", file=sys.stderr)
    def one(t):
        try: return t, T.fetch(t)
        except Exception: return t, None
    with ThreadPoolExecutor(6) as ex:
        for i, (t, s) in enumerate(ex.map(one, miss)):
            cache[t] = s
            if i % 50 == 49: save_cache(cache); print(f"  {i+1}/{len(miss)}", file=sys.stderr)
    save_cache(cache)
    return cache

def cagr(ser, a, b):
    if a not in ser or b not in ser: return None
    ms = sorted(m for m in ser if a <= m <= b)
    # 窓の全月を持つこと（欠けた月があれば比較しない＝穴を跨いで年率を作らない）
    n = (int(b[:4])-int(a[:4]))*12 + int(b[5:7])-int(a[5:7])
    if len(ms) < n*0.97: return None
    yrs = n/12.0
    return (ser[b]/ser[a])**(1/yrs)-1, maxdd(ser, a, b), yrs

def maxdd(ser, a, b):
    pk=None; dd=0
    for m in sorted(ser):
        if not (a<=m<=b): continue
        v=ser[m]; pk = v if pk is None or v>pk else pk
        dd=min(dd, v/pk-1)
    return dd

def main():
    lineup = json.load(open(os.path.join(BASE,"out","broker_lineup.json")))["etfs"]
    tickers = sorted(lineup)
    px = fetch_all(tickers + ["SPY"])
    spy = px.get("SPY")
    if not spy: print("SPYが取れない＝測定不能で中止", file=sys.stderr); sys.exit(1)
    end = sorted(spy)[-1]
    if end.endswith(f"{time.gmtime().tm_mon:02d}") and str(time.gmtime().tm_year) == end[:4]:
        end = sorted(spy)[-2]   # 進行中の月は使わない
    anchors = ["2006-08","2011-08","2016-08","2021-08"]
    res = {"generated": time.strftime("%Y-%m-%d"), "end": end,
           "母集団": "out/broker_lineup.json（楽天の海外ETF取扱742本）＝生存バイアスは構造的（償還・取扱終了は最初から居ない）",
           "windows": {}, "取得失敗": [], "レバ・インバース除外": []}
    got = {}
    for t in tickers:
        nm = lineup[t].get("nm","")
        if LEV.search(nm):                       # 名前で判るものは取得の成否より先に勘定する（反証: 旧順序はレバ23本を「取得失敗」に数えた）
            res["レバ・インバース除外"].append(t); continue
        s = px.get(t)
        if not s or len(s) < 6:
            res["取得失敗"].append(t); continue
        got[t] = (s, nm, lineup[t].get("er",""))
    for a in anchors:
        base = cagr(spy, a, end)
        if not base: continue
        rows=[]
        for t,(s,nm,er) in got.items():
            c = cagr(s, a, end)
            if not c: continue
            rows.append({"t":t,"nm":nm,"er":er,"cagr":round(c[0]*100,2),"maxdd":round(c[1]*100,1),
                         "cls":classify(nm),"beat":c[0]>base[0]})
        rows.sort(key=lambda r:-r["cagr"])
        beat=[r for r in rows if r["beat"]]
        res["windows"][a]={"spy":round(base[0]*100,2),"spy_maxdd":round(base[1]*100,1),"yrs":round(base[2],2),
                           "n":len(rows),"beat_n":len(beat),
                           "beat_share":round(len(beat)/len(rows),3) if rows else None,
                           "rows":rows}
    # 5年の脚の persistence（2011-16 → 16-21 → 21-26）
    legs=[("2011-08","2016-08"),("2016-08","2021-08"),("2021-08",end)]
    lb={}
    for a,b in legs:
        sb=cagr(spy,a,b)
        if not sb: continue
        d={}
        for t,(s,nm,er) in got.items():
            c=cagr(s,a,b)
            if c: d[t]=c[0]>sb[0]
        lb[f"{a}→{b}"]=d
    keys=list(lb)
    pers=[]
    for i in range(len(keys)-1):
        A,B=lb[keys[i]],lb[keys[i+1]]
        both=[t for t in A if t in B]
        w=[t for t in both if A[t]]; l=[t for t in both if not A[t]]
        pw=sum(B[t] for t in w)/len(w) if w else None
        pl=sum(B[t] for t in l)/len(l) if l else None
        pers.append({"from":keys[i],"to":keys[i+1],"n":len(both),
                     "P(次も勝つ|勝った)":round(pw,3) if pw is not None else None,
                     "P(次は勝つ|負けた)":round(pl,3) if pl is not None else None,
                     "lift":round(pw-pl,3) if (pw is not None and pl is not None) else None})
    res["persistence_5y脚"]=pers
    # 転がる10年（15年以上の履歴を持つETFのみ・全120ヶ月窓の勝率）
    roll={}
    ms_spy=sorted(spy)
    for t,(s,nm,er) in got.items():
        ms=sorted(m for m in s if m<=end)
        if len(ms)<181: continue
        wins=tot=0
        for i in range(len(ms)-120):
            a,b=ms[i],ms[i+120]
            if a not in spy or b not in spy: continue
            tot+=1
            if (s[b]/s[a]) > (spy[b]/spy[a]): wins+=1
        if tot>=60: roll[t]={"nm":nm,"windows":tot,"beat_share":round(wins/tot,3)}
    res["rolling10y"]=dict(sorted(roll.items(),key=lambda kv:-kv[1]["beat_share"])[:40])
    res["rolling10y_n"]=len(roll)
    json.dump(res, open(OUT,"w"), ensure_ascii=False, indent=1)
    # 画面
    for a,w in res["windows"].items():
        print(f"\n【{a} → {end}（{w['yrs']}年）】SPY {w['spy']}%/年 (dd {w['spy_maxdd']}%)  比較できた {w['n']}本 → 勝った {w['beat_n']}本 ({w['beat_share']*100:.0f}%)")
        for r in w["rows"][:15]:
            print(f"  {r['t']:6} {r['cagr']:>6.2f}%/年 dd{r['maxdd']:>6.1f}% er={r['er'] or '?':>5} [{r['cls']}] {r['nm'][:44]}")
    print("\npersistence:", json.dumps(pers,ensure_ascii=False))
    print("取得失敗", len(res["取得失敗"]), "レバ除外", len(res["レバ・インバース除外"]))

if __name__=="__main__":
    main()
