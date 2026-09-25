#!/usr/bin/env python3
"""night/moat4_text.py — 事前登録 out/moat4_prereg.json の C3（値上げの記述）と C4（顧客維持率の開示）の採取

アンカー（2013-07 / 2018-07）時点で最新の 10-K（filed <= アンカー年-07-01）を SEC から取り、
本文の語数・値上げの句の出現数・NRR の百分率だけを残す（本文は保存しない）。
句は事前登録の regex をそのまま読む（ここに写さない）。

使い方: python3 night/moat4_text.py [--only A,MSFT] [--limit N]   出力: out/moat4_text.json（途中でも追記保存）
"""
import json, os, re, sys, time, html, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out')
sys.argv_saved = sys.argv; sys.argv = ['x']
sys.path.insert(0, BASE)
import hachimon_fetch as h  # User-Agent（メールは設定済み）
sys.argv = sys.argv_saved

PRE = json.load(open(os.path.join(OUT, 'moat4_prereg.json')))
PHRASES = [re.compile(p, re.I) for p in PRE['candidates']['C3_pricing_text']['phrases_regex_case_insensitive']]
NRR_KEY = re.compile(r'(net\s+revenue\s+retention|dollar[- ]based\s+net\s+(revenue\s+)?retention|net\s+dollar\s+(revenue\s+)?retention|net\s+expansion\s+rate)', re.I)
PCT = re.compile(r'(\d{2,3}(?:\.\d+)?)\s*%')
ANCHORS = {'2013': '2013-07-01', '2018': '2018-07-01'}
DST = os.path.join(OUT, 'moat4_text.json')
GAP = 0.13  # 10 req/s 未満（--shard k/n のときは n 倍に広げて合計を守る）

_last = [0.0]
def get(url, tries=3):
    for i in range(tries):
        w = GAP - (time.time() - _last[0])
        if w > 0: time.sleep(w)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h.HDRS), timeout=30) as r:
                t0 = time.time(); buf = b''
                while True:  # 詰まった転送で永久に待たない（1本90秒で打ち切り）
                    ch = r.read(1 << 16)
                    if not ch: return buf
                    buf += ch
                    if time.time() - t0 > 90: raise TimeoutError('slow transfer')
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(2 * (i + 1))

def filings(cik):
    """10-K の (filed, acc, primaryDocument) を全ページから集める。"""
    j = json.loads(get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json'))
    out = []
    def eat(r):
        for f, a, d, fm in zip(r['filingDate'], r['accessionNumber'], r['primaryDocument'], r['form']):
            if fm == '10-K': out.append((f, a, d))
    eat(j['filings']['recent'])
    for p in j['filings'].get('files', []):
        if p.get('filingFrom', '9999') <= '2018-07-01':
            eat(json.loads(get('https://data.sec.gov/submissions/' + p['name'])))
    return out

TAG = re.compile(r'<[^>]+>')
def text_of(raw):
    s = raw.decode('utf-8', 'ignore')
    s = re.sub(r'(?is)<(script|style|ix:header)[^>]*>.*?</\1>', ' ', s)
    s = html.unescape(TAG.sub(' ', s))
    return re.sub(r'\s+', ' ', s)

def measure(t):
    words = len(t.split())
    hits = sum(len(p.findall(t)) for p in PHRASES)
    nrr = None
    for m in NRR_KEY.finditer(t):
        seg = t[m.end(): m.end() + 300]
        seg = seg.split('. ')[0]
        for x in PCT.findall(seg):
            v = float(x)
            if 100 <= v <= 200: nrr = v; break
        if nrr is not None: break
    return dict(words=words, hits=hits, nrr=nrr, nrr_mention=bool(NRR_KEY.search(t)))

def main():
    args = sys.argv[1:]
    only = set(args[args.index('--only') + 1].split(',')) if '--only' in args else None
    limit = int(args[args.index('--limit') + 1]) if '--limit' in args else None
    tick = [r['ticker'] for r in json.load(open(os.path.join(OUT, 'retro_features2_2018.json')))['rows']]
    ck = json.load(open(os.path.join(OUT, '_cik_tickers.json')))
    cmap = {}
    for k, v in (ck.items() if isinstance(ck, dict) else []):
        if isinstance(v, dict) and 'ticker' in v: cmap[v['ticker'].upper()] = int(v.get('cik_str') or v.get('cik'))
        elif isinstance(v, (int, str)) and str(v).isdigit(): cmap[k.upper()] = int(v)
    global GAP, DST
    if '--shard' in args:  # 並列: k/n。書き先を分け、間隔を n 倍にして SEC の合計を 10 req/s 未満に保つ
        k, n = map(int, args[args.index('--shard') + 1].split('/'))
        tick = tick[k::n]; GAP *= n; DST = DST.replace('.json', f'.{k}.json')
    res = json.load(open(DST)) if os.path.exists(DST) else {'rows': {}}
    todo = [t for t in tick if (only is None or t in only) and t not in res['rows']]
    if limit: todo = todo[:limit]
    print(f'対象 {len(todo)}社（済 {len(res["rows"])}）', flush=True)
    for i, t in enumerate(todo, 1):
        rec = {}
        cik = cmap.get(t.upper()) or cmap.get(t.upper().replace('.', '-'))
        if not cik:
            rec['err'] = 'CIK不明'
        else:
            try:
                fl = filings(cik)
                for y, dl in ANCHORS.items():
                    c = sorted([f for f in fl if f[0] <= dl], reverse=True)
                    if not c: rec[y] = None; continue
                    f, a, d = c[0]
                    base = f'https://www.sec.gov/Archives/edgar/data/{cik}/{a.replace("-", "")}/'
                    txt = text_of(get(base + d)); ex13 = []
                    try:  # 事前登録の修正 A2: MD&A を載せる別紙 EX-13 も本文に足す
                        for it in json.loads(get(base + 'index.json'))['directory']['item']:
                            n = it['name']
                            if re.search(r'ex-?13', n, re.I) and n.lower().endswith(('.htm', '.html', '.txt')):
                                txt += ' ' + text_of(get(base + n)); ex13.append(n)
                    except Exception:
                        pass
                    m = measure(txt); m.update(filed=f, acc=a, ex13=ex13)
                    rec[y] = m
            except Exception as e:
                rec['err'] = f'{type(e).__name__}: {str(e)[:80]}'
        res['rows'][t] = rec
        if i % 5 == 0 or i == len(todo):
            res['generated'] = time.strftime('%Y-%m-%d'); res['tool'] = 'night/moat4_text.py'
            json.dump(res, open(DST, 'w'), ensure_ascii=False)
            print(f'{i}/{len(todo)} {t}', flush=True)

if __name__ == '__main__':
    main()
