#!/usr/bin/env python3
"""歴史の読解が残した「引用」を、今日の規約(v9.9.144)で採点し直す測定器（2026-09-19 新設）。

★この器は判定を持たない。買付の線も刻みの定義も変えない（絶対のルール1）。
  出すのは「今日の規約で絞った70の lift が動くか」の実測と、その値札だけ。

なぜ要るか——2026-09-19 の lift 監査が出した数字は **歴史の読解ラベル** で測ったものだが、
  歴史の70と今日の70の一致率は **38%** しかない（v9.9.144 で70を「残余」から
  「積極的な主張」へ改め、2026-08-20 の全数二重読みで 163社が70→50へ落ちたため）。
  ＝「irr=70 は効かない(+0.071)」は **今日の門が70と呼ぶ社についての結論ではない**。
  同時に「今日の70は効く」という証拠もどこにも無い。ここに白黒をつける。

⚠ これは「引用が今日の規約を満たすか」の測定であって、「その社が今日の規約で70になるか」
  ではない。**引用に無い＝原本に無い、ではない**（今日の二重読みは原本を読む）。
  歴史の読解は旧規約の下で「移行摩擦の証拠」として引用を採っているので近い代理にはなるが、
  同じものではない。この非対称は結論の読み方に必ず添えること。

⚠ 非対称がもう一つある。50 の引用は「50である証拠」として採られているので、
  **50→70 の昇格は原理的に測れない。測れるのは 70→50 の降格だけ。**
  そしてその向きは、今日の是正の向き（212社中163社が降格）とちょうど一致する。

使い方:
  python3 night/irr70_regrade.py --reach            到達可能性と検出力（★結果を見る前に）
  python3 night/irr70_regrade.py --sheet            盲検の採点シートを出す
  python3 night/irr70_regrade.py --grade <json>     採点結果を読んで lift を測る
"""
import json, os, re, sys, random, statistics as st
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import irr_rung_audit as A          # 土台は再実装しない（v9.9.65）

B = A.B
SEED = 20260919
HURDLE = A.HURDLE

# 歴史の「中段」の刻み。2018 だけ 75（70 が無い）。
MID = {'2013': 70, '2015': 70, '2018': 75}
CAL_N = 60                          # 較正に混ぜる irr=50 の件数（seed 固定）

def rows_with_quote():
    """全ビンテージの読解を、引用つきで読む。irr_rung_audit.build() と同じ集合・同じ作法。"""
    SEMI = A.semi_map()
    out = []
    for v, files in A.SRC.items():
        ret = {r['ticker']: r for r in A.L(A.RET[v])['rows'] if r.get('tr_cagr') is not None}
        seen = {}
        for fn, key, tk in files:
            qk = 'irr_quote' if key == 'irr18' else 'quote'
            for r in A.L(fn)['rows']:
                if r.get(key) is None: continue
                seen[r[tk]] = (r, key, qk)
        for t, (r, key, qk) in seen.items():
            x = ret.get(t)
            if not x: continue
            hit, sic, sdesc = SEMI.get(t, (False, '', ''))
            out.append(dict(v=v, t=t, irr=r[key], quote=(r.get(qk) or ''),
                            cagr=x['tr_cagr'], years=x['years'], semi=hit,
                            sic=sic, sicDesc=sdesc, m5=r.get('moat5')))
    return out

def per_company(rs):
    """社単位へ寄せる。同じ社が複数ビンテージに出るときは **最新ビンテージ**を採る
    （irr_rung_audit.agreement() と同じ作法）。⚠のべで数えると両端の社が二重に効く。"""
    out = {}
    for r in sorted(rs, key=lambda r: r['v']): out[r['t']] = r
    return list(out.values())

def redact(text, ticker):
    """ティッカーを伏せる。⚠完全な盲検ではない——引用に社名が残ることがある。"""
    if not text: return ''
    return re.sub(r'\b' + re.escape(ticker) + r'\b', '[T]', text, flags=re.I)

def sheet():
    rs = rows_with_quote()
    mid = [r for r in rs if r['irr'] == MID[r['v']]]
    fifty = [r for r in rs if r['irr'] == 50]
    rnd = random.Random(SEED)
    cal = rnd.sample(fifty, min(CAL_N, len(fifty)))
    pool = mid + cal
    rnd.shuffle(pool)
    items, key = [], {}
    for i, r in enumerate(pool, 1):
        qid = 'Q%04d' % i
        key[qid] = dict(v=r['v'], t=r['t'], irr=r['irr'])
        items.append(dict(id=qid, quote=redact(r['quote'], r['t'])))
    return dict(generated=A.__dict__.get('TODAY', '2026-09-19'),
                note='盲検の採点シート。中段(70/75)の全行＋irr=50の較正サンプル。順はシャッフル・ティッカーは伏せてある。',
                n=len(items), n_mid=len(mid), n_cal=len(cal), items=items), key

def reach(rs_mid, rs_all):
    """★結果を見る前に出すもの。
       (a)神の規則の天井: 前方リターンを完全に知って k 社を採ったときの lift の上限
       (b)検出力: keep70 が k 社になったとき Δ を p<0.05 で拾える確率
       ⚠(a)が線に届かない k では、どんな規約で絞っても合格しえない（v1/v3/v11/v12 で4回踏んだ型）。"""
    n = len(rs_all)
    win = [1 if r['cagr'] >= HURDLE else 0 for r in rs_all]
    order = sorted(range(n), key=lambda i: -rs_all[i]['cagr'])
    god, nulls = {}, {}
    rnd = random.Random(SEED)
    for k in (5, 8, 10, 15, 20, 25, 30, 40, 51):
        if k >= n: continue
        god[k] = round(A.lift_of(win, order[:k], n), 3)
        idx = list(range(n)); sm = []
        for _ in range(2000):
            rnd.shuffle(idx); sm.append(A.lift_of(win, idx[:k], n))
        sm.sort(); nulls[k] = round(sm[int(.95*2000)], 3)
    pw = {}
    for k in (8, 10, 15, 20, 25, 30):
        if k >= n: continue
        pw[k] = A.power(rs_all, k, [0.10, 0.15, 0.20, 0.30], B=300, BB=200)
    return dict(pool_n=n, mid_n=len(rs_mid),
                base_p15=round(sum(win)/n, 3),
                god_ceiling=god, family_null_p95=nulls, power=pw,
                note='god_ceiling は後知恵で上位k社を採った lift。family_null_p95 は同じ k の群を'
                     '無作為に作ったときの95%点。前者が後者に届かない k では、どんな規約でも合格しえない。')

def grade(path):
    with open(path) as f: g = json.load(f)
    verdict = {x['id']: x['verdict'] for x in g['items']}
    with open(os.path.join(B, 'irr70_regrade_map.json')) as f: key = json.load(f)['key']
    rs = rows_with_quote()
    by = {(r['v'], r['t']): r for r in rs}
    for qid, k in key.items():
        r = by.get((k['v'], k['t']))
        if r is not None: r['verdict'] = verdict.get(qid)
    rs_c = per_company(rs)                      # ★主判定は社単位
    mid = [r for r in rs_c if r['irr'] == MID[r['v']]]
    cal = [r for r in rs if r['irr'] == 50 and r.get('verdict')]   # 較正は採点した行そのもの（のべ）
    # ── 較正: 50 の側で keep70 が何割出るか ───────────────
    cc = Counter(r['verdict'] for r in cal)
    cal_rate = cc['keep70'] / len(cal) if cal else None
    # ── 主判定 ────────────────────────────────────────
    pool = [r for r in rs_c if r['irr'] in (50, MID[r['v']])]    # 50 と 中段 だけ・社単位
    def mk(pred): return A.value_tag(pool, pred, B_perm=2000, B_boot=2000)
    res = dict(
        calib=dict(n=len(cal), dist=dict(cc), keep70_rate=round(cal_rate, 3) if cal_rate is not None else None,
                   line=0.15, ok=(cal_rate is not None and cal_rate < 0.15)),
        mid_dist=dict(Counter(r.get('verdict') for r in mid)),
        pool_n=len(pool),
        orig70=mk(lambda r: r['irr'] == MID[r['v']]),
        keep70=mk(lambda r: r['irr'] == MID[r['v']] and r.get('verdict') == 'keep70'),
        demote=mk(lambda r: r['irr'] == MID[r['v']] and r.get('verdict') == 'demote50'),
    )
    # 半導体を外した対照
    ns = [r for r in pool if not r['semi']]
    res['nonsemi'] = dict(
        pool_n=len(ns),
        orig70=A.value_tag(ns, lambda r: r['irr'] == MID[r['v']]),
        keep70=A.value_tag(ns, lambda r: r['irr'] == MID[r['v']] and r.get('verdict') == 'keep70'))
    # 群の素の実測
    res['groups'] = {k: A.stats([r for r in mid if r.get('verdict') == k])
                     for k in ('keep70', 'demote50', 'unclear')}
    res['groups']['irr50_all'] = A.stats([r for r in rs_c if r['irr'] == 50])
    # のべ（参考・主判定ではない）
    pool_r = [r for r in rs if r['irr'] in (50, MID[r['v']])]
    res['rowlevel'] = dict(
        pool_n=len(pool_r),
        orig70=A.value_tag(pool_r, lambda r: r['irr'] == MID[r['v']]),
        keep70=A.value_tag(pool_r, lambda r: r['irr'] == MID[r['v']] and r.get('verdict') == 'keep70'))
    # ── ビンテージ別（★事前登録の外＝結果を見た後に足した診断）────────
    #    窓の長さが 13.09/11.10/8.09年 と違うので P(15%+) のベース率が違う。
    #    束ねた数字が一つの年に支配されていないかを見るためだけに出す。
    res['by_vintage'] = {}
    for v in sorted(MID):
        pv = [r for r in rs_c if r['v'] == v and r['irr'] in (50, MID[v])]
        if not pv: continue
        f = lambda pred: A.value_tag(pv, pred, B_perm=2000, B_boot=2000)
        res['by_vintage'][v] = dict(
            pool_n=len(pv), years=round(pv[0]['years'], 2), base=A.stats(pv)['p15'],
            orig70=f(lambda r: r['irr'] == MID[v]),
            keep70=f(lambda r: r['irr'] == MID[v] and r.get('verdict') == 'keep70'),
            demote=f(lambda r: r['irr'] == MID[v] and r.get('verdict') == 'demote50'))
    res['rows'] = [dict(v=r['v'], t=r['t'], irr=r['irr'], verdict=r.get('verdict'),
                        cagr=round(r['cagr'], 4), semi=r['semi']) for r in mid]
    return res

if __name__ == '__main__':
    args = sys.argv[1:]
    if '--sheet' in args:
        s, key = sheet()
        with open(os.path.join(B, 'irr70_regrade_sheet.json'), 'w') as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
        with open(os.path.join(B, 'irr70_regrade_map.json'), 'w') as f:
            json.dump(dict(note='盲検の鍵。採点が終わるまで開かないこと。', key=key), f, ensure_ascii=False, indent=1)
        print('採点シート %d件（中段 %d / 較正 %d）→ out/irr70_regrade_sheet.json' % (s['n'], s['n_mid'], s['n_cal']))
    elif '--reach' in args:
        rs = per_company(rows_with_quote())
        pool = [r for r in rs if r['irr'] in (50, MID[r['v']])]
        mid = [r for r in pool if r['irr'] == MID[r['v']]]
        out = reach(mid, pool)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        with open(os.path.join(B, 'irr70_regrade_reach.json'), 'w') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    elif '--grade' in args:
        p = args[args.index('--grade') + 1]
        out = grade(p)
        with open(os.path.join(B, 'irr70_regrade.json'), 'w') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=1))
    else:
        print(__doc__)
