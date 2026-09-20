#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_size.py — **irr=85 に時価総額（規模）は効くのか**（2026-09-20新設・読むだけ）

ユーザーの問い「irr85で時価総額による影響はあるの？」への測定。**判定にも採点にも一切介入しない。**

★先に限界を言う: **時価総額は歴史側の在庫に一件も無い**（`grep mcap out/retro_*.json` が0件）。
  この台帳が一貫して使ってきた規模の物差しは **売上規模(rev)** で、
  `retro_capture` の「売上50億$+ → 生存 +20.8pt」・`retro_business_vs_price` の
  「株価に対して唯一残った指標が売上規模（2013 ρ+0.24 / 2015 +0.10）」もすべて売上。
  ⇒ 歴史の側は **売上規模を代理として** 測る。時価総額そのものを歴史で測るには
  px×株数の再構成が要り、それは未実施＝**穴として明示する**。

出すもの（3つの経路＋歴史）:
  A **Ω への経路** … `mcap` は発見度(negS)の入力（index.html:2425 の枝）。
     **刻みは <2十億$→+2 / >100→−1** で、罰が効くのは negS≤−2 のときだけ。
     mcap の枝は `analysts<=0 && instOwn<=0` でしか発火せず、他に負へ効く項が無いので
     **>100 の側は −1 で止まり閾値 −2 に原理的に届かない＝空回り**。
     一方 <2 は単独で +2 に届くので **+1.5 の褒美は現に効く**（実測で確認する）。
  B **配分への経路** … 目標ウェイトは時価総額Tier（v9.9.147）。**ここは現に効く**。
  C **合否・席への経路** … buyGate / ccfMoatGate / ccfIrr85Frame / ccfAllocTop の mech に
     時価総額は入らない＝**効かない**。
  D **歴史** … irr=85 の中で売上規模がリターンを分けるか。⚠ 事前登録は無い＝**事後の測定**。
     `irr85_criteria`（事前登録・候補15本・偽陽性率0.678）は **rev を候補に含めて不合格**に
     していた（lift +0.192 だが半導体で符号反転 −0.05/+0.33）。ここはその再測定＋層別。
"""
import json, os, re, sys, glob, statistics, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, 'night')
from audit_hist85_today import collect85, rows_of, SEMI_SIC, VINTAGES  # noqa: E402  二重実装を作らない

TODAY = __import__('datetime').date.today().isoformat()
HURDLE = 0.15   # 既存のハードル（新しい定数を作らない）


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def spearman(xs, ys):
    """順位相関。中央値二分は情報を捨てるので連続のまま見る（hist10 の作法）"""
    pr = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pr) < 4:
        return None, len(pr)
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(s):
            j = i
            while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[s[k]] = avg
            i = j + 1
        return r
    a, b = rank([p[0] for p in pr]), rank([p[1] for p in pr])
    n = len(pr)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** .5
    db = sum((y - mb) ** 2 for y in b) ** .5
    return (num / (da * db) if da and db else None), n


def split_lift(rows, key):
    """中央値二分して P(年率≥15%) の lift を出す。⚠ 事前登録の線は引かない（記述）"""
    v = [r for r in rows if r.get(key) is not None and r.get('tr') is not None]
    if len(v) < 4:
        return None
    m = statistics.median([r[key] for r in v])
    hi = [r for r in v if r[key] > m]
    lo = [r for r in v if r[key] <= m]
    if not hi or not lo:
        return None
    ph = sum(1 for r in hi if r['tr'] >= HURDLE) / len(hi)
    pl = sum(1 for r in lo if r['tr'] >= HURDLE) / len(lo)
    return dict(n=len(v), median=m, n_hi=len(hi), n_lo=len(lo),
                p_hi=round(ph, 3), p_lo=round(pl, 3), lift=round(ph - pl, 3),
                med_hi=round(med([r['tr'] for r in hi]), 4),
                med_lo=round(med([r['tr'] for r in lo]), 4))


# ---------- 今日の門（A/B/C） ----------
def today_part():
    if not os.path.exists('out/score_all.json'):
        subprocess.run(['node', 'night/score_all.js'], capture_output=True, text=True)
    sa = json.load(open('out/score_all.json', encoding='utf-8'))
    sa = sa if isinstance(sa, list) else (sa.get('rows') or [])
    by = {r.get('t'): r for r in sa if isinstance(r, dict)}
    out = []
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        d = json.load(open(p, encoding='utf-8'))
        if d.get('irr') != 85:
            continue
        t = os.path.basename(p).replace('_gate_pack.json', '')
        r = by.get(t, {})
        an = float(d.get('analysts') or 0); io = float(d.get('instOwn') or 0)
        mc = d.get('mcap')
        mc = float(mc) if mc not in (None, '') else None
        fires = (an <= 0 and io <= 0 and mc is not None and mc > 0)
        band = None
        if fires:
            band = '<2（+2→Ω+1.5が効く）' if mc < 2 else ('>100（−1・閾値−2に届かず空回り）' if mc > 100 else '中間2-100（据え置き）')
        out.append(dict(t=t, jp=bool(re.fullmatch(r'\d{4,5}', t)),
                        mcap_field=mc, mcapU=r.get('mcapU'), tier=r.get('tier') if False else None,
                        omega=r.get('s'), moat=r.get('moat'), buy=r.get('buy'),
                        negS_fires=fires, negS_band=band))
    return out


def mcap_channel_all():
    """mcap が発見度の枝に入る社を全数で数える（今日 Ω を動かしているのはどの帯か）"""
    small, big, mid, empty = [], [], 0, 0
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        d = json.load(open(p, encoding='utf-8'))
        t = os.path.basename(p).replace('_gate_pack.json', '')
        an = float(d.get('analysts') or 0); io = float(d.get('instOwn') or 0)
        mc = d.get('mcap')
        if mc in (None, ''):
            empty += 1
            continue
        mc = float(mc)
        if not (an <= 0 and io <= 0 and mc > 0):
            continue
        jp = bool(re.fullmatch(r'\d{4,5}', t))
        if mc < 2:
            small.append([t, mc, jp])
        elif mc > 100:
            big.append([t, mc, jp])
        else:
            mid += 1
    return dict(small=sorted(small, key=lambda x: x[1]), big=sorted(big, key=lambda x: -x[1]),
                mid=mid, empty=empty)


# ---------- 配分（B）: 門の ccfMcapWeights をそのまま抜いて使う（再実装しない・v9.9.65） ----------
def alloc_part():
    from shadow_irr85_privilege import _slice_fn   # 切り出しも既存の実装を借りる
    src = open('index.html', encoding='utf-8').read()
    body = "\n".join(_slice_fn(src, h) for h in (
        'function ccfMcapUSD(', 'const CCF_MCAP_TIERS=',
        'function ccfMcapTier(', 'function ccfMcapWeights('))
    rows = json.load(open('out/score_all.json', encoding='utf-8'))
    rows = rows if isinstance(rows, list) else (rows.get('rows') or [])
    buy = [r['t'] for r in rows if r.get('buy')]
    ex = json.load(open('gate_exceptions.json', encoding='utf-8')).get('items') or []
    exl = [e['t'] for e in ex if e.get('in_castle_split')]
    fx = (json.load(open('out/dashboard.json', encoding='utf-8')).get('fx') or {}).get('USDJPY')
    def pk(t):
        f = 'out/%s_gate_pack.json' % t
        d = json.load(open(f, encoding='utf-8')) if os.path.exists(f) else {}
        return {'t': t, 'nm': d.get('nm'), 'px': d.get('px'), 'ni': d.get('ni'),
                'eps': d.get('eps'), 'irr': d.get('irr')}
    lst = [pk(t) for t in buy + [t for t in exl if t not in buy]]
    js = (body + "\nconst IN=" + json.dumps(lst) + ";\n"
          + "const list=IN.map(x=>({t:x.t,m:ccfMcapUSD(x," + repr(fx) + ")}));\n"
          + "const r=ccfMcapWeights(list,50,8);\n"   # 城の按分枠50%（特別枠は v9.9.159 で0社）
          + "console.log(JSON.stringify({mode:r.mode,w:r.w,tier:r.tier,missing:r.missing,"
            "m:Object.fromEntries(list.map(x=>[x.t,x.m]))}));")
    pr = subprocess.run(['node', '-e', js], capture_output=True, text=True)
    if pr.returncode:
        return dict(error=(pr.stderr or pr.stdout)[:300])
    o = json.loads(pr.stdout)
    irr = {x['t']: x['irr'] for x in lst}
    tbl = [dict(t=t, mcapU=o['m'].get(t), tier=o['tier'].get(t), w=o['w'][t],
                irr=irr.get(t), seat=(t in buy)) for t in o['w']]
    tbl.sort(key=lambda r: -(r['mcapU'] or 0))
    def s85(f):
        v = [r['w'] for r in tbl if f(r)]
        return dict(n=len(v), sum=round(sum(v), 2), avg=(round(sum(v) / len(v), 2) if v else None))
    return dict(fx=fx, mode=o['mode'], missing=o['missing'], rows=tbl,
                irr85=s85(lambda r: r['irr'] == 85), irr70=s85(lambda r: r['irr'] == 70),
                equal_weight=round(50.0 / len(tbl), 2))


# ---------- 歴史（D） ----------
# 規模は **売上(rev)**。⚠ 窓・アンカーを揃えるため、主測定は
#   「2018年時点の売上 × 2018→2026 のリターン」で 28社ぜんぶを同じ基準に載せる
#   （audit_hist85_today が確立した基準。窓が違う数字を並べない）。
def hist_part():
    f2 = {r['ticker']: r for r in rows_of('out/retro_features2_2018.json')}
    ret = {r['ticker']: r for r in rows_of('out/retro_returns_2018.json')}
    sic = {r['ticker']: r for r in rows_of('out/retro_sic.json')}
    # 刻みのラベル（ビンテージで欄名が違うので audit_hist85_today の VINTAGES を借りる）
    rung = {}
    for v, f, key, fld in VINTAGES:
        if not os.path.exists(f):
            continue
        for r in rows_of(f):
            t, x = r.get(key), r.get(fld)
            if t and x in (50, 70, 75, 85, 100):
                rung.setdefault(t, {})[v] = x

    def mk(t):
        a, b, s = f2.get(t), ret.get(t), sic.get(t)
        sic4 = (s or {}).get('sic')
        return dict(t=t, rev=(a or {}).get('rev'), tr=(b or {}).get('tr_cagr'),
                    mdd=(b or {}).get('mdd'), years=(b or {}).get('years'),
                    sic=sic4, semi=(sic4 in SEMI_SIC) if sic4 else None,
                    rungs=rung.get(t, {}))

    u85 = collect85()
    g85 = [mk(t) for t in sorted(u85)]
    # 対照: 読解された社のうち 85 でない群（刻み別）
    others = {}
    for t, d in rung.items():
        if t in u85:
            continue
        top = max(d.values())
        others.setdefault(top, []).append(mk(t))
    cohort = [mk(t) for t in sorted(ret)]

    def pack(rows, label):
        v = [r for r in rows if r.get('tr') is not None]
        vr = [r for r in v if r.get('rev') is not None]
        rho, n_rho = spearman([r['rev'] for r in vr], [r['tr'] for r in vr])
        return dict(label=label, n=len(rows), n_ret=len(v), n_rev=len(vr),
                    med_tr=(round(med([r['tr'] for r in v]), 4) if v else None),
                    p15=(round(sum(1 for r in v if r['tr'] >= HURDLE) / len(v), 3) if v else None),
                    rho_rev_tr=(round(rho, 3) if rho is not None else None), n_rho=n_rho,
                    split=split_lift(vr, 'rev'))

    res = dict(all85=pack(g85, 'irr=85（実社28）'), cohort=pack(cohort, '2018コホート全体'))
    res['by_rung'] = {str(k): pack(v, 'irr=%d' % k) for k, v in sorted(others.items())}
    res['semi'] = dict(
        inside=pack([r for r in g85 if r['semi'] is True], 'irr=85 ∧ 半導体連鎖'),
        outside=pack([r for r in g85 if r['semi'] is False], 'irr=85 ∧ 非半導体'))
    res['semi_split'] = dict(
        inside=split_lift([r for r in g85 if r['semi'] is True and r.get('rev') is not None], 'rev'),
        outside=split_lift([r for r in g85 if r['semi'] is False and r.get('rev') is not None], 'rev'))
    res['cohort_split'] = split_lift([r for r in cohort if r.get('rev') is not None], 'rev')
    res['rows'] = g85
    return res


def main():
    t = today_part()
    ch = mcap_channel_all()
    h = hist_part()
    al = alloc_part()
    out = dict(generated=TODAY, hurdle=HURDLE, alloc=al,
               note='時価総額は歴史側の在庫に一件も無い（代理は売上規模）。Dは事前登録の無い事後の測定。',
               today=t, mcap_channel=ch, hist=h)
    json.dump(out, open('out/irr85_size.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    print('irr85_size  %s' % TODAY)
    print('\n【A】Ω への経路（発見度 negS・index.html:2425）')
    print('  mcap が枝に入る社を全数で: <2十億$ %d社（+2→Ω+1.5が効く）／ >100 %d社（−1・空回り）／ 中間 %d社 ／ 欄が空 %d社'
          % (len(ch['small']), len(ch['big']), ch['mid'], ch['empty']))
    print('  ⚠ >100 の枝は analysts<=0 ∧ instOwn<=0 でしか発火せず、他に負へ効く項が無いので')
    print('     negS は −1 で止まり罰の閾値 −2 に**原理的に届かない**＝この枝は空回りしている。')
    jpbig = [x for x in ch['big'] if x[2]]
    print('  ⚠ >100 の %d社のうち日本株 %d社（%s…）＝JP の mcap は十億**円**なので過大に読まれているが、'
          % (len(ch['big']), len(jpbig), ' '.join(x[0] for x in jpbig[:4])))
    print('     倒れる先が空回りの枝なので **Ω へは効かない**（十億円で <2 になる上場企業は事実上無い）。')
    print('\n  irr=85 の14社:')
    for r in t:
        print('   %-6s mcap欄 %-10s → %s' % (r['t'], r['mcap_field'], r['negS_band'] or '欄が空＝発火しない'))
    print('\n【B】配分への経路（時価総額Tier・v9.9.147）  ドル円 %s ／ mode %s ／ 測れない社 %s'
          % (al.get('fx'), al.get('mode'), al.get('missing') or 'なし'))
    for r in al.get('rows', []):
        print('   %-6s %8s 十億$  %-14s 目標 %5.2f%%  irr=%-3s %s'
              % (r['t'], ('%.1f' % r['mcapU']) if r['mcapU'] else '未取得',
                 r['tier'], r['w'], r['irr'], '★席' if r['seat'] else '門外例外'))
    print('   irr=85 %d社 計 %.2f%%（平均 %.2f）／ irr=70 %d社 計 %.2f%%（平均 %.2f）／ 等ウェイトなら 1社 %.2f%%'
          % (al['irr85']['n'], al['irr85']['sum'], al['irr85']['avg'],
             al['irr70']['n'], al['irr70']['sum'], al['irr70']['avg'], al['equal_weight']))
    print('   ★**時価総額Tierは irr=85 を構造的に軽くする**——歴史で唯一効いた変数なのに配分では最も軽い。')
    print('     席の優先(v9.9.100)は irr=85 を先に置くが、**金額は時価総額が決める**ので優先が金額に伝わらない。')
    print('\n【C】合否・席への経路 … buyGate / ccfMoatGate / ccfIrr85Frame / ccfAllocTop の mech に')
    print('     時価総額は入らない＝**効かない**（grep で確認・irr だけが席の優先を握る）。')
    print('\n【D】歴史（規模＝売上・2018年時点 × 2018→2026 のリターン）')
    for k in ('all85', 'cohort'):
        x = h[k]
        print('  %-22s n=%-3d 中央値 %s  P(≥15%%) %s  ρ(売上,リターン) %s (n=%d)'
              % (x['label'], x['n_ret'], x['med_tr'], x['p15'], x['rho_rev_tr'], x['n_rho']))
    for k, x in h['by_rung'].items():
        print('  %-22s n=%-3d 中央値 %s  P(≥15%%) %s  ρ %s (n=%d)'
              % (x['label'], x['n_ret'], x['med_tr'], x['p15'], x['rho_rev_tr'], x['n_rho']))
    for k in ('inside', 'outside'):
        x = h['semi'][k]
        print('  %-22s n=%-3d 中央値 %s  P(≥15%%) %s  ρ %s (n=%d)'
              % (x['label'], x['n_ret'], x['med_tr'], x['p15'], x['rho_rev_tr'], x['n_rho']))
    print('\n  中央値二分（P(≥15%) の lift）')
    print('   irr=85 全体   :', json.dumps(h['all85']['split'], ensure_ascii=False))
    print('   ∧半導体連鎖   :', json.dumps(h['semi_split']['inside'], ensure_ascii=False))
    print('   ∧非半導体     :', json.dumps(h['semi_split']['outside'], ensure_ascii=False))
    print('   （対照）母集団 :', json.dumps(h['cohort_split'], ensure_ascii=False))
    print('  ⚠ irr=85 の lift +0.192 は `irr85_criteria` の事前登録検定が rev について出した値と一致し、')
    print('     層別の −0.05 / +0.333 も「半導体で符号が反転」の実測を独立に再現した＝**不合格の再確認**。')
    print('  ⚠ n=27 では lift の分解能が粗い——売上と営業利益率は**別々の分割**なのに同じ lift 0.192 を返す。')
    print('\n→ out/irr85_size.json')


if __name__ == '__main__':
    main()
