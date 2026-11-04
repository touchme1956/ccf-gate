#!/usr/bin/env python3
"""night/defense_swap_posthoc.py — defense_swap_check の①（1本の入れ替え216通り）の事後の確かめ（2026-11-04・判定に使わない）

決まり（defense_swap_check の頭）の「同等の幅」と物差しの選び方で答えが変わるかを、保存した差（out/defense_swap_check.json）から読み直す。
新しい計算はしない（差は小数3桁で保存されたもの）。見方: A 決まりどおり／B 同等の幅を2倍／C 実績の2つ（2000年〜の積立）を外す／
D 100年の2つを外す／E 実績と100年の4つを外す（未来の物差しと暴落の局面だけ）。
使い方: python3 night/defense_swap_posthoc.py → out/defense_swap_posthoc.json
"""
import json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from defense_swap_check import MEAS  # noqa: E402

SRC = os.path.join(BASE, 'out', 'defense_swap_check.json')
OUT = os.path.join(BASE, 'out', 'defense_swap_posthoc.json')
REAL = {'実績の20年積立で年15%以上', '実績の20年積立の年率の中央'}
CENT = {'100年の30年の中央', '100年の30年の最悪'}
VIEWS = {'A 決まりどおり': (1.0, set()), 'B 同等の幅を2倍': (2.0, set()), 'C 実績の2つを外す': (1.0, REAL),
         'D 100年の2つを外す': (1.0, CENT), 'E 実績と100年の4つを外す': (1.0, REAL | CENT)}


def cls_of(r, k, drop):
    worse, better = [], []
    for key, ja, side, sgn, tol in MEAS:
        if ja in drop:
            continue
        d = r['差'][ja]
        if d is None:
            continue
        t = tol * k
        if isinstance(d, dict):
            v = min(d.values())
            if v < -t:
                worse.append(ja)
            elif v > t:
                better.append((ja, side))
            continue
        if sgn * d < -t:
            worse.append(ja)
        elif sgn * d > t:
            better.append((ja, side))
    if worse:
        return '替えないほうがいい', worse, better
    rs, ds = any(s == 'ret' for _, s in better), any(s == 'def' for _, s in better)
    return ('良い' if rs and ds else '守りが厚くなる' if ds else '期待値が上がる' if rs else '同等'), worse, better


def main():
    d = json.load(open(SRC))
    out = dict(generated=d['generated'], tool='night/defense_swap_posthoc.py', kind='事後の確かめ（判定に使わない）', 見方={})
    for vn, (k, drop) in VIEWS.items():
        ok = []
        for r in d['入れ替え']:
            c, w, b = cls_of(r, k, drop)
            if c != '替えないほうがいい':
                ok.append(dict(名前=r['名前'], 元=r['元'], 量=r['量'], 先=r['先'], 分け方=c, 良い=[x for x, _ in b]))
        out['見方'][vn] = dict(替えないほうがいい以外の数=len(ok), 一覧=ok)
        print(vn, len(ok), [f"{x['元']}→{x['先']} {x['量']}（{x['分け方']}）" for x in ok])
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
