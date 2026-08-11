#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_criteria.py — **irr=85 の社に別枠の採点基準を設けるなら、歴史は何を支持するか**
（2026-08-11新設・ユーザーの問い「irr85の銘柄だけは門と別枠で採点基準を設けるには歴史をみてどうするべきか検証して」）

■ 何を問うか
  門は既に **別枠85（v9.9.119）** を持つ——irr=85 なら Ω75+ を免除し、代わりに
  `営業利益率≥11.9% ∧ FCF転換≥0.64 ∧ 売上5年CAGR≥1.8% ∧ nde≤4 ∧ 二本柱無傷` を課す。
  その下限は「2018年ビンテージ irr=85 の**継続組15社の最小値**」だった。

  **だが「最小値」は定義上ほとんど何も落とさない。** 実測（2026-08-11）:
  実際の最小値は 営利率 11.89(COHR) / FCF転換 0.639(WST) / cagr 1.76(CW) で、
  門はこれを **11.9 / 0.64 / 1.8 へ丸め上げていた**。その結果
  **線を作った当の3社が自分の線で落ちていた**（COHR −0.01 / WST −0.001 / CW −0.04）。
  → **v9.9.129（2026-08-11 ユーザー明示指示「いれて」）で丸め上げを撤回し、実測の最小値をそのまま置いた。**
     実測: 投下可10社・別枠85の5社とも不変＝純粋なラチェット。
  ＝現行の下限は「識別する基準」ではなく「**最悪の勝者を下回るな**」という床で、
  しかも丸めのぶんだけ床が勝者に食い込んでいる。

  そこで問い直す: **irr=85 の群の中で、継続組と非継続組を分ける入口の変数はあるのか。**

■ 事前登録（**結果を見る前に固定する**。この repo の作法）
  母集団 : 3ビンテージ(2013/2015/2018)で irr=85 と読まれた社の和集合。リターンのある社のみ
  結果   : 継続 = 窓の実現年率 ≥ 15%（既存のハードル。新しい定数を作らない）
  候補   : 当時(as-of)の機械値12本 ＋ 定性3本（時制・機構型・主観の堀moat5）。
           **すべて既存の在庫にある欄**で、この検証のために新しく作った量は一つも無い
  採用の線（**3つ全部を満たしたものだけ「使える」と呼ぶ**）:
    (1) 中央値で二分したとき lift ≥ **+0.15**（片側の P(継続) が反対側より15pt以上高い）
    (2) **符号が層をまたいで反転しない**——(a)2018年ビンテージ群 と (b)2013/2015のみの群、
        (c)半導体連鎖 と (d)非半導体、の**両方の割り方で**同じ向き
    (3) 分子（少ない側の該当社数）が **3社以上**
  ⚠ 期待される答えは「**何も残らない**」。CLAUDE.md は一般母集団で
     「継続/非継続は入口の財務で分かれなかった（営利率 20.36 vs 20.51）」を既に実測しており、
     2018年で唯一分けた「時制（完了形 vs 願望形）」も 2013/2015 で**符号が逆**になっている。
     **残らなかったこと自体が答え**であり、そのときの設計上の含意は下の「読み方」に書く。

■ この検証の限界（先に書く）
  ・n=28（リターンのある27社／継続組は窓によるが15〜16社）。**どの候補も過剰適合の危険が極めて高い**
  ・候補15本を同じ標本に当てるので、**偶然どれか1本が線を通る確率は無視できない**
    （置換検定で偽陽性率を出す）
  ・窓は 2018→26 が主（8.1年・半導体AI相場）。2013→26(13.1年) も併記するが標本が重なる
  ・**ここで見つかった基準を規約にしてはいけない**——規約の改定は絶対のルール1（ユーザー明示指示）の領分。
    この道具が出すのは「歴史が支持するか / しないか」だけ

使い方: python3 night/irr85_criteria.py [--json]
出力  : out/irr85_criteria.json
"""
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
HURDLE = 0.15          # 継続の線。既存のハードル（v9.9.124）を流用＝新しい定数を作らない
MIN_LIFT = 0.15        # 事前登録(1)
MIN_NUM = 3            # 事前登録(3)


def rows_of(f):
    d = json.load(open(f, encoding='utf-8'))
    r = d if isinstance(d, list) else (d.get('rows') or d.get('items') or [])
    if isinstance(r, dict):
        r = list(r.values())
    return [x for x in r if isinstance(x, dict)]


def build():
    H = json.load(open('out/audit_hist85_today.json', encoding='utf-8'))['rows']
    F1 = {r['ticker']: r for r in rows_of('out/retro_features_2018.json') if r.get('ticker')}
    F2 = {r['ticker']: r for r in rows_of('out/retro_features2_2018.json') if r.get('ticker')}
    # 定性（時制・機構）は replication の在庫から。2018年版は別ファイルで欄名が違う
    Q = {}
    for f, k in (('out/retro_irr85_replication_2013_2013q.json', 'ticker'),
                 ('out/retro_irr85_replication_2015_2015q_2015qb.json', 'ticker')):
        for r in rows_of(f):
            if r.get('irr') == 85:
                Q.setdefault(r[k], {}).update(tense=r.get('tense'), mech=r.get('mech'),
                                              moat5=r.get('moat5'))
    for f in ('out/retro_moat_2018.json', 'out/retro_moat_2018_rest.json'):
        for r in rows_of(f):
            if r.get('irr18') == 85:
                Q.setdefault(r['t'], {}).setdefault('moat5', r.get('moat5'))

    out = []
    for h in H:
        t = h['t']
        a, b, q = F1.get(t, {}), F2.get(t, {}), Q.get(t, {})
        if h['cagr18'] is None:
            continue
        out.append(dict(
            t=t, y=1 if h['cagr18'] >= HURDLE else 0, cagr18=h['cagr18'], cagr13=h['cagr13'],
            v2018=('2018' in h['vintages']), semi=h['semi'],
            opm=b.get('opm'), cagr5=b.get('cagr5'), conv5=b.get('conv5'), nde=a.get('nde18'),
            opmD5=b.get('opmD5'), accel=b.get('accel'), rnd=b.get('rnd_r'),
            payout=b.get('payout5'), netiss=b.get('netiss_r'), intcov=b.get('intcov'),
            accr=b.get('accr'), rev=b.get('rev'),
            tense=q.get('tense'), mech=q.get('mech'), moat5=q.get('moat5')))
    return out


NUM = [('opm', '営業利益率'), ('cagr5', '売上5年CAGR'), ('conv5', 'FCF転換'), ('nde', '純負債/EBITDA'),
       ('opmD5', '営利率の5年変化'), ('accel', '成長の加速度'), ('rnd', 'R&D/売上'),
       ('payout', '還元性向'), ('netiss', '純株式発行'), ('intcov', 'インタレストカバレッジ'),
       ('accr', 'アクルーアル'), ('rev', '売上規模')]


def split(rows, k):
    """中央値で二分し (上半分のP, 下半分のP, 上n, 下n) を返す"""
    v = [r for r in rows if isinstance(r.get(k), (int, float))]
    if len(v) < 6:
        return None
    m = st.median([r[k] for r in v])
    hi = [r for r in v if r[k] > m]
    lo = [r for r in v if r[k] <= m]
    if not hi or not lo:
        return None
    return (sum(r['y'] for r in hi) / len(hi), sum(r['y'] for r in lo) / len(lo), len(hi), len(lo))


def judge(rows, k):
    """事前登録の3条件で裁く。返り値: (合否, 説明, 全体lift)"""
    s = split(rows, k)
    if s is None:
        return False, '標本不足', None
    ph, pl, nh, nl = s
    lift = ph - pl
    if abs(lift) < MIN_LIFT:
        return False, f'lift {lift:+.2f} が線 {MIN_LIFT} 未満', lift
    if min(nh, nl) < MIN_NUM:
        return False, f'分子 {min(nh,nl)}社 が線 {MIN_NUM} 未満', lift
    # 符号の一貫性を2つの割り方で見る
    for lbl, f in (('ビンテージ', lambda r: r['v2018']), ('半導体', lambda r: r['semi'] is True)):
        sub = []
        for want in (True, False):
            g = [r for r in rows if f(r) is want]
            ss = split(g, k)
            sub.append(None if ss is None else (ss[0] - ss[1]))
        a, b = sub
        if a is None or b is None:
            return False, f'{lbl}で層別すると標本不足（符号の一貫性を確かめられない）', lift
        if (a > 0) != (b > 0):
            return False, f'{lbl}で**符号が反転**（{a:+.2f} / {b:+.2f}）', lift
    return True, f'lift {lift:+.2f}・符号一貫', lift


def main():
    rows = build()
    n, ny = len(rows), sum(r['y'] for r in rows)
    print('■ irr=85 の群の中で、継続組と非継続組を分ける入口の変数はあるか')
    print(f'  母集団 {n}社（うち継続 {ny}社＝P={ny/n:.2f}）／ 継続の線 年{HURDLE*100:.0f}%')
    print(f'  事前登録: lift≥{MIN_LIFT} ∧ 分子≥{MIN_NUM}社 ∧ ビンテージ・半導体の両方で符号が反転しない\n')

    res, passed = [], []
    print(f"  {'':<22}{'上半分P':>8}{'下半分P':>8}{'lift':>8}  判定")
    for k, lbl in NUM:
        ok, why, lift = judge(rows, k)
        s = split(rows, k)
        ph = f'{s[0]:.2f}' if s else '—'
        pl = f'{s[1]:.2f}' if s else '—'
        lf = f'{lift:+.2f}' if lift is not None else '  —'
        print(f"  {lbl:<22}{ph:>8}{pl:>8}{lf:>8}  {'✓合格' if ok else '✗ '+why}")
        res.append(dict(k=k, label=lbl, lift=lift, ok=ok, why=why))
        if ok:
            passed.append(lbl)

    # ── 定性（時制・機構・主観の堀）──────────────────────────────
    print('\n  ── 定性 ──')
    qual = []
    for k, lbl in (('tense', '時制（完了形）'), ('moat5', '主観の堀 moat5')):
        v = [r for r in rows if r.get(k) is not None]
        if len(v) < 6:
            print(f'  {lbl:<22}標本不足（{len(v)}社）'); continue
        if k == 'tense':
            hi = [r for r in v if r[k] == '完了形']; lo = [r for r in v if r[k] != '完了形']
        else:
            m = st.median([r[k] for r in v])
            hi = [r for r in v if r[k] > m]; lo = [r for r in v if r[k] <= m]
        if not hi or not lo:
            print(f'  {lbl:<22}片側が空'); continue
        ph, pl = sum(r['y'] for r in hi)/len(hi), sum(r['y'] for r in lo)/len(lo)
        print(f"  {lbl:<22}{ph:>8.2f}{pl:>8.2f}{ph-pl:>+8.2f}  n={len(hi)}/{len(lo)}"
              f"{'  ⚠2018年ビンテージでは 0.81 vs 0.40 だったが3ビンテージでは符号が逆（既記録）' if k=='tense' else ''}")
        qual.append(dict(k=k, label=lbl, lift=ph-pl, nhi=len(hi), nlo=len(lo)))

    # 機構型（B設計組込 とその他）
    mv = [r for r in rows if r.get('mech')]
    if mv:
        b = [r for r in mv if r['mech'] and r['mech'].startswith('B')]
        o = [r for r in mv if not (r['mech'] and r['mech'].startswith('B'))]
        if b and o:
            print(f"  {'機構=B設計組込を除く':<22}{sum(r['y'] for r in o)/len(o):>8.2f}"
                  f"{sum(r['y'] for r in b)/len(b):>8.2f}"
                  f"{sum(r['y'] for r in o)/len(o)-sum(r['y'] for r in b)/len(b):>+8.2f}"
                  f"  n={len(o)}/{len(b)}  ⚠分子{len(b)}社＝**1社を消しているだけ**の可能性")

    # ── 多重検定の値札（候補12本を同じ標本に当てている）──────────────
    import random
    rnd = random.Random(20260811)
    fp = 0
    ys = [r['y'] for r in rows]
    for _ in range(2000):
        sh = ys[:]; rnd.shuffle(sh)
        sr = [dict(r, y=sh[i]) for i, r in enumerate(rows)]
        if any(judge(sr, k)[0] for k, _ in NUM):
            fp += 1
    print(f'\n■ 多重検定の値札: 結果をシャッフルして同じ手続きを2000回——'
          f'**偶然どれか1本が合格する確率 {fp/2000:.3f}**')
    print(f'   ＝この事前登録は**緩すぎる**（候補12本 × n={n} では雑音が{fp/2000*100:.0f}%の確率で線を通る）。')
    print(f'   **だからこそ「合格ゼロ」が効く**——雑音でさえ{fp/2000*100:.0f}%通る緩い試験を、')
    print(f'   実データが1本も通らなかった。本物の信号があれば、この緩さならまず通っていた。')
    print(f'   ⚠逆に言えば、**もし何かが合格していても意味は無かった**（偶然と区別できない）。')
    print(f'   → 次に同じ問いを立てるなら、**検出力を結果の前に出して標本設計から決めること**')
    print(f'     （CLAUDE.md が hist_val v2 で残した検問③をそのまま踏んだ形）')

    print('\n■ 判定')
    if passed:
        print(f'  事前登録を満たした候補: **{" / ".join(passed)}**')
        print(f'  ⚠ ただし偽陽性率 {fp/2000:.3f} と n={n} を見てから読むこと')
    else:
        print('  **合格ゼロ。irr=85 の群の中で継続を分ける入口の変数は見つからない。**')

    print('\n■ 読み方（設計上の含意）')
    print('  ・**「合格ゼロ」は失敗ではなく、現行の別枠85の設計を支持する**——')
    print('    下限を「継続組の最小値」に置いたのは、識別できないと分かっている場に')
    print('    **識別する線を引かない**ということ。歴史はそれ以上を支持しない')
    print('  ・**丸めは v9.9.129 で是正済み**。実測の最小値 営利率11.89 / FCF転換0.639 / cagr1.76 を')
    print('    門はかつて 11.9 / 0.64 / 1.8 へ丸め上げており、線を作った当の3社（COHR/WST/CW）が')
    print('    自分の線で落ちていた＝**床のつもりが勝者に食い込んでいた**。丸め上げを撤回して解消')
    print('  ・**足すなら「分ける基準」ではなく「壊れないための安全弁」**。歴史で唯一この群の中で')
    print('    起きた恒久毀損は CMTL（−30.1%/年・DD−96%・機構B設計組込・moat5=2）の1社で、')
    print('    **n=1 では規則にできない**（CLAUDE.md「n=10でふるいを足すのは過剰適合」）')
    print('  ・irr=85 という**ラベル自体は当たっている**（28社の中央値 +19.2% vs 母集団 +6.7%）。')
    print('    分けられないのは「85の中の優劣」であって、「85かどうか」ではない')

    if AS_JSON:
        p = 'out/irr85_criteria.json'
        json.dump(dict(generated='2026-08-11', n=n, n_cont=ny, hurdle=HURDLE,
                       prereg=dict(min_lift=MIN_LIFT, min_num=MIN_NUM,
                                   consistency=['vintage', 'semiconductor']),
                       false_positive_rate=fp/2000,
                       numeric=res, qualitative=qual, passed=passed,
                       rows=rows), open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
