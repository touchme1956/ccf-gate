#!/usr/bin/env python3
"""night/alloc_check.py — 「NASDAQ100 50 / SMH20 / ITA10 / 個別株20% これは？」（2026-10-11・ユーザーの問い）

読むだけ。門・採点・配分（portfolio.json）には触れない。判断の材料（事後・仮説の検定ではない）。
形・判定の決まり・勧め方は、計算の前にこのファイルに固定してコミットする。

比べる2つ（合計の比）:
  今 … NASDAQ100 50 / SMH 20 / ITA 15 / 個別株 15
  案 … NASDAQ100 50 / SMH 20 / ITA 10 / 個別株 20   （＝ITA の5を個別株へ）
個別株の代え方（これからの物差しは ETF しか持たないので、個別株を ETF で代える）:
  V … 市場（VOO）＝銘柄を選ぶ上乗せ0・市場並みの値動き（future30 の Q3b・100年の代用と同じ置き方）
  S … 席の業種の写し＝今の投下可（out/score_all.json の buy）を席の順位の重み（portfolio.json の castle_rank_weights）で
      業種の ETF に置く（SECTOR の表: CW→ITA・LRCX/ASML/KLAC→SMH・MSFT/GOOGL→QQQM・MCO→VOO・IDXX→XLV）
      ＝上乗せ0だが業種の傾きは今の席どおり。表に無い社が席に入っていたら止まる（推測で置かない）
  ⚠ どちらも銘柄ごとの値動き（4〜8社の固有のぶれ）を持たない＝個別株のぶれと下落を小さく見せる向き
物差し:
  ① 4つの世界と20年の積立の確率（morefunds.seat_metrics・感度5本）で 案 − 今 を etf_ita_xlk と同じ決まりで判定
     （全体の形を V と S で。参考に ETF 側だけ〔個別株を除き 85→80 を正規化〕）。
     参考（判定に使わない）: future30_options の条件（15%以上の確率 ≥ 今−3pt ∧ 最悪の世界 > 今 ∧ 5%未満 < 今）
     自己検問: seat_metrics が作る席A の ITA の行が out/etf_ita_xlk.json の席A の ITA の行と一致しなければ止まる
  ② 100年の代用（future30 と同じ: NASDAQ100＝テック65%＋市場35%・SMH＝Chips・ITA＝Aero＋Guns・VOO＝市場・
     XLV＝Drugs＋MedEq＋Hlth を前月末の時価総額で加重）で、30年（起点1965〜1995）と20年（起点1965〜2005）の
     毎月の積立の市場との比（中央値・下位10%点・最悪・市場に勝った割合）。個別株は V なら市場、S なら席の業種の写し
  ③ 注文書の時期の目安（今の保有・値段は横ばい・売らない・入金は今月から pf:monthly、nisa.monthly_from から
     nisa.monthly_total_jpy）: 区分の比率が目標を下回る月＝その区分に新しいお金が入り始める月。
     目標を超えている区分の取り分は¥0（ccfCatBudget の不足の比）なので、下回るまでの比率は 保有÷(総資産＋入金の累計)。
     ⚠ 1株単位の注文では、下回ってから1株の半分に届くまで1〜2か月遅れることがある
  ④ 集中（ETF の中身まで・目標の姿）: night/lookthrough.py --what-if に今と案の目標の姿を渡し、指定の行をそのまま写す
勧め方（計算の前に固定）:
  案を勧めるのは、①の全体の形が V と S の両方で『堅い価値あり』のときだけ。
  それ以外は『今のまま』（変える根拠がデータに無い）。②③④は判定に使わない。
  採否はユーザー（この道具は portfolio.json を書かない）
出力: out/alloc_check.json
"""
import datetime, json, os, re, statistics as S, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import morefunds as MF        # noqa: E402
import gaps_common as G       # noqa: E402
import future30 as F          # noqa: E402
import future30_xlk as FX     # noqa: E402

OUT = os.path.join(BASE, 'out', 'alloc_check.json')

NOW = {'QQQM': 50, 'SMH': 20, 'ITA': 15}       # 今の ETF 側（NASDAQ100 は QQQM で代える＝morefunds・etf_ita_xlk と同じ）
NEW = {'QQQM': 50, 'SMH': 20, 'ITA': 10}       # 案の ETF 側
CASTLE_NOW, CASTLE_NEW = 15, 20                # 個別株
SECTOR = {'CW': 'ITA', 'LRCX': 'SMH', 'ASML': 'SMH', 'KLAC': 'SMH',
          'MSFT': 'QQQM', 'GOOGL': 'QQQM', 'MCO': 'VOO', 'IDXX': 'XLV'}


def seats():
    rows = [r for r in json.load(open(os.path.join(BASE, 'out', 'score_all.json'))) if r.get('buy') is True]
    rows.sort(key=lambda r: -float(r['s']))
    tg = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    rw = tg.get('castle_rank_weights') or []
    if tg.get('castle_weighting') != 'rank' or len(rw) < len(rows):
        raise SystemExit(f"✗ 席の重みが rank でないか重みが足りない（{tg.get('castle_weighting')}・{len(rw)}本 対 席{len(rows)}社）＝写しを作れない")
    w = {r['t']: float(rw[i]) for i, r in enumerate(rows)}
    miss = [t for t in w if t not in SECTOR]
    if miss:
        raise SystemExit(f'✗ 業種の表に無い社が席に入っている: {miss}（推測で置かない＝SECTOR に足してから回す）')
    tot = sum(w.values())
    prox = {}
    for t, v in w.items():
        prox[SECTOR[t]] = prox.get(SECTOR[t], 0) + v / tot
    return [r['t'] for r in rows], {t: round(v / tot, 4) for t, v in w.items()}, prox


def forms(prox):
    def whole(etf, c, mode):
        f = dict(etf)
        if mode == 'V':
            f['VOO'] = f.get('VOO', 0) + c
        else:
            for k, v in prox.items():
                f[k] = f.get(k, 0) + c * v
        return f
    return {
        'N0 今の ETF 側（QQQM 50 / SMH 20 / ITA 15）': dict(NOW),
        'N1 案の ETF 側（QQQM 50 / SMH 20 / ITA 10）': dict(NEW),
        'V0 今（個別株15＝市場）': whole(NOW, CASTLE_NOW, 'V'),
        'V1 案（個別株20＝市場）': whole(NEW, CASTLE_NEW, 'V'),
        'S0 今（個別株15＝席の業種の写し）': whole(NOW, CASTLE_NOW, 'S'),
        'S1 案（個別株20＝席の業種の写し）': whole(NEW, CASTLE_NEW, 'S'),
    }


PAIRS = {'V 全体（個別株＝市場）': ('V1 案（個別株20＝市場）', 'V0 今（個別株15＝市場）'),
         'S 全体（個別株＝席の業種の写し）': ('S1 案（個別株20＝席の業種の写し）', 'S0 今（個別株15＝席の業種の写し）'),
         '参考 ETF 側だけ': ('N1 案の ETF 側（QQQM 50 / SMH 20 / ITA 10）', 'N0 今の ETF 側（QQQM 50 / SMH 20 / ITA 15）')}


def forward(FM):
    ctx = MF.CB.build(max_k=1)
    tabs = MF.p15_tables()
    Sx = MF.seat_metrics(ctx, tabs, FM)
    ref = json.load(open(os.path.join(BASE, 'out', 'etf_ita_xlk.json')))['slots']['A']['table']['ITA']
    mine = MF.row_of(Sx, 'ITA')
    for k in ('平均', '最悪', '確率', '五未満', 'ぶれ', '最大下落'):
        if k not in ref or abs(float(ref[k]) - float(mine[k])) > 0.051:
            raise SystemExit(f'✗ 自己検問: 席A の ITA の {k} が etf_ita_xlk.json と違う（{mine[k]} 対 {ref.get(k)}）')
    rows = {k: MF.row_of(Sx, k) for k in FM}
    jud = {nm: MF.judge(Sx, a, b) for nm, (a, b) in PAIRS.items()}
    ref_rule = {}
    for nm, (a, b) in PAIRS.items():
        ra, rb = rows[a], rows[b]
        ref_rule[nm] = dict(確率_15以上=bool(ra['確率'] >= rb['確率'] - 3), 最悪の世界=bool(ra['最悪'] > rb['最悪']),
                            確率_5未満=bool(ra['五未満'] < rb['五未満']))
        ref_rule[nm]['3つとも'] = all(ref_rule[nm].values())
    return {'自己検問': f"席A の ITA の行が out/etf_ita_xlk.json と一致（平均 {mine['平均']}・最悪 {mine['最悪']}・確率 {mine['確率']}）",
            '形ごと（主）': rows, '判定（案 − 今）': jud, '参考_future30_options の条件（判定に使わない）': ref_rule}


def century(FM):
    cols, ret, capm, me, be, share, mkt = F.load()
    endm = max(mkt)
    tech = G.french_tech()
    allm = sorted(mkt)
    parts = {'QQQM': F.mix([(0.65, tech), (0.35, mkt)], allm), 'SMH': ret['Chips'],
             'ITA': F.capw(ret, capm, ['Aero', 'Guns'], allm), 'VOO': mkt,
             'XLV': F.capw(ret, capm, ['Drugs', 'MedEq', 'Hlth'], allm)}
    out = {}
    for nm, f in FM.items():
        tw = sum(f.values())
        s = F.mix([(w / tw, parts[k]) for k, w in f.items() if w > 0], allm)
        d = {}
        for n, lab, starts, half in ((360, '30年の積立（起点1965〜1995）', range(1965, 1996), 1979),
                                     (240, '20年の積立（起点1965〜2005）', range(1965, 2006), 1985)):
            v = []
            for y in starts:
                ms = F.months((y + 1) * 100 + 1, n)
                if ms[-1] > endm:
                    continue
                a, b = F.dca_mult(s, ms), F.dca_mult(mkt, ms)
                if a and b:
                    v.append((y, a / b))
            xs = sorted(x for _, x in v)
            q = lambda p: xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))]
            d[lab] = {'窓': len(xs), '中央値': round(S.median(xs), 3), '下位10%点': round(q(0.10), 3), '最悪': round(xs[0], 3),
                      '市場に勝った割合': round(sum(x > 1 for x in xs) / len(xs), 2),
                      f'中央値_起点〜{half}': round(S.median([x for y, x in v if y <= half]), 3),
                      f'中央値_起点{half + 1}〜': round(S.median([x for y, x in v if y > half]), 3)}
        out[nm] = d
    return out


def timing():
    h, buckets, tot = FX.holdings()
    st = json.load(open(os.path.join(BASE, 'state.json')))
    d = st.get('data') or st
    tg = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    num = lambda x: int(float(str(x).replace(',', ''))) if x not in (None, '') else 0
    m0 = num(d.get('pf:monthly'))
    m1 = num((tg.get('nisa') or {}).get('monthly_total_jpy')) or m0
    start = int((tg.get('nisa') or {}).get('monthly_from', '2027-01').replace('-', ''))
    held = {'個別株': buckets.get('個別株', 0), 'その他（XLK・ITA ほか）': buckets.get('その他（XLK ほか）', 0)}
    targets = {'今': {'個別株': CASTLE_NOW, 'その他（XLK・ITA ほか）': NOW['ITA']},
               '案': {'個別株': CASTLE_NEW, 'その他（XLK・ITA ほか）': NEW['ITA']}}
    res = {}
    for nm, tgt in targets.items():
        r = {}
        for b, pct in tgt.items():
            m, cum, hit = 202610, 0, None
            for i in range(1, 361):
                cum += m1 if m >= start else m0
                if held[b] / (tot + cum) < pct / 100:
                    hit = (i, m)
                    break
                m = G.add_months(m, 1)
            r[b] = {'目標(%)': pct, '今(%)': round(100 * held[b] / tot, 1),
                    '新しいお金が入り始める月（目安）': None if not hit else f'{hit[0]}か月目（{hit[1] // 100}-{hit[1] % 100:02d}）'}
        res[nm] = r
    return {'保有の日（株数）': h['保有の日（株数）'], '価格の日': h['価格の日'], 'ドル円': h['ドル円'], '総額(円)': tot,
            '区分(%)': h['区分(%)'], '入金の前提': f'今月から毎月 ¥{m0:,}、{start // 100}-{start % 100:02d} から ¥{m1:,}（iDeCo・こどもNISA を含む入金額）・値段は横ばい・売らない',
            '今と案': res}


def concentration(prox_w):
    out = {}
    for nm, etf, c in (('今', NOW, CASTLE_NOW), ('案', NEW, CASTLE_NEW)):
        castle = ','.join(f'{t}={c * w:.3f}' for t, w in prox_w.items())
        net = ','.join(f'{k}={v}' for k, v in etf.items())
        p = subprocess.run([sys.executable, os.path.join(BASE, 'night', 'lookthrough.py'), '--what-if', '--castle', castle, '--net', net],
                           capture_output=True, text=True, timeout=300, cwd=BASE)
        line = next((ln.strip() for ln in p.stdout.splitlines() if ln.strip().startswith('★指定') and '網' in ln), None)
        top = [ln.strip() for ln in p.stdout.splitlines() if re.match(r'^\s+半導体連鎖', ln)]
        out[nm] = {'城（総資産に対する%）': castle, '網': net, 'lookthrough の行（そのまま）': line, '参考_今の保有の半導体連鎖': top[:1]}
    return out


def main():
    order, prox_w, prox = seats()
    FM = forms(prox)
    fw = forward(FM)
    cn = century(FM)
    tm = timing()
    cc = concentration(prox_w)
    J = fw['判定（案 − 今）']
    both = J['V 全体（個別株＝市場）']['まとめ'] == '堅い価値あり' and J['S 全体（個別株＝席の業種の写し）']['まとめ'] == '堅い価値あり'
    rec = '案（ITA 10・個別株 20）' if both else '今のまま（ITA 15・個別株 15）'
    out = {'generated': datetime.date.today().isoformat(), 'tool': 'night/alloc_check.py',
           '位置づけ': '判断の材料（事後・仮説の検定ではない）。形・判定の決まり・勧め方は計算の前にこのファイルに固定',
           '席（今の投下可・Ωの順）': order, '席の重み（個別株の中・順位の重み 5:3 を正規化）': prox_w,
           '席の業種の写し（個別株の中の比）': {k: round(v, 4) for k, v in prox.items()},
           '形（合計の比）': {k: {t: round(v, 3) for t, v in f.items()} for k, f in FM.items()},
           '勧め方': '案を勧めるのは①の全体の形が V と S の両方で『堅い価値あり』のときだけ。それ以外は今のまま。②③④は判定に使わない',
           '勧める案（決まりどおり）': rec,
           '① 4つの世界と積立の確率': fw, '② 100年の代用（市場との比）': cn, '③ 注文書の時期（目安）': tm, '④ 集中（目標の姿・ETF の中身まで）': cc}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('席', order, '写し', out['席の業種の写し（個別株の中の比）'])
    print(fw['自己検問'])
    for k, r in fw['形ごと（主）'].items():
        print(f"{k:<34} 平均{r['平均']:6.2f} 最悪{r['最悪']:6.2f} 15%以上{r['確率']:5.1f} 5%未満{r['五未満']:5.1f} ぶれ{r['ぶれ']:5.1f} 最大下落{r['最大下落']:6.1f} 世界{r['世界ごと']}")
    for nm, j in J.items():
        print(nm, '主', j['主'], 'まとめ', j['まとめ'], {v: (x['判定'], x['Δ']) for v, x in j['感度ごと'].items()})
    print('参考の条件', fw['参考_future30_options の条件（判定に使わない）'])
    for nm, d in cn.items():
        a, b = d['30年の積立（起点1965〜1995）'], d['20年の積立（起点1965〜2005）']
        print(f"{nm:<34} 30年 中央{a['中央値']} 下位10%{a['下位10%点']} 最悪{a['最悪']} 勝ち{a['市場に勝った割合']} | 20年 中央{b['中央値']} 下位10%{b['下位10%点']} 最悪{b['最悪']} 勝ち{b['市場に勝った割合']}")
    print(json.dumps(tm['今と案'], ensure_ascii=False), tm['区分(%)'])
    for nm, d in cc.items():
        print(nm, d['lookthrough の行（そのまま）'])
    print('勧める案', rec)
    print('書いた', OUT)


if __name__ == '__main__':
    main()
