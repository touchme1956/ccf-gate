#!/usr/bin/env python3
"""night/edge/prefix_check.py — 先読みの機械検査（前の月の成績が、後のデータを足しても変わらないか）

考え方: 規則が月 m に使う情報は m−1 月末まで。ならば データを 1990-12 で切って走らせた成績と、2000-12 で切って走らせた成績は、
1990-12 までの月で**1ビットも違わない**はず。違えば、規則はどこかで後のデータを使っている（全期間の平均・百分位・ぶれで
標準化した・後の月の組入れを使った など）。選定の段のデータ（〜2000-12）の中だけで確かめるので、ホールドアウトは覗かない。
⚠ 同じ月の先読み（月 m の持ち高に月 m のリターンを使う）はこの検査では見えない——コードを読む検査で別に確かめる。

使い方: python3 night/edge/prefix_check.py key1 key2 …（無ければ out/edge/spec_*.json の全部）
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(HERE))
CUTS = (199012, 200012)

CODE = r'''
import json, os, sys
sys.path.insert(0, %r)
import importlib
key = sys.argv[1]
spec = json.load(open(os.path.join(%r, 'out', 'edge', 'spec_' + key + '.json')))['spec']
r = importlib.import_module('fam_' + key).run(spec)
out = {'ret': r['ret'], 'bench': r['bench']}
mk = r.get('markets') or {}
out['markets'] = {n: x['ret'] for n, x in mk.items()}
print(json.dumps(out))
''' % (HERE, BASE)


def run(key, cut):
    env = dict(os.environ, EDGE_PHASE='select', EDGE_SEL_END=str(cut))
    p = subprocess.run([sys.executable, '-c', CODE, key], capture_output=True, text=True, env=env, timeout=3600)
    if p.returncode:
        raise RuntimeError(p.stderr[-800:])
    return json.loads(p.stdout.strip().split('\n')[-1])


def diff(a, b, upto):
    bad, n = [], 0
    for m, v in a.items():
        mm = int(m)
        if mm > upto:
            continue
        n += 1
        w = b.get(m)
        if w is None or abs(v - w) > 1e-10:
            bad.append((mm, v, w))
    return n, bad


def main():
    keys = sys.argv[1:] or sorted(f[5:-5] for f in os.listdir(os.path.join(BASE, 'out', 'edge')) if f.startswith('spec_'))
    res = {}
    for k in keys:
        try:
            early, late = run(k, CUTS[0]), run(k, CUTS[1])
        except Exception as e:
            print(f'✗ {k}: 走らない {e}'); res[k] = {'ok': False, 'error': str(e)[-300:]}; continue
        n, bad = diff(early['ret'], late['ret'], CUTS[0])
        nb, badb = diff(early['bench'], late['bench'], CUTS[0])
        mb = {}
        for nm, s in (early.get('markets') or {}).items():
            _, bm = diff(s, (late.get('markets') or {}).get(nm, {}), CUTS[0])
            if bm:
                mb[nm] = len(bm)
        ok = not bad and not badb and not mb
        res[k] = {'ok': ok, 'months_compared': n, 'ret_diffs': len(bad), 'bench_diffs': len(badb), 'market_diffs': mb,
                  'first_diffs': [list(x) for x in bad[:5]]}
        print(('✓' if ok else '✗') + f' {k}: 1990-12 までの {n}か月 — 規則 {len(bad)}件・相手 {len(badb)}件・他の市場 {mb or 0} で食い違い'
              + (f'  例 {bad[:3]}' if bad else ''))
    os.makedirs(os.path.join(BASE, 'out', 'edge'), exist_ok=True)
    p = os.path.join(BASE, 'out', 'edge', 'prefix_check.json')
    old = json.load(open(p)) if os.path.exists(p) else {}
    old.update(res)
    json.dump(old, open(p, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
