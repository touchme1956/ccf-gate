#!/usr/bin/env python3
"""irr の刻みを、在庫の生データから数え直す測定器（2026-09-19 新設）。

★この器は判定を持たない。合否の線を引かない（引けば新しい規約になる＝絶対のルール1）。
  出すのは「刻み別の実測」「lift とその値札」「歴史の刻みと今日の刻みの一致率」だけ。

なぜ要るか——3つとも、既存の器が構造的に答えられない問いだから:
  (1) `retro_moat_durability.py` は **のべ**で群を出す（2013+2015のみ・2018は欄名が違うので不参加）。
      同じ社が複数ビンテージに出るので、両端（唯一の恒久毀損 CMTL と 最良 LRCX）が二重に数えられる。
      → こちらは **社単位**も出し、durability と同条件での照合も出す（二つが違うことを言わないため）。
  (2) **lift の値札**（帰無分布の95%点・置換p・CI・検出力）をどの器も出していなかった。
      lift が線に届かないことは「効果が無い」ではなく「この標本では見えない」かもしれない。
  (3) **歴史の刻みと今日の台帳の刻みが同じ社を指しているか**を誰も数えていなかった。
      v9.9.144(irr=70を「積極的な主張」へ)と2026-08-20の全数二重読みで定義が動いている。

⚠ 数字をこの器の外へ書き写さないこと。写した数字は必ず陳腐化する（base_rate_check が
  「n=10」を焼き付けて実際に陳腐化した）。引用するときは out/irr_rung_audit.json から読む。

使い方: python3 night/irr_rung_audit.py [--power] [--semi-list] [--json]
  --power     検出力を測る（重い・純Pythonで数分）。既定は走らせない
  --semi-list 半導体連鎖の判定を1社ずつSIC記述つきで出す（線は判断なので引き直せるように）
"""
import json, os, sys, random, statistics as st
from collections import defaultdict, Counter

B = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out')
def L(p):
    with open(os.path.join(B, p)) as f: return json.load(f)

HURDLE = 0.15      # 既存のハードル（新しい定数を作らない）
IMPAIR = -0.15     # 既存の恒久毀損の線
SEED   = 20260919

# ── 素材 ────────────────────────────────────────────────
# ⚠ ビンテージごとの読解ファイルは複数ある。一覧を眺めても「どれが同じ系列か」は判らない
#   （実測: 最初の測定で retro_moat_2013q.json 130社を落とした）。durability の build() と
#   同じ集合を使い、2018 を足す。
SRC = {
    '2013': [('retro_moat_2013.json', 'irr', 'ticker'), ('retro_moat_2013q.json', 'irr', 'ticker')],
    '2015': [('retro_moat_2015.json', 'irr', 'ticker'), ('retro_moat_2015q.json', 'irr', 'ticker'),
             ('retro_moat_2015qb.json', 'irr', 'ticker')],
    '2018': [('retro_moat_2018.json', 'irr18', 't'), ('retro_moat_2018_rest.json', 'irr18', 't')],
}
RET = {'2013': 'retro_returns_2013_all.json', '2015': 'retro_returns_2015_q.json',
       '2018': 'retro_returns_2018.json'}

def semi_map():
    """半導体連鎖の判定。⚠これは判断であって測定ではない。--semi-list で1社ずつ出せる。"""
    m = {}
    for r in L('retro_sic.json')['rows']:
        s, d = (r.get('sic') or ''), (r.get('sicDesc') or '')
        dl = d.lower()
        hit = ('semiconductor' in dl or 'electronic component' in dl
               or s in {'3559','3674','3672','3675','3676','3677','3678','3679','3827'})
        m[r['ticker']] = (hit, s, d)
    return m

def build():
    SEMI = semi_map()
    rows, dup_in_v, missing = [], Counter(), Counter()
    for v, files in SRC.items():
        ret = {r['ticker']: r for r in L(RET[v])['rows'] if r.get('tr_cagr') is not None}
        seen = {}
        for fn, key, tk in files:
            for r in L(fn)['rows']:
                if r.get(key) is None: continue
                t = r[tk]
                if t in seen: dup_in_v[v] += 1      # 同じビンテージ内の重複（後勝ちにはしない・数える）
                seen[t] = r
                x = ret.get(t)
                if not x: missing[v] += 1; continue
                hit, sic, sdesc = SEMI.get(t, (False, '', ''))
                rows.append(dict(v=v, t=t, irr=r[key], m5=r.get('moat5'), mech=r.get('mech'),
                                 cagr=x['tr_cagr'], mdd=x.get('mdd'), years=x['years'],
                                 semi=hit, sic=sic, sicDesc=sdesc))
    # 同じビンテージ内の重複は1件に潰す（後勝ち＝durability と同じ作法）
    ded = {}
    for r in rows: ded[(r['v'], r['t'])] = r
    return list(ded.values()), dict(dup_in_v), dict(missing)

def stats(rs):
    if not rs: return None
    c = [r['cagr'] for r in rs]
    return dict(n=len(rs), med=round(st.median(c), 4),
                p15=round(sum(1 for x in c if x >= HURDLE)/len(c), 3),
                impair=round(sum(1 for x in c if x <= IMPAIR)/len(c), 3),
                impair_n=sum(1 for x in c if x <= IMPAIR),
                neg=round(sum(1 for x in c if x < 0)/len(c), 3),
                worst=round(min(c), 3), semi_n=sum(1 for r in rs if r['semi']))

def rungs(rs):
    out = {'base': stats(rs)}
    for k in sorted({r['irr'] for r in rs}):
        out[str(k)] = stats([r for r in rs if r['irr'] == k])
    return out

# ── lift とその値札 ──────────────────────────────────────
def lift_of(win, pred_idx, n):
    k = len(pred_idx)
    if k == 0 or k == n: return None
    s = set(pred_idx)
    a = sum(win[i] for i in pred_idx)
    b = sum(win) - a
    return a/k - b/(n-k)

def value_tag(rs, pred, B_perm=2000, B_boot=2000):
    """実測の lift と、その値札（置換p・帰無の95%点・ブートストラップCI）。
    ⚠置換は『同じ n,k の群を無作為に作る』＝群の大きさは保ったままラベルだけ混ぜる帰無。"""
    n = len(rs)
    win = [1 if r['cagr'] >= HURDLE else 0 for r in rs]
    idx = [i for i, r in enumerate(rs) if pred(r)]
    obs = lift_of(win, idx, n)
    if obs is None: return None
    k = len(idx)
    rnd = random.Random(SEED)
    order = list(range(n)); null = []; hit = 0
    for _ in range(B_perm):
        rnd.shuffle(order)
        l = lift_of(win, order[:k], n)
        null.append(l)
        if l >= obs: hit += 1
    null.sort()
    # ブートストラップ（会社を resample）
    rnd2 = random.Random(SEED + 1); bs = []
    for _ in range(B_boot):
        s = [rs[rnd2.randrange(n)] for _ in range(n)]
        w = [1 if r['cagr'] >= HURDLE else 0 for r in s]
        ii = [i for i, r in enumerate(s) if pred(r)]
        l = lift_of(w, ii, n)
        if l is not None: bs.append(l)
    bs.sort()
    return dict(lift=round(obs, 3), n_group=k, p=round(hit/B_perm, 4),
                null_p95=round(null[int(.95*B_perm)], 3),
                null_p99=round(null[int(.99*B_perm)], 3),
                ci95=[round(bs[int(.025*len(bs))], 3), round(bs[int(.975*len(bs))], 3)],
                detectable="実測が帰無の95%点を超える" if obs > null[int(.95*B_perm)] else "実測が帰無の95%点に届かない")

def power(rs, k, deltas, B=800, BB=250):
    """この標本サイズで、真の効果 Δ を p<0.05 で拾える確率。
    ⚠『lift が線に届かない＝効果が無い』と読む前に、これを見ること。"""
    n = len(rs); base = sum(1 for r in rs if r['cagr'] >= HURDLE)/n
    rnd = random.Random(SEED + 2); out = {}
    for d in deltas:
        hit = 0
        for _ in range(B):
            pool = ([1 if rnd.random() < min(1, base+d) else 0 for _ in range(k)] +
                    [1 if rnd.random() < base else 0 for _ in range(n-k)])
            obs = sum(pool[:k])/k - sum(pool[k:])/(n-k)
            c = 0
            for _ in range(BB):
                rnd.shuffle(pool)
                if sum(pool[:k])/k - sum(pool[k:])/(n-k) >= obs: c += 1
            if c/BB < 0.05: hit += 1
        out[f"{d:+.2f}"] = round(hit/B, 2)
    return out

# ── 歴史の刻み vs 今日の台帳の刻み ──────────────────────────
def today_rungs():
    import glob
    out = {}
    for p in glob.glob(os.path.join(B, '*_gate_pack.json')):
        t = os.path.basename(p).replace('_gate_pack.json', '')
        try: d = json.load(open(p))
        except Exception: continue
        v = d.get('irr', (d.get('data') or {}).get('irr'))
        if v is not None: out[t] = v
    return out

def agreement(rows, today):
    """歴史で読まれた刻みと、今日の台帳の刻みが同じ社を指しているか。
    ⚠ 一致率が低い刻みは、歴史の数字をそのまま今日の刻みの根拠にできない
      （この台帳が13回踏んだ「基準の違う二つを割る」型）。"""
    newest = {}
    for r in sorted(rows, key=lambda r: r['v']): newest[r['t']] = r['irr']
    mat, res = defaultdict(Counter), {}
    for t, h in newest.items():
        if t in today: mat[h][today[t]] += 1
    for h in sorted(mat):
        tot = sum(mat[h].values())
        res[str(h)] = dict(n=tot, same=mat[h][h], rate=round(mat[h][h]/tot, 3),
                           to={str(k): v for k, v in sorted(mat[h].items())})
    return res

def cross_check(rows):
    """durability(のべ・2013+2015のみ)と同条件で数えて、差が説明できるか。
    ⚠ 二つの器が違う数を出すこと自体は破れではない。破れになるのは **なぜ違うかを機械が
      説明できない** とき。ここでは差を「刻みが付かなかった社（irr が空欄）」まで分解する:
      durability は *読解された社* を数え（母集団のベースを出す器）、こちらは *刻みが付いた社*
      を数える（刻み別の統計を出す器）。差は irr=null の社そのものになるはず。"""
    try: d = L('retro_moat_durability.json')
    except Exception: return {'status': '読めなかった'}
    # durability と同じ集合を、irr の有無を問わずに数える
    seen, unrated = set(), []
    for v in ('2013', '2015'):
        ret = {r['ticker'] for r in L(RET[v])['rows'] if r.get('tr_cagr') is not None}
        for fn, key, tk in SRC[v]:
            for r in L(fn)['rows']:
                t = r[tk]
                if t not in ret: continue
                seen.add((v, t))
                if r.get(key) is None:
                    unrated.append(dict(v=v, t=t, moat5=r.get('moat5'),
                                        why=(r.get('note') or '')[:120]))
    # 同じビンテージ内の重複は潰れるので、unrated も (v,t) で一意化
    uq = {(u['v'], u['t']): u for u in unrated}
    mine = [r for r in rows if r['v'] in ('2013', '2015')]
    diff = len(seen) - len(mine)
    return {'note': 'durability は 2013+2015 の のべ（2018は欄名が違うので不参加＝設計）',
            'durability_n_total': d.get('n_total'),
            'same_set_counted_here': len(seen),
            'rated_here': len(mine),
            'diff': diff,
            'explained_by_unrated': len(uq),
            'reconciled': (d.get('n_total') == len(seen)) and (diff == len(uq)),
            'unrated_companies': sorted(uq.values(), key=lambda u: (u['v'], u['t']))}


def main():
    args = sys.argv[1:]
    rows, dup, miss = build()
    per = {}
    for r in sorted(rows, key=lambda r: r['v']): per[r['t']] = r   # 社単位＝最も新しいビンテージ
    uni = list(per.values())
    nonsemi = [r for r in uni if not r['semi']]
    today = today_rungs()

    out = {
        'generated': __import__('datetime').date.today().isoformat(),
        'tool': 'night/irr_rung_audit.py',
        'stance': '測定器。判定も合否の線も持たない（絶対のルール1）',
        'hurdle': HURDLE, 'impair_line': IMPAIR, 'seed': SEED,
        'material': dict(rows_total=len(rows), companies=len({r['t'] for r in rows}),
                         by_vintage=dict(Counter(r['v'] for r in rows)),
                         dup_within_vintage=dup, no_return_data=miss,
                         multi_vintage=sum(1 for t, vs in
                             __import__('collections').Counter(r['t'] for r in rows).items() if vs > 1)),
        'rungs_pooled':   rungs(rows),
        'rungs_per_company': rungs(uni),
        'rungs_non_semi': rungs(nonsemi),
        'rungs_semi_only': rungs([r for r in uni if r['semi']]),
        'today_rung_dist': dict(Counter(today.values())),
        'agreement_hist_vs_today': agreement(rows, today),
        'cross_check_durability': cross_check(rows),
    }

    CASES = [('irr=85', lambda r: r['irr'] == 85),
             ('irr>=70', lambda r: r['irr'] >= 70),
             ('irr=70or75', lambda r: r['irr'] in (70, 75)),
             ('irr=100', lambda r: r['irr'] == 100),
             ('moat5>=4', lambda r: (r['m5'] or 0) >= 4),
             ('半導体連鎖（対照）', lambda r: r['semi'])]
    out['lift_per_company'] = {lab: value_tag(uni, f) for lab, f in CASES}
    out['lift_non_semi'] = {lab: value_tag(nonsemi, f) for lab, f in CASES if lab != '半導体連鎖（対照）'}

    if '--power' in args:
        ks = {'n=%d (irr=85 社単位)' % len([r for r in uni if r['irr'] == 85]): len([r for r in uni if r['irr'] == 85]),
              'n=%d (irr=85 非半導体)' % len([r for r in nonsemi if r['irr'] == 85]): len([r for r in nonsemi if r['irr'] == 85]),
              'n=%d (irr=70/75)' % len([r for r in uni if r['irr'] in (70, 75)]): len([r for r in uni if r['irr'] in (70, 75)])}
        out['power'] = {lab: power(uni, k, [0.10, 0.15, 0.20, 0.30]) for lab, k in ks.items()}
        out['power_note'] = 'lift が線に届かないことは、この確率が低ければ「効果が無い」を意味しない'
    else:
        out['power'] = None
        out['power_note'] = '--power で測る（重いので既定では走らせない）'

    if '--semi-list' in args:
        out['semi_list'] = sorted([dict(t=r['t'], sic=r['sic'], desc=r['sicDesc'], irr=r['irr'])
                                   for r in uni if r['semi']], key=lambda x: x['t'])

    p = os.path.join(B, 'irr_rung_audit.json')
    with open(p, 'w') as f: json.dump(out, f, ensure_ascii=False, indent=1)

    if '--json' in args:
        print(json.dumps(out, ensure_ascii=False, indent=1)); return

    m = out['material']
    print(f"■ 素材  のべ{m['rows_total']}件／実{m['companies']}社／複数ビンテージ {m['multi_vintage']}社")
    print(f"   ビンテージ別 {m['by_vintage']}  ビンテージ内の重複 {m['dup_within_vintage']}  返り値なし {m['no_return_data']}")
    for lab, key in [('のべ', 'rungs_pooled'), ('社単位', 'rungs_per_company'),
                     ('社単位∧非半導体', 'rungs_non_semi'), ('社単位∧半導体のみ', 'rungs_semi_only')]:
        print(f"\n--- {lab} ---")
        for k, s in out[key].items():
            if s: print(f"   {k:<6} n={s['n']:<4} 中央{s['med']:+.1%}  15%+ {s['p15']:.3f}  毀損 {s['impair']:.3f}({s['impair_n']})  最悪{s['worst']:+.1%}")
    print("\n--- lift とその値札（社単位）---")
    for lab, v in out['lift_per_company'].items():
        if v: print(f"   {lab:<18} lift {v['lift']:+.3f} n={v['n_group']:<4} p={v['p']:.4f} CI[{v['ci95'][0]:+.3f},{v['ci95'][1]:+.3f}] 帰無95%点{v['null_p95']:+.3f} → {v['detectable']}")
    print("\n--- lift（非半導体）---")
    for lab, v in out['lift_non_semi'].items():
        if v: print(f"   {lab:<18} lift {v['lift']:+.3f} n={v['n_group']:<4} p={v['p']:.4f} CI[{v['ci95'][0]:+.3f},{v['ci95'][1]:+.3f}]")
    print(f"\n--- 歴史の刻み → 今日の台帳の刻み（今日の分布 {out['today_rung_dist']}）---")
    for h, a in out['agreement_hist_vs_today'].items():
        print(f"   歴史{h:<4} n={a['n']:<3} 同じ刻み {a['same']}/{a['n']} = {a['rate']:.0%}   行き先 {a['to']}")
    if out.get('power'):
        print("\n--- 検出力（真の効果Δを p<0.05 で拾える確率）---")
        for lab, d in out['power'].items(): print(f"   {lab:<24} " + "  ".join(f"{k}→{v:.2f}" for k, v in d.items()))
    print(f"\n→ {p}")

if __name__ == '__main__':
    main()
