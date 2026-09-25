#!/usr/bin/env python3
"""night/angles_excerpt.py — 事前登録 out/angles4_prereg.json の A1/A2 用に、匿名化した抜粋を作る

2013年アンカー（filed <= 2013-07-01）で最新の 10-K または 20-F を取り、
(1) Item 1（事業）の冒頭 最大18,000字 (2) 資金の使い道・市場・成長に触れる段落 最大12,000字 を抜き出す。
社名（歴代の名前）・ティッカー・社名の先頭語を [COMPANY] に置き換える。株価・リターンは入れない。
出力は _angles_data/excerpts/{T}.txt（gitignore・原本の写しなので commit しない）と out/angles_excerpt_index.json（件数と出典だけ）。

使い方: python3 night/angles_excerpt.py [--only A,MSFT]
"""
import json, os, re, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import moat4_text as mt          # get() / text_of()（SEC のレートと詰まり対策を共有）
import angles_13f as a13         # names_by_cik()

DST = os.path.join(BASE, '_angles_data', 'excerpts')
KEY = re.compile(r'(repurchas|buyback|dividend|acqui|capital allocation|return on (invested )?capital|reinvest|capital expenditure|'
                 r'market share|addressable|growth (strateg|opportunit)|expan(d|sion) (into|our)|new markets|mature|saturat|'
                 r'share count|dilut|hurdle|intrinsic value|internal rate of return|payback)', re.I)

def filings(cik):
    j = json.loads(mt.get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json'))
    out = []
    def eat(r):
        for f, a, d, fm in zip(r['filingDate'], r['accessionNumber'], r['primaryDocument'], r['form']):
            if fm in ('10-K', '20-F') and f <= '2013-07-01': out.append((f, a, d, fm))
    eat(j['filings']['recent'])
    for p in j['filings'].get('files', []):
        if p.get('filingFrom', '9999') <= '2013-07-01': eat(json.loads(mt.get('https://data.sec.gov/submissions/' + p['name'])))
    return sorted(out, reverse=True)

def excerpt(t):
    m = re.search(r'item\s*1\.?\s*(\(?[a-z]\)?\s*)?business', t, re.I)
    starts = [x.start() for x in re.finditer(r'item\s*1\.?\s*business', t, re.I)]
    s0 = starts[1] if len(starts) > 1 else (starts[0] if starts else (m.start() if m else 0))  # 目次の次の本物の見出し
    e = re.search(r'item\s*1a\.?\s*risk', t[s0 + 200:], re.I)
    biz = t[s0: s0 + 200 + (e.start() if e else 18000)][:18000]
    paras, n = [], 0
    for sent in re.split(r'(?<=[.;])\s+', t):
        if KEY.search(sent) and 40 < len(sent) < 1200 and sent not in biz:
            paras.append(sent); n += len(sent)
            if n > 12000: break
    return biz, ' '.join(paras)

def anon(s, names, ticker):
    pats = set()
    for nm in names:
        base = re.sub(r'[,.]?\s*(inc|corp(oration)?|co|company|ltd|limited|plc|holdings?|group|n\.?v|s\.?a|ag|se)\.?$', '', nm.strip(), flags=re.I).strip()
        if len(base) >= 3: pats.add(r'[\s\-]+'.join(re.escape(w) for w in base.split()))  # 空白とハイフンのどちらでも（Curtiss-Wright）
        first = base.split()[0] if base.split() else ''
        if len(first) >= 4 and first.lower() not in ('american', 'united', 'national', 'general', 'first', 'international', 'global', 'north', 'south'):
            pats.add(re.escape(first))
    pats.add(r'\b' + re.escape(ticker) + r'\b')
    for p in sorted(pats, key=len, reverse=True):
        s = re.sub(p, '[COMPANY]', s, flags=re.I)
    return s

def main():
    args = sys.argv[1:]; only = set(args[args.index('--only') + 1].split(',')) if '--only' in args else None
    os.makedirs(DST, exist_ok=True)
    tick = [r['ticker'] for r in json.load(open(os.path.join(BASE, 'out', 'retro_moat_pillars_2013.json')))['rows']]
    cik = json.load(open(os.path.join(BASE, 'out', '_cik_tickers.json')))
    for f in ('retro_cohort_2013.json', 'retro_cohort_2015.json'):
        for r in json.load(open(os.path.join(BASE, 'out', f)))['rows']:
            if r.get('ticker') and r.get('cik') and r['ticker'] not in cik: cik[r['ticker']] = r['cik']
    names = a13.names_by_cik()
    idx_p = os.path.join(BASE, 'out', 'angles_excerpt_index.json')
    idx = json.load(open(idx_p)) if os.path.exists(idx_p) else {}
    for i, t in enumerate(tick, 1):
        if (only and t not in only) or (not only and t in idx and os.path.exists(os.path.join(DST, t + '.txt'))): continue
        try:
            c = int(cik[t]); fl = filings(c)
            if not fl: idx[t] = dict(err='2013-07-01 以前の10-K/20-Fが無い'); continue
            f, a, d, fm = fl[0]; base = f'https://www.sec.gov/Archives/edgar/data/{c}/{a.replace("-", "")}/'
            txt = mt.text_of(mt.get(base + d))
            try:
                for it in json.loads(mt.get(base + 'index.json'))['directory']['item']:
                    if re.search(r'ex-?13', it['name'], re.I) and it['name'].lower().endswith(('.htm', '.html', '.txt')):
                        txt += ' ' + mt.text_of(mt.get(base + it['name']))
            except Exception: pass
            biz, cap = excerpt(txt)
            nm = names.get(c, set())
            body = anon(f'=== 事業（Item 1 の抜粋）===\n{biz}\n\n=== 資金の使い道・市場・成長に触れる文 ===\n{cap}', nm, t)
            open(os.path.join(DST, t + '.txt'), 'w').write(body)
            leak = [n for n in nm if len(n) > 5 and n.lower() in body.lower()]
            idx[t] = dict(form=fm, filed=f, acc=a, chars=len(body), name_left=bool(leak))
        except Exception as e:
            idx[t] = dict(err=f'{type(e).__name__}: {str(e)[:80]}')
        if i % 10 == 0:
            json.dump(idx, open(idx_p, 'w'), ensure_ascii=False); print(i, t, flush=True)
    json.dump(idx, open(idx_p, 'w'), ensure_ascii=False)
    print('完了', len(idx), 'err', sum('err' in v for v in idx.values()), '社名が残った', sum(v.get('name_left', False) for v in idx.values()))

if __name__ == '__main__':
    main()
