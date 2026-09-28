#!/usr/bin/env python3
"""night/gaps_delisted_irr.py — 歴史検証の穴⑦: 上場廃止した会社を戻しても irr の上乗せは残るか（読むだけ・判定に不使用）

事前登録: out/gaps7_prereg.json の Q7_survivor（9c28f6c・測る前に固定）
irr の歴史検証（retro_moat_2013*.json）は2026年まで生き残った会社だけを読んでいた。
2013年の質実証プールで上場廃止して成績が測れた96社（買収78・非公開化9・破産8・上場基準1）を同じ手順で読み、戻す。

手順（生き残りの読みと同じ二段）:
  prep   … 2013-07-01以前に提出した最新の年次報告書を SEC から取り、本文だけにして社名を伏せる。
           上場廃止96社＋較正の生き残り48社を混ぜ、読み手の束（12社ずつ）にする。どれが生き残りかは束に書かない
  quotes … 読み手の出力（read_*.json）から 70/85 を主張した引用だけを集め、採点者の束にする（引用文と id だけ）
  final  … 2人の採点を合わせて刻みを決め、P15・恒久毀損を刻みごとに出す
出力: out/gaps_delisted_irr/（束・読み・採点）と out/gaps_delisted_irr.json
"""
import hashlib, html, json, os, re, sys, time, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out')
DIR = os.path.join(OUT, 'gaps_delisted_irr')
SCR = os.environ.get('GAPS_SCRATCH') or os.path.join(BASE, 'out', '_gaps_irr_docs')   # 本文（伏せ字済み）の置き場。repo には入れない
CUTOFF = '2013-07-01'
HURDLE, IMPAIR = 0.15, -0.15


def L(p):
    return json.load(open(os.path.join(OUT, p), encoding='utf-8'))


def did(cik):
    return 'D' + hashlib.sha1(f'gaps7|{cik}'.encode()).hexdigest()[:8]


def population():
    rows = L('retro_delisted_2013.json')['rows']
    sp = {r['cik']: r for r in L('retro_delisted_secpx_2013.json')['rows']}
    q = [r for r in rows if r['quality']]
    delisted = [r for r in q if sp.get(r['cik'], {}).get('kind') == '退場(測定)' and sp[r['cik']].get('px_cagr') is not None]
    surv = [r for r in q if r['status'] == 'survivor' and sp.get(r['cik'], {}).get('px_cagr') is not None]
    read = {}
    for fn in ('retro_moat_2013.json', 'retro_moat_2013q.json'):
        for r in L(fn)['rows']:
            if r.get('irr') is not None:
                read[r['ticker']] = r['irr']
    t2r = {r.get('ticker_hist'): r for r in surv if r.get('ticker_hist')}
    surv_read = {t: v for t, v in read.items() if t in t2r}
    return q, delisted, surv, surv_read, t2r, sp


def calib_sample(surv_read):
    """較正の生き残り48社: 85/100 は全部・70 は1社おき・50 は5社おき（ティッカー昇順）"""
    hi = sorted(t for t, v in surv_read.items() if v >= 85)
    s70 = sorted(t for t, v in surv_read.items() if v in (70, 75))[::2][:18]
    s50 = sorted(t for t, v in surv_read.items() if v == 50)[::5][:24]
    return hi + s70 + s50


def to_text(raw):
    s = raw.decode('utf-8', 'ignore') if isinstance(raw, bytes) else raw
    s = re.sub(r'(?is)<(script|style).*?</\1>', ' ', s)
    s = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>', '\n', s)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    s = re.sub(r'[ \t\r\f\v\xa0]+', ' ', s)
    s = re.sub(r'\n\s*\n+', '\n\n', s)
    return s.strip()


STOP = {'inc', 'corp', 'corporation', 'co', 'company', 'ltd', 'limited', 'plc', 'holdings', 'holding', 'group',
        'the', 'of', 'and', 'nv', 'sa', 'ag', 'lp', 'llc', 'international', 'technologies', 'technology',
        'industries', 'systems', 'services', 'parent', 'new', 'de', 'del'}


def anonymize(text, name, tickers):
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z&'\-]+", name or '') if w.lower() not in STOP and len(w) >= 3]
    pats = []
    if name:
        base = re.sub(r'[,\.]', '', name).strip()
        pats.append(re.escape(base))
    if words:
        pats.append(r'\b' + r'\s+'.join(re.escape(w) for w in words) + r'\b')
        pats.append(r'\b' + re.escape(words[0]) + r"(?:'s)?\b")
    for t in tickers:
        if t and len(t) >= 2:
            pats.append(r'\b' + re.escape(t) + r'\b')
    for p in pats:
        text = re.sub(p, 'the Company', text, flags=re.I)
    return text


def prep():
    import retro_build_readlist as R
    os.makedirs(DIR, exist_ok=True)
    os.makedirs(SCR, exist_ok=True)
    q, delisted, surv, surv_read, t2r, sp = population()
    cal = calib_sample(surv_read)
    items = [('delisted', r) for r in delisted] + [('calib', t2r[t]) for t in cal]
    key, miss = [], []
    for kind, r in items:
        cik = int(r['cik'])
        i = did(cik)
        fn = os.path.join(SCR, f'{i}.txt')
        try:
            f = R.pick(cik, CUTOFF)
        except Exception as e:
            f, err = None, str(e)
        if not f:
            miss.append({'cik': cik, 'name': r['name'], 'why': '2013-07-01以前の年次報告書が見つからない'})
            continue
        if not os.path.exists(fn) or os.path.getsize(fn) < 2000:
            for a in range(4):
                try:
                    raw = urllib.request.urlopen(urllib.request.Request(f['url'], headers=R.HD), timeout=120).read()
                    break
                except Exception:
                    time.sleep(3 * (a + 1))
            else:
                miss.append({'cik': cik, 'name': r['name'], 'why': '本文の取得に失敗'})
                continue
            txt = anonymize(to_text(raw), r['name'], [r.get('ticker_hist')] + list(r.get('cands') or []))
            open(fn, 'w', encoding='utf-8').write(txt)
            time.sleep(0.15)
        key.append({'id': i, 'cik': cik, 'name': r['name'], 'kind': kind, 'ticker': r.get('ticker_hist'),
                    'form': f['form'], 'filed': f['filed'], 'url': f['url'], 'chars': os.path.getsize(fn)})
    # 束: id の昇順（sha1 なので生き残りと上場廃止が混ざる）に12社ずつ
    key.sort(key=lambda x: x['id'])
    batches = [key[k:k + 12] for k in range(0, len(key), 12)]
    for b, grp in enumerate(batches, 1):
        json.dump([{'id': x['id'], 'file': os.path.join(SCR, x['id'] + '.txt'), 'form': x['form'], 'filed': x['filed']}
                   for x in grp], open(os.path.join(DIR, f'batch{b:02d}.json'), 'w'), ensure_ascii=False, indent=1)
    json.dump({'generated': time.strftime('%Y-%m-%d'), 'cutoff': CUTOFF, 'n': len(key),
               'n_delisted': sum(x['kind'] == 'delisted' for x in key), 'n_calib': sum(x['kind'] == 'calib' for x in key),
               'missing': miss, 'rows': key}, open(os.path.join(DIR, 'key.json'), 'w'), ensure_ascii=False, indent=1)
    print('本文', len(key), '（上場廃止', sum(x['kind'] == 'delisted' for x in key), '・較正', sum(x['kind'] == 'calib' for x in key), '）',
          '取れない', len(miss), '束', len(batches))
    for m in miss:
        print('  取れない:', m)


def quotes():
    """読み手が 70/85 を主張した引用を集め、採点者の束（引用と id だけ）にする"""
    items = []
    for fn in sorted(os.listdir(DIR)):
        if fn.startswith('read_') and fn.endswith('.json'):
            for r in json.load(open(os.path.join(DIR, fn))):
                if r.get('rung') in (70, 85, 100) and (r.get('quote') or '').strip():
                    qid = 'G' + hashlib.sha1(('g|' + r['id']).encode()).hexdigest()[:8]
                    items.append({'id': qid, 'quote': r['quote'].strip()})
    items.sort(key=lambda x: x['id'])
    json.dump(items, open(os.path.join(DIR, 'grade_items.json'), 'w'), ensure_ascii=False, indent=1)
    print('採点する引用', len(items))


def today_label_survivor(t, orig):
    """生き残りの今日の刻み: 元の50は50のまま。70/75/85 は再採点（2人が一致したもの・割れたら低い方）"""
    if orig not in (70, 75, 85):
        return 85 if orig == 100 else orig
    iid = 'Q' + hashlib.sha1(f'2013|{t}'.encode()).hexdigest()[:8]
    A, B = {}, {}
    for k in range(1, 9):
        for side, dst in (('A', A), ('B', B)):
            p = os.path.join(OUT, 'irr_regrade', f'graded_{side}{k}.json')
            if os.path.exists(p):
                for g in json.load(open(p)):
                    dst[g['id']] = g.get('rung')
    a, b = A.get(iid), B.get(iid)
    if a is None and b is None:
        return 70 if orig in (70, 75) else orig
    if a is None or b is None:
        return a if b is None else b
    return a if a == b else min(a, b)


def final():
    q, delisted, surv, surv_read, t2r, sp = population()
    key = {x['id']: x for x in L('gaps_delisted_irr/key.json')['rows']}
    reads = {}
    for fn in sorted(os.listdir(DIR)):
        if fn.startswith('read_') and fn.endswith('.json'):
            for r in json.load(open(os.path.join(DIR, fn))):
                reads[r['id']] = r
    gA = {g['id']: g.get('rung') for g in json.load(open(os.path.join(DIR, 'graded_A.json')))}
    gB = {g['id']: g.get('rung') for g in json.load(open(os.path.join(DIR, 'graded_B.json')))}

    def new_label(i):
        r = reads.get(i)
        if not r:
            return None
        if r.get('rung') not in (70, 85, 100):
            return 50
        qid = 'G' + hashlib.sha1(('g|' + i).encode()).hexdigest()[:8]
        a, b = gA.get(qid), gB.get(qid)
        if a is None or b is None:
            return None
        return a if a == b else min(a, b)

    # 較正: 生き残りの今日の刻み vs 同じ手順で読み直した刻み
    cal = []
    for i, x in key.items():
        if x['kind'] != 'calib':
            continue
        t = x['ticker']
        cal.append({'t': t, 'orig': surv_read.get(t), 'today': today_label_survivor(t, surv_read.get(t)), 'new': new_label(i)})
    agree = [c for c in cal if c['new'] is not None]
    hi_today = [c for c in agree if c['today'] >= 85]
    calib = {'n': len(agree), '一致率': round(sum(c['today'] == c['new'] for c in agree) / len(agree), 3) if agree else None,
             '今日85の社を85と読んだ': f"{sum(c['new'] >= 85 for c in hi_today)}/{len(hi_today)}",
             '今日50の社を70以上と読んだ': f"{sum(c['new'] >= 70 for c in agree if c['today'] == 50)}/{sum(c['today'] == 50 for c in agree)}",
             '行': cal}

    # 母集団: 生き残り（読んだ163社・重み 370/163）＋ 上場廃止（新しく読んだ社・重み1）
    w_s = len(surv) / len(surv_read)
    S = []
    for t, orig in surv_read.items():
        r = t2r[t]
        S.append({'t': t, 'kind': '生き残り', 'rung': today_label_survivor(t, orig), 'px': sp[r['cik']]['px_cagr'], 'w': w_s})
    D = []
    for i, x in key.items():
        if x['kind'] != 'delisted':
            continue
        lab = new_label(i)
        r = next(rr for rr in delisted if int(rr['cik']) == x['cik'])
        D.append({'name': x['name'], 'kind': '上場廃止', 'exit': r['exit_kind'], 'rung': lab, 'px': sp[r['cik']]['px_cagr'], 'w': 1.0,
                  'quote': (reads.get(i) or {}).get('quote')})

    def stats(rows, lo, hi_):
        g = [r for r in rows if r['rung'] is not None and lo <= r['rung'] <= hi_]
        W = sum(r['w'] for r in g)
        if not W:
            return {'n': 0}
        return {'n': len(g), '重みの合計': round(W, 1), 'P15': round(sum(r['w'] for r in g if r['px'] >= HURDLE) / W, 3),
                '恒久毀損': round(sum(r['w'] for r in g if r['px'] <= IMPAIR) / W, 3)}

    def lift(rows, lo):
        a, b = stats(rows, lo, 100), stats(rows, 50, 50)
        return None if not a.get('n') or not b.get('n') else round(a['P15'] - b['P15'], 3)
    res = {}
    for nm, rows in (('生き残りだけ', S), ('上場廃止を戻す', S + D)):
        res[nm] = {'50': stats(rows, 50, 50), '70': stats(rows, 70, 75), '85以上': stats(rows, 85, 100),
                   '70以上': stats(rows, 70, 100), 'lift_85以上−50': lift(rows, 85), 'lift_70以上−50': lift(rows, 70)}
    only_s, both = res['生き残りだけ']['lift_85以上−50'], res['上場廃止を戻す']['lift_85以上−50']
    n85 = res['上場廃止を戻す']['85以上']['n']
    if n85 < 8:
        verdict = '判定不能（85以上が8社未満）'
    elif both is None or only_s is None:
        verdict = '判定不能'
    elif both > 0 and both >= only_s / 2:
        verdict = '生存バイアスで作られた上乗せではない'
    elif both <= 0:
        verdict = '作られていた'
    else:
        verdict = '弱い'
    by_rung = {}
    for lab in (50, 70, 85):
        s_ = [r for r in S if r['rung'] is not None and (r['rung'] >= 85 if lab == 85 else r['rung'] == lab)]
        d_ = [r for r in D if r['rung'] is not None and (r['rung'] >= 85 if lab == 85 else r['rung'] == lab)]
        tot = sum(r['w'] for r in s_) + len(d_)
        by_rung[str(lab)] = {'上場廃止の割合（重み付き）': round(len(d_) / tot, 3) if tot else None, '上場廃止の社数': len(d_),
                             '上場廃止の内訳': {k: sum(1 for r in d_ if r['exit'] == k) for k in sorted({r['exit'] for r in d_})}}
    doc = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/gaps_delisted_irr.py', 'prereg': 'out/gaps7_prereg.json Q7_survivor（9c28f6c）',
           '判定': verdict, '結果': res, '刻みごとの上場廃止': by_rung, '較正（生き残りを同じ手順で読み直した）': calib,
           '上場廃止の社（85以上と70）': [dict(name=r['name'], exit=r['exit'], rung=r['rung'], px=round(r['px'], 3), quote=(r['quote'] or '')[:300])
                                  for r in sorted(D, key=lambda r: -(r['rung'] or 0)) if (r['rung'] or 0) >= 70],
           '読めなかった上場廃止': [r['name'] for r in D if r['rung'] is None],
           '注': '価格の年率は配当なし（secpx の px_cagr）。生き残りは読んだ163社を 370/163 で重み付け。2013年だけ'}
    json.dump(doc, open(os.path.join(OUT, 'gaps_delisted_irr.json'), 'w'), ensure_ascii=False, indent=1)
    print('判定', verdict)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    print('較正', {k: v for k, v in calib.items() if k != '行'})
    print('刻みごとの上場廃止', by_rung)


if __name__ == '__main__':
    {'prep': prep, 'quotes': quotes, 'final': final}[sys.argv[1] if len(sys.argv) > 1 else 'prep']()
