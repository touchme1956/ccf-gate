#!/usr/bin/env python3
"""night/etfcand_short.py — 記録10年未満の ETF の候補（2026-10-13・ユーザー「10年未満の候補に上がるやつは？」）

読むだけ。門・採点・配分（portfolio.json）には触れない。事前登録 out/etfcand_short_prereg.json（5ed1da1・測る前に固定）どおり。
etfcand（8e86a4b）で『W10 の120か月がそろわない』として外した471本を、短い窓で同じやり方で並べる。

  第1段  python3 night/etfcand_short.py stage1
         W5（2021-10〜2026-09・60か月）と W3（2023-10〜・36か月）で、今の形の NASDAQ100 から5を回した形の Δ を出し、
         今の本と同じ賭け → etfcand の家族の新しい器 → 新しい家族 の順に整理して、第2段へ送る家族を決める。3年に満たない本は印だけ
  第2段  python3 night/etfcand_short.py stage2
         etfcand.stage2 をそのまま使う（東証の本で経費率が分からなければ 0.5% と置く・事後の点検は回さない）
出力: out/etfcand_short.json

事前登録の追記（6fc89b6）と追記2（573a5bd）で、第1段を回した後・第2段の前に測り方を直した:
  時差      東証・名証の本と米国上場の本の相関は、重ならない四半期（3か月の複利）で測る。東証の月末の値は米国の前日の終値まで
            しか映さないので、同じ指数の双子でも月次の相関は 0.95 前後で頭打ちになる（2568.T 対 QQQ: 月次 0.949・四半期 0.992）
  分割の誤り 日次で1日に −30% 以下か +40% 以上動いた日の塊のうち、10営業日後も水準がずれたままのものの月は壊れた値の月
            （2644.T が 2024-10-09 に −49.1%・分割の記録なし）。一日だけの誤った値で水準が戻るもの（1489.T 2024-01-17 −96.6%）は数えない
"""
import datetime, json, math, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etfcand as E          # noqa: E402
import gaps_common as G      # noqa: E402

OUT = os.path.join(BASE, 'out', 'etfcand_short.json')
SRC = E.OUT
PREREG = 'out/etfcand_short_prereg.json（5ed1da1）'
W5 = (202110, 202609)
W3 = (202310, 202609)
WHY_SHORT = 'X3 W10 の120か月がそろわない'
SAME_IND = {'XLK', 'VGT', 'IXN', 'MGK', 'VONG', 'SPYG', 'VOOG', 'VUG', 'FTXL', 'VHT', 'IXJ'}   # etfcand で同じ賭けとした11本
C_MIN = 12                     # 3年に満たない本に印を付ける最低の月数
C_QMIN = 24                    # 3年に満たない本で、東証と米国上場の相関を四半期で測る最低の月数
DAY_LO, DAY_HI = -0.30, 0.40   # 1日の動きがこれを超えたら分割の誤り（実際の最大は日本株 −12.4%・中国株 +8.5% 程度）
log = E.log
r2 = E.r2


def jp_fallback():
    import nx_jpfunds_data as J
    return J.FALLBACK_FEE


def win_of(c):
    return E.months(*W5) if c['grp'] == 'A' else E.months(*W3)


def ten_years(first):
    return f'{first // 100 + 10}-{first % 100:02d}'


def qret(r, ks):
    """窓の月を先頭から3か月ずつ区切った重ならない四半期の複利のリターン"""
    out = []
    for i in range(0, len(ks) - 2, 3):
        v = 1.0
        for m in ks[i:i + 3]:
            v *= 1 + r[m]
        out.append(v - 1)
    return out


def xcorr(ra, ua, rb, ub, ks):
    """東証・名証と米国上場の組は四半期・同じ市場どうしは月次（事前登録の追記 6fc89b6）"""
    if ua != ub:
        return E.M.corr(qret(ra, ks), qret(rb, ks))
    return E.corr(ra, rb, ks)


def daily_bad(tickers):
    """日次で水準がずれたままの塊（分割の誤り）の月（W5 の中）。{ティッカー: {月: 水準のずれ%}}, {ティッカー: {日: 戻った塊の最初の動き%}}
    1日に −30% 以下か +40% 以上の日を、10営業日以内に続くものどうしで塊にし、塊の前日の終値と塊の最後の日の10営業日後の終値を比べる
    （事前登録の追記2 573a5bd）。水準が戻っていれば一日だけの誤った値で、月次の値には効かない"""
    from concurrent.futures import ThreadPoolExecutor
    lo, hi = W5[0] * 100 + 1, W5[1] * 100 + 31

    def one(y):
        try:
            r = E.M.yahoo(y, interval='1d')
        except Exception as e:  # noqa
            return y, None, None, str(e)[:120]
        ds = sorted(r)
        lv, v = [], 1.0
        for dd in ds:
            v *= 1 + r[dd]
            lv.append(v)
        flags = [i for i, dd in enumerate(ds) if lo <= dd <= hi and (r[dd] <= DAY_LO or r[dd] >= DAY_HI)]
        clusters = []
        for i in flags:
            if clusters and i - clusters[-1][-1] <= 10:
                clusters[-1].append(i)
            else:
                clusters.append([i])
        shift, gone = {}, {}
        for cl in clusters:
            p0 = lv[cl[0] - 1] if cl[0] > 0 else 1.0
            p1 = lv[min(cl[-1] + 10, len(lv) - 1)]
            x = p1 / p0 - 1
            if x <= DAY_LO or x >= DAY_HI:
                shift.setdefault(ds[cl[0]] // 100, round(100 * x, 1))
            else:
                gone[ds[cl[0]]] = round(100 * r[ds[cl[0]]], 1)
        return y, shift, gone, None
    res, transient, err = {}, {}, {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, (y, out, gone, e) in enumerate(ex.map(one, tickers)):
            if out is None:
                err[y] = e
            else:
                res[y] = out
                if gone:
                    transient[y] = gone
            if (i + 1) % 100 == 0:
                log(f'  日次 {i + 1}/{len(tickers)}')
    return res, transient, err


def stage1():
    t0 = time.time()
    src = json.load(open(SRC))
    x3 = [x for x in src['除外_X3'] if x['why'] == WHY_SHORT]
    assert len(x3) == 471, len(x3)
    nofetch = [dict(t=x['t'], 名前=x['nm'], 理由=x.get('err')) for x in src['除外_X3'] if x['why'] == 'X3 値段が取れない']
    fam_of_rep = {f['代表']: f for f in src['家族']}
    same_ind = {c['t'] for c in src['候補'] if c['同じ賭け']}
    assert same_ind == SAME_IND, same_ind
    src_short = {s['代表']: s for s in src['ショートリスト']}
    src_verdict = {v['代表']: v['判定']['まとめ'] for v in (src.get('stage2') or {}).get('判定', {}).values()}

    uni, _excl, nrows = E.load_universe()
    meta = {d['t']: d for d in uni}
    fxr = E.fx_monthly()

    # 今の本（etfcand.stage1 と同じ取り方）
    import csv, html, io
    meta_h = {}
    for r in csv.reader(io.StringIO(open(E.ETFD, 'rb').read().decode('utf-8-sig'))):
        if len(r) > 32 and r[3] in E.MKT_US and r[1] in E.HELD_REF:
            meta_h[r[1]] = dict(t=r[1], y=r[1], us=True, region=r[7], dy=E.num(r[19]), er=E.num(r[5]), nm=html.unescape(r[2]))
    assert set(meta_h) == set(E.HELD_REF)
    px_h, err_h = E.fetch([meta_h[t]['y'] for t in E.HELD_REF])
    assert not err_h, err_h
    H = {t: E.to_yen(meta_h[t], px_h[t], fxr)[0] for t in E.HELD_REF}
    k5, k3 = E.months(*W5), E.months(*W3)

    def shld(m):
        return H['SHLD'][m] if m >= E.SHLD_FROM else H['ITA'][m]
    base = {m: sum(E.BASE_W[t] * (shld(m) if t == 'SHLD' else H[t][m]) for t in E.BASE_W) / E.NET for m in k5}
    bst = {'W5': E.stats(base, k5), 'W3': E.stats(base, k3)}
    log('今の形 W5', {k: r2(v) for k, v in bst['W5'].items()}, ' W3', {k: r2(v) for k, v in bst['W3'].items()})

    # 値段（短い記録の本・etfcand の家族の代表・同じ賭けの11本）
    refs = sorted(set(fam_of_rep) | same_ind)
    need = [meta[x['t']] for x in x3] + [meta[t] for t in refs]
    log('値段を取る', len(need))
    px, perr = E.fetch(sorted({d['y'] for d in need}))
    ref = {}
    for t in refs:
        ry = E.to_yen(meta[t], px[meta[t]['y']], fxr)[0]
        miss = [m for m in k5 if m not in ry]
        assert not miss, f'家族の代表 {t} の月が欠ける {miss[:3]}'
        ref[t] = ry
    ref_us = {t: meta[t]['us'] for t in refs}
    log('日次の値段で分割の誤りを探す', len(need))
    dbad, dgone, derr = daily_bad(sorted({d['y'] for d in need}))
    ref_drop = {t: dbad[meta[t]['y']] for t in refs if dbad.get(meta[t]['y'])}
    assert 'GLD' not in ref_drop
    for t in ref_drop:
        del ref[t]
    log(f"  水準がずれたままの分割の誤りがある本 {sum(1 for v in dbad.values() if v)}（うち etfcand の代表 {len(ref_drop)}: {sorted(ref_drop)}）・"
        f"一日だけの誤った値（戻った）{len(dgone)}・日次が取れない {len(derr)}")
    gld = ref['GLD']

    # 組（A＝W5 もそろう・B＝W3 だけ・C＝3年に満たない）
    def bad(d, ry, ks):
        db = dbad.get(d['y']) or {}
        return [m for m in ks if ry[m] <= E.BROKEN_LO or ry[m] >= E.BROKEN_HI or m in db]

    def bad_txt(d, ry, ms):
        db = dbad.get(d['y']) or {}
        return ', '.join(f'{m} 月次 {100 * ry[m]:+.1f}%' + (f'（日次の水準のずれ {db[m]:+.1f}%）' if m in db else '') for m in ms[:4])
    cands, cgrp, nopx = [], [], []
    for x in x3:
        d = meta[x['t']]
        r = px.get(d['y'])
        if r is None:
            nopx.append(dict(t=d['t'], 名前=d['nm'], 理由=perr.get(d['y'])))
            continue
        ry, k, drag = E.to_yen(d, r, fxr)
        c = dict(d, ry=ry, tax_k=k, tax_drag=drag, first=min(ry) if ry else None, n=len(ry))
        grp, note = 'C', None
        if all(m in ry for m in k3):
            b3 = bad(d, ry, k3)
            if b3:
                note = '値段が壊れている（W3 に月次 −60% 以下か +100% 以上の月か、日次の水準が分割の誤りでずれた月）: ' + bad_txt(d, ry, b3)
            else:
                grp = 'B'
                if all(m in ry for m in k5):
                    b5 = bad(d, ry, k5)
                    if b5:
                        note = 'W5 の前の2年に壊れた値（W3 だけで並べる）: ' + bad_txt(d, ry, b5)
                    else:
                        grp = 'A'
        c['grp'], c['note'] = grp, note
        (cands if grp in ('A', 'B') else cgrp).append(c)
    log(f"組 A {sum(c['grp'] == 'A' for c in cands)}・B {sum(c['grp'] == 'B' for c in cands)}・C {len(cgrp)}・値段なし {len(nopx)}")

    # 同じ賭け → etfcand の家族の新しい器
    def cor(c, rb, ub, ks, q=True):
        return xcorr(c['ry'], c['us'], rb, ub, ks) if q else E.corr(c['ry'], rb, ks)

    def held_best(c, ks, q=True):
        best = None
        for h in E.HELD_REF:
            hk = [m for m in ks if m >= E.SHLD_FROM] if h == 'SHLD' else ks
            if len(hk) < C_MIN:
                continue
            v = cor(c, H[h], True, hk, q)
            if best is None or v > best[1]:
                best = (h, v)
        return best

    def ref_best(c, ks):
        best = None
        for t, ry in ref.items():
            v = cor(c, ry, ref_us[t], ks)
            if best is None or v > best[1]:
                best = (t, v)
        return best
    for c in cands:
        ks = win_of(c)
        c['held_corr'] = held_best(c, ks)
        c['same_bet'] = c['held_corr'][1] >= E.SAME_BET
        c['exist'] = None
        if not c['same_bet']:
            t, v = ref_best(c, ks)
            c['ref_corr'] = (t, v)
            if v >= E.FAMILY:
                c['exist'] = t

    # Δ（候補の形 − 今の形）
    for c in cands:
        for wn, ks in (('W5', k5), ('W3', k3)):
            if wn == 'W5' and c['grp'] != 'A':
                continue
            fr = {m: base[m] + E.SLOT / E.NET * (c['ry'][m] - H['QQQ'][m]) for m in ks}
            st, so = E.stats(fr, ks), E.stats(c['ry'], ks)
            c[wn] = dict(form=st, own=so, d={k: (st[k] - bst[wn][k]) if st[k] is not None else None for k in st})

    # 新しい家族（W3 の相関 ≥0.95・etfcand と同じ順）
    usdjpy = G.fred('DEXJPUS')
    fx_now = usdjpy[max(k for k in usdjpy if k <= W5[1])]

    def aum_usd(c):
        a = c['aum'] or 0.0
        return a / fx_now if c['aum_unit'] == '百万円' else a
    live = [c for c in cands if not c['same_bet'] and not c['exist']]
    live.sort(key=lambda c: (c['first'], c['er'] if c['er'] is not None else 9e9, -aum_usd(c)))
    fams = []
    for c in live:
        hit = next((f for f in fams if cor(c, f['rep']['ry'], f['rep']['us'], k3) >= E.FAMILY), None)
        if hit:
            hit['members'].append(c)
            c['family'] = hit['id']
        else:
            f = dict(id=1001 + len(fams), rep=c, members=[c])
            fams.append(f)
            c['family'] = f['id']
    fid = {f['id']: f for f in fams}
    log(f"同じ賭け {sum(c['same_bet'] for c in cands)}・etfcand の家族の新しい器 {sum(bool(c['exist']) for c in cands)}・"
        f"新しい賭け {len(live)} → 家族 {len(fams)}")

    # ショートリスト
    def is_gold(f):
        return f['rep']['cls'] != '株式' and cor(f['rep'], gld, True, k3) >= 0.95
    elig = [f for f in fams if f['rep']['cls'] == '株式' or is_gold(f)]
    lists = {}
    for wn in ('W5', 'W3'):
        pool = [f for f in elig if wn in f['rep']]
        for mt, key in (('Δ年率', 'cagr'), ('Δ最大下落', 'mdd'), ('Δ効率', 'eff')):
            top = sorted(pool, key=lambda f: -f['rep'][wn]['d'][key])[:E.TOPK]
            lists[f'{wn} {mt}'] = [f['id'] for f in top]
    short = {}
    for ln, ids in lists.items():
        for i in ids:
            short.setdefault(i, []).append(ln)
    log(f'ショートリスト {len(short)} 家族')
    for i, why in sorted(short.items()):
        rp = fid[i]['rep']
        w = rp.get('W5') or rp['W3']
        log(f"  #{i} {rp['t']:8} {rp['nm'][:44]:44} {rp['grp']} 家族{len(fid[i]['members']):2d}本 "
            f"{'W5' if 'W5' in rp else 'W3'} Δ年率 {r2(w['d']['cagr']):+6.2f} Δ下落 {r2(w['d']['mdd']):+6.2f} Δ効率 {w['d']['eff']:+.4f} ← {', '.join(why)}")

    # C（3年に満たない本）の印
    short_reps = {f['rep']['t']: f for f in fams}
    c_rows = []
    pool_us = dict(ref_us)
    pool_us.update({t: f['rep']['us'] for t, f in short_reps.items()})
    for c in cgrp:
        ks = []
        for m in reversed(E.months(*W3)):          # 9月から遡って続いている月だけ（四半期の区切りが抜けをまたがない）
            if m not in c['ry']:
                break
            ks.insert(0, m)
        o = dict(t=c['t'], 名前=c['nm'], 日本語名=c['ja'], 市場=c['mkt'], 資産=c['cls'], 地域=c['region'], 経費率=c['er'],
                 最初の月=c['first'], 月数=c['n'], W3の中の続いた月数=len(ks))
        q = len(ks) >= C_QMIN
        if c['note']:
            o['印'] = c['note']
        elif len(ks) < C_MIN or bad(c, c['ry'], ks):
            o['印'] = '月が足りない（12か月未満）' if len(ks) < C_MIN else '値段が壊れている月がある: ' + bad_txt(c, c['ry'], bad(c, c['ry'], ks))
        else:
            if not q and not c['us']:
                o['注'] = '24か月に満たないので月次で測った（東証と米国上場の双子でも時差で 0.95 に届かないことがある）'
            h = held_best(c, ks, q)
            o['今の本との相関の最大'] = {'本': h[0], '相関': round(h[1], 3)}
            if h[1] >= E.SAME_BET:
                o['印'] = f'同じ賭け（{h[0]}）'
            else:
                pool = dict(ref)
                pool.update({t: f['rep']['ry'] for t, f in short_reps.items()})
                best = max(((t, cor(c, ry, pool_us[t], ks, q)) for t, ry in pool.items() if all(m in ry for m in ks)), key=lambda kv: kv[1])
                o['いちばん近い本'] = {'本': best[0], '相関': round(best[1], 3)}
                if best[1] >= E.FAMILY:
                    if best[0] in SAME_IND:
                        o['印'] = f'同じ賭け（間接・{best[0]}）'
                    elif best[0] in fam_of_rep:
                        o['印'] = f"etfcand の家族 #{fam_of_rep[best[0]]['id']}（{best[0]}）の新しい器"
                    else:
                        o['印'] = f"短い記録の家族 #{short_reps[best[0]]['id']}（{best[0]}）の仲間"
                else:
                    o['印'] = '新しい賭け（判定できない）'
        c_rows.append(o)

    # 参考: etfcand のショートリストの代表を同じ短い窓で
    ref_long = {}
    for t, s in src_short.items():
        o = {'etfcand の家族': s['家族'], 'etfcand のまとめ': src_verdict.get(t)}
        for wn, ks in (('W5', k5), ('W3', k3)):
            fr = {m: base[m] + E.SLOT / E.NET * (ref[t][m] - H['QQQ'][m]) for m in ks}
            st = E.stats(fr, ks)
            dd = {k: st[k] - bst[wn][k] for k in st}
            pool = [f for f in elig if wn in f['rep']]
            o[wn] = {'Δ': {k: (r2(v) if k != 'eff' else round(v, 4)) for k, v in dd.items()},
                     '短い記録の並びに入れたら何位': {mt: 1 + sum(f['rep'][wn]['d'][key] > dd[key] for f in pool)
                                           for mt, key in (('Δ年率', 'cagr'), ('Δ最大下落', 'mdd'), ('Δ効率', 'eff'))},
                     '並びの本数': len(pool)}
        ref_long[t] = o

    def fmt(x):
        return {k: (r2(v) if k != 'eff' else (round(v, 4) if v is not None else None)) for k, v in x.items()}

    def row(c):
        o = dict(t=c['t'], 名前=c['nm'], 日本語名=c['ja'], 市場=c['mkt'], 資産=c['cls'], 地域=c['region'], 指数=c['idx'],
                 経費率=c['er'], 配当利回り=c['dy'], 純資産=c['aum'], 純資産の単位=c['aum_unit'], 設定日=c['inception'],
                 最初の月=c['first'], 組=c['grp'], 記録が10年になる月=ten_years(c['first']), 外国税の目減り=r2(c['tax_drag'], 3),
                 今の本との相関の最大={'本': c['held_corr'][0], '相関': round(c['held_corr'][1], 3)}, 同じ賭け=c['same_bet'])
        if c.get('note'):
            o['注'] = c['note']
        if c.get('ref_corr'):
            o['etfcand の本でいちばん近い'] = {'本': c['ref_corr'][0], '相関': round(c['ref_corr'][1], 3)}
        if c['exist']:
            o['既にある家族'] = (f"同じ賭け（間接・{c['exist']}）" if c['exist'] in SAME_IND
                            else f"etfcand の家族 #{fam_of_rep[c['exist']]['id']}（{c['exist']}）")
        if c.get('family'):
            o['家族'] = c['family']
        for wn in ('W5', 'W3'):
            if wn in c:
                o[wn] = {'形': fmt(c[wn]['form']), '単体': fmt(c[wn]['own']), 'Δ': fmt(c[wn]['d'])}
        return o
    vehicles = []
    for c in cands:
        if c['exist'] and c['exist'] not in SAME_IND:
            f = fam_of_rep[c['exist']]
            vehicles.append(dict(t=c['t'], 名前=c['nm'], 市場=c['mkt'], 経費率=c['er'], 純資産=c['aum'], 純資産の単位=c['aum_unit'],
                                 最初の月=c['first'], 家族=f['id'], 家族の代表=c['exist'], 相関=round(c['ref_corr'][1], 3),
                                 etfcand_のショートリスト=c['exist'] in src_short, etfcand_のまとめ=src_verdict.get(c['exist'])))
    vehicles.sort(key=lambda v: (v['家族'], v['経費率'] if v['経費率'] is not None else 9e9))
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/etfcand_short.py', prereg=PREREG, stage=1,
               母集団=dict(元='out/etfcand.json の 除外_X3（W10 の120か月がそろわない）', 本数=len(x3), A=sum(c['grp'] == 'A' for c in cands),
                         B=sum(c['grp'] == 'B' for c in cands), C=len(cgrp), 値段が取れない=len(nopx),
                         同じ賭け=sum(c['same_bet'] for c in cands), 既にある家族の新しい器=sum(bool(c['exist']) for c in cands),
                         新しい賭け=len(live), 新しい家族=len(fams)),
               今の形={'重み（全体の%）': E.BASE_W, 'SHLD': 'SHLD の 2023-09 までは ITA で代える', 'W5': fmt(bst['W5']), 'W3': fmt(bst['W3'])},
               窓=dict(W5=f'{W5[0]}〜{W5[1]}', W3=f'{W3[0]}〜{W3[1]}'),
               候補=[row(c) for c in sorted(cands, key=lambda c: -c['W3']['d']['cagr'])],
               家族=[dict(id=f['id'], 代表=f['rep']['t'], 代表の名前=f['rep']['nm'], 資産=f['rep']['cls'], 組=f['rep']['grp'],
                          本=[m['t'] for m in f['members']], 金の現物=is_gold(f) if f['rep']['cls'] != '株式' else False) for f in fams],
               並び=lists,
               ショートリスト=[dict(家族=i, 代表=fid[i]['rep']['t'], 名前=fid[i]['rep']['nm'], 組=fid[i]['rep']['grp'], 入った並び=why,
                                   本=[m['t'] for m in fid[i]['members']]) for i, why in sorted(short.items())],
               既にある家族の新しい器=vehicles,
               C_3年に満たない本=c_rows, 値段が取れない=nofetch + nopx,
               日次の分割の誤り={'線': f'1日 {100 * DAY_LO:.0f}% 以下か +{100 * DAY_HI:.0f}% 以上の日の塊で、10営業日後も水準が同じだけずれたまま（W5 の中・追記2 573a5bd）',
                            '本（月: 水準のずれ%）': {y: v for y, v in sorted(dbad.items()) if v},
                            '当てはめの相手から外した etfcand の代表': ref_drop,
                            '一日だけの誤った値（水準が戻った・数えない）': dgone, '日次が取れない': derr},
               時差='東証・名証と米国上場の組の相関は重ならない四半期（3か月の複利）で測った（事前登録の追記 6fc89b6）',
               参考_etfcandのショートリストを同じ短い窓で=ref_long, secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    log('→', OUT, f'（{doc["secs"]}秒）')
    return doc


def stage2():
    d1 = json.load(open(OUT))
    gdx = json.load(open(SRC))['stage2']['判定']
    gdx = next(v for v in gdx.values() if v['代表'] == 'GDX')['判定']['感度ごと']['main']['Δ']
    doc = E.stage2(src=OUT, posthoc_on=False, jp_fallback_er=jp_fallback())
    res = doc['stage2']['判定']
    first = {c['t']: c['最初の月'] for c in d1['候補']}
    firm = sorted([r for r in res.values() if r['判定']['まとめ'] == '堅い価値あり'],
                  key=lambda r: (-r['判定']['感度ごと']['main']['Δ']['平均'], -r['判定']['感度ごと']['main']['Δ']['最悪']))
    if firm:
        items = []
        for r in firm:
            dd = r['判定']['感度ごと']['main']['Δ']
            side = '上' if (dd['平均'], dd['最悪']) > (gdx['平均'], gdx['最悪']) else '下'
            items.append(f"{r['代表']}（家族 #{r['家族']}・Δ平均 {dd['平均']:+.2f}・Δ最悪 {dd['最悪']:+.2f}・GDX より{side}・"
                         f"再検定 {ten_years(first[r['代表']])}）")
        concl = ('『堅い価値あり』' + str(len(firm)) + '家族: ' + '／'.join(items) +
                 '。記録10年未満なので決まりでは配分に足さない（etfcand の母集団の決まりの外）。GDX の勧めは変えない')
    else:
        concl = '『堅い価値あり』の短い記録の家族は無い＝短い記録の本から上に来るものは無い。GDX の勧めは変えない'
    doc['stage2']['結論'] = concl
    doc['stage2']['GDX（etfcand・主のΔ）'] = gdx
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    log('結論（etfcand_short の決まり）:', concl)
    return doc


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'stage1'
    if cmd == 'stage1':
        stage1()
    elif cmd == 'stage2':
        stage2()
    else:
        raise SystemExit(f'不明な指示: {cmd}')
