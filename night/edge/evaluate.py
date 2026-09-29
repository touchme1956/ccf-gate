#!/usr/bin/env python3
"""night/edge/evaluate.py — 凍結した規則を2001年以降（ホールドアウト）で一度だけ裁く（事前登録 out/edge_prereg.json どおり）

使い方: python3 night/edge/evaluate.py --round 1 [--only key1,key2]
  ・EDGE_PHASE=holdout を**この道具の中でだけ**立てる（選定の段の作業は 2000-12 までしか読めない）
  ・out/edge/spec_{key}.json（コミット済みのもの）を読み、fam_{key}.run(spec) を呼ぶ
  ・Holm は これまでに検定した全系統（out/edge/ledger.json・累積）で掛ける
出力: out/edge_results.json（全系統の最新の判定）・out/edge/ledger.json（検定の台帳・消さない）
"""
import os, sys
os.environ['EDGE_PHASE'] = 'holdout'
import argparse, importlib, json, math, statistics as S, subprocess, datetime, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as h                                            # noqa: E402

BASE = h.BASE
PRE = json.load(open(os.path.join(BASE, 'out', 'edge_prereg.json'), encoding='utf-8'))
LEDGER = os.path.join(BASE, 'out', 'edge', 'ledger.json')
OUT = os.path.join(BASE, 'out', 'edge_results.json')
MIN_EX, T_MIN, ALPHA, REPL_SHARE, REPL_T = 1.0, 2.0, 0.05, 0.6, 2.0


def committed(path):
    """spec が検定の前にコミットされているか（順番の証拠）→ コミットの sha と時刻"""
    try:
        r = subprocess.run(['git', '-C', BASE, 'log', '-1', '--format=%h %cI', '--', path], capture_output=True, text=True, timeout=30)
        dirty = subprocess.run(['git', '-C', BASE, 'status', '--porcelain', '--', path], capture_output=True, text=True, timeout=30).stdout.strip()
        return (r.stdout.strip() or None), (dirty == '')
    except Exception:
        return None, False


def pooled(markets):
    """市場をならした月次超過（費用後）の t。共通の月がそろわない市場もあるので、月ごとに取れる市場の平均"""
    per = {}
    for nm, x in markets.items():
        c = x.get('cost', 0.0) or 0.0
        tv = x.get('turnover') or {}
        for m in x['ret']:
            if m >= h.HOLD_START and m in x['bench']:
                per.setdefault(m, []).append(x['ret'][m] - tv.get(m, 0.0) * c - x['bench'][m])
    ex = [S.mean(v) for m, v in sorted(per.items())]
    if len(ex) < 24:
        return None, None
    mu, sd = S.mean(ex), S.stdev(ex)
    return round(mu * 1200, 2), round(mu / (sd / math.sqrt(len(ex))), 2) if sd > 0 else None


def judge_one(key, spec_doc):
    mod = importlib.import_module(f'fam_{key}')
    r = mod.run(spec_doc['spec'])
    tv, c = r.get('turnover'), r.get('cost', 0.0) or 0.0
    sel = h.stats(r['ret'], r['bench'], r.get('rf'), b=h.SEL_END, turnover=tv, cost=c)
    hold = h.stats(r['ret'], r['bench'], r.get('rf'), a=h.HOLD_START, turnover=tv, cost=c)
    mk = r.get('markets') or {}
    rep = {}
    for nm, x in mk.items():
        st = h.stats(x['ret'], x['bench'], x.get('rf'), a=h.HOLD_START, turnover=x.get('turnover'), cost=x.get('cost', 0.0) or 0.0)
        if st:
            rep[nm] = st
    pos = sum(1 for v in rep.values() if v['excess'] > 0)
    p_ex, p_t = pooled(mk) if mk else (None, None)
    out = {'key': key, 'name': getattr(mod, 'FAMILY', {}).get('name'), 'implement': getattr(mod, 'FAMILY', {}).get('implement'),
           'spec': spec_doc['spec'], 'n_variants': spec_doc.get('n_variants_tried'), 'selection': sel, 'holdout': hold,
           'replication': {'markets': rep, 'positive': f'{pos}/{len(rep)}' if rep else None,
                           'pooled_excess': p_ex, 'pooled_t': p_t} if mk else None}
    return out


def verdict(x, holm_pass):
    s, hd = x['selection'], x['holdout']
    c1 = bool(hd and hd['excess'] >= MIN_EX)
    c2 = bool(hd and hd['t'] is not None and hd['t'] >= T_MIN)
    c3 = bool(s and s['excess'] > 0)
    rp = x.get('replication')
    if rp and rp['markets']:
        n = len(rp['markets']); pos = int(rp['positive'].split('/')[0])
        c5 = pos / n >= REPL_SHARE and (rp['pooled_t'] or 0) >= REPL_T
    else:
        c5 = None                                            # 当てられない規則（再現の条件は掛からない）
    crit = {'1_ホールドアウトの超過≥+1%/年': c1, '2_t≥2': c2, '3_選定期間でも勝ち': c3, '4_Holm': holm_pass,
            '5_他の市場で再現': c5}
    if c1 and c2 and c3 and holm_pass and c5 is not False:
        v = '確かな勝ち'
    elif c1 and c2 and c3:
        v = '候補'
    else:
        v = '不合格'
    risk = None
    if hd:
        same = hd['vol'] <= hd['bench_vol'] * 1.1 and hd['maxdd'] >= hd['bench_maxdd'] - 5
        risk = '同じリスクで' if same else 'リスクを増やして'
    return crit, v, risk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--round', type=int, required=True)
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    specs = sorted(f for f in os.listdir(os.path.join(BASE, 'out', 'edge')) if f.startswith('spec_') and f.endswith('.json'))
    only = {k for k in a.only.split(',') if k}
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {'about': '検定した系統の台帳（累積・消さない）。Holm はここに載った全系統で掛ける', 'rows': {}}
    results = json.load(open(OUT)) if os.path.exists(OUT) else {}
    fam = results.get('families', {})
    for fn in specs:
        key = fn[5:-5]
        if only and key not in only:
            continue
        path = os.path.join(BASE, 'out', 'edge', fn)
        sha, clean = committed(path)
        if not sha or not clean:
            print(f'✗ {key}: spec がコミットされていない（または変更がある）— 検定しない'); continue
        doc = json.load(open(path, encoding='utf-8'))
        try:
            x = judge_one(key, doc)
        except Exception as e:
            print(f'✗ {key}: run が失敗 {e}'); traceback.print_exc(); continue
        x['spec_commit'] = sha
        x['round'] = led['rows'].get(key, {}).get('round', a.round)
        hd = x['holdout']
        led['rows'].setdefault(key, {'round': a.round, 'first_tested': datetime.date.today().isoformat(), 'spec_commit': sha})
        led['rows'][key]['p'] = h.pnorm_upper(hd['t']) if hd else 1.0
        fam[key] = x
    # Holm（累積の全系統）
    ps = sorted(((v['p'], k) for k, v in led['rows'].items()), key=lambda z: z[0])
    K = len(ps)
    holm, stop = {}, False
    for i, (p, k) in enumerate(ps):
        thr = ALPHA / (K - i)
        ok = (not stop) and p <= thr
        if not ok:
            stop = True
        holm[k] = {'p': p, 'thr': thr, 'pass': ok}
    for k, x in fam.items():
        hp = holm.get(k, {}).get('pass', False)
        x['holm'] = holm.get(k)
        x['criteria'], x['verdict'], x['risk'] = verdict(x, hp)
    results = {'generated': datetime.date.today().isoformat(), 'prereg': 'out/edge_prereg.json', 'K_cumulative': K,
               'families': fam}
    json.dump(results, open(OUT, 'w'), ensure_ascii=False, indent=1)
    json.dump(led, open(LEDGER, 'w'), ensure_ascii=False, indent=1)
    print(f'■ 累積 K={K}（Holm の最小の線 {ALPHA / K:.4f}）')
    for k, x in sorted(fam.items(), key=lambda kv: -(kv[1]['holdout'] or {}).get('t', -9) if kv[1]['holdout'] else 9):
        s, hd, rp = x['selection'] or {}, x['holdout'] or {}, x.get('replication') or {}
        print(f"{x['verdict']:5} {k:12} 選定 {s.get('excess')!s:>6}%(t{s.get('t')})  検定 {hd.get('cagr')}% vs {hd.get('bench_cagr')}% "
              f"超過 {hd.get('excess')!s:>6}%(t{hd.get('t')}, NW{hd.get('t_nw')})  ぶれ {hd.get('vol')}/{hd.get('bench_vol')} 最大下落 {hd.get('maxdd')}/{hd.get('bench_maxdd')}"
              f"  10年窓 {hd.get('roll10_win')}  再現 {rp.get('positive')} ならし {rp.get('pooled_excess')}(t{rp.get('pooled_t')})  {x.get('risk') or ''}")


if __name__ == '__main__':
    main()
