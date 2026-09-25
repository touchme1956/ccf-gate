#!/usr/bin/env python3
"""night/angles_read_ingest.py — A1/A2 の盲検読解の準備（--prepare）と取り込み（--ingest）

--prepare: _angles_data/excerpts/{T}.txt をランダムな番号 _angles_data/blind/{ID}.txt へ写し、
           対応表 _angles_data/blind_map.json（読み手には渡さない）と、班ごとの番号リストを作る。
--ingest : 読み手の納品 _angles_data/reads/batch_*.json を取り込み、
           ①100/70/50 の引用が抜粋に逐語で在るか（空白を畳んで照合）を検査し、引用の無い主張は null にする（事前登録どおり）
           ②『どの会社だと思うか』の答えを実際の社名・ティッカーと突き合わせて guess_ok を付ける（漏れの検査・判定には使わない）
           → out/angles_read.json（ティッカーつき）
"""
import glob, json, os, random, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(BASE, '_angles_data')
NB = 21  # 班の数（249社 → 1班12社前後）

def norm(s): return re.sub(r'\s+', ' ', re.sub(r'[“”"’‘\']', '', s or '')).strip().lower()

def prepare():
    ts = sorted(f[:-4] for f in os.listdir(os.path.join(D, 'excerpts')) if f.endswith('.txt'))
    rng = random.Random(20260927); ids = rng.sample(range(1000, 9999), len(ts))
    mp = {}; os.makedirs(os.path.join(D, 'blind'), exist_ok=True)
    for t, i in zip(ts, ids):
        mp[str(i)] = t
        open(os.path.join(D, 'blind', f'{i}.txt'), 'w').write(open(os.path.join(D, 'excerpts', t + '.txt')).read())
    order = list(mp); rng.shuffle(order)
    batches = [order[k::NB] for k in range(NB)]
    json.dump(mp, open(os.path.join(D, 'blind_map.json'), 'w'))
    json.dump(batches, open(os.path.join(D, 'blind_batches.json'), 'w'))
    print(len(mp), '社 →', NB, '班', [len(b) for b in batches])

def ingest():
    mp = json.load(open(os.path.join(D, 'blind_map.json')))
    sys.path.insert(0, os.path.join(BASE, 'night')); import angles_13f as a13
    cik = json.load(open(os.path.join(BASE, 'out', '_cik_tickers.json')))
    names = a13.names_by_cik()
    rows, bad = {}, []
    for f in sorted(glob.glob(os.path.join(D, 'reads', 'batch_*.json'))):
        for r in json.load(open(f)):
            i = str(r.get('id')); t = mp.get(i)
            if not t: bad.append(i); continue
            src = norm(open(os.path.join(D, 'blind', i + '.txt')).read())
            rec = {'id': i}
            for k in ('runway', 'capalloc'):
                v = r.get(k); q = r.get(k + '_quote') or ''
                ok = bool(q) and all(norm(part) in src for part in re.split(r'\s*(?:\.\.\.|…)\s*', q) if len(norm(part)) >= 15)
                if v in (100, 70, 50) and not ok and v != 70:
                    rec[k] = None; rec[k + '_voided'] = f'{v} だが引用が抜粋に逐語で無い（事前登録: 引用の無い主張は null）'
                else:
                    rec[k] = v if v in (100, 70, 50) else None
                rec[k + '_quote'] = q[:400]; rec[k + '_why'] = (r.get(k + '_why') or '')[:400]; rec[k + '_verbatim'] = ok
            g = norm(r.get('guess') or '')
            real = [norm(n) for n in names.get(int(cik[t]), set())] + [t.lower()] if t in cik else [t.lower()]
            rec['guess'] = r.get('guess'); rec['guess_ok'] = bool(g) and any(
                g == n or (len(g) >= 4 and (g in n or n.split()[0] == g.split()[0])) for n in real if n)
            rows[t] = rec
    out = dict(generated=__import__('datetime').date.today().isoformat(), tool='night/angles_read_ingest.py',
               prereg='out/angles4_prereg.json', n=len(rows), unknown_ids=bad,
               count={k: {str(v): sum(r.get(k) == v for r in rows.values()) for v in (100, 70, 50, None)} for k in ('runway', 'capalloc')},
               voided=sum(any(k.endswith('_voided') for k in r) for r in rows.values()),
               guess_ok=sum(r['guess_ok'] for r in rows.values()), rows=rows)
    json.dump(out, open(os.path.join(BASE, 'out', 'angles_read.json'), 'w'), ensure_ascii=False, indent=1)
    print({k: out[k] for k in ('n', 'count', 'voided', 'guess_ok', 'unknown_ids')})

if __name__ == '__main__':
    prepare() if '--prepare' in sys.argv else ingest()
