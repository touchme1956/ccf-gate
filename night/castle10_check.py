#!/usr/bin/env python3
"""night/castle10_check.py — 「個別株を5％減らす案は？」（2026-10-13・ユーザーの問い）

読むだけ。門・採点・配分（portfolio.json）には触れない。判断の材料（事後・仮説の検定ではない）。
形・判定の決まり・勧め方は、計算の前にこのファイルに固定してコミットする（alloc_check と同じ作法）。

今の形（合計の比・2026-10-13）: NASDAQ100 40 / SMH 25 / ITA 5 / SHLD 5 / XLV 5 / FBT 5 / 個別株 15
  4つの世界の物差しでは etfcand の第2段と同じく SHLD を ITA で（A1 をつなげない）、FBT を XLV で代える
  （FBT の代理 FBIOX の相関 0.874 が事前登録の線 0.90 に届かない）＝ETF 側は QQQM 40 / SMH 25 / ITA 10 / XLV 10
  （QQQM＝NASDAQ100。etfcand の『今の形』と同じ）。
個別株の代え方（これからの物差しは ETF しか持たないので、個別株を ETF で代える＝alloc_check と同じ2通り）:
  V … 市場（VOO）＝銘柄を選ぶ上乗せ0・市場並みの値動き
  S … 席の業種の写し（alloc_check.seats(): 今の投下可を席の順位の重みで業種の ETF に置く。
      CW→ITA・LRCX/ASML→SMH・MSFT/GOOGL→QQQM ほか。表に無い社が席に入っていたら止まる）
  ⚠ どちらも銘柄ごとの値動き（席5社の固有のぶれ）を持たない＝個別株のぶれと下落を小さく見せる向き
    ＝個別株を減らすことの守りの効き目は、この物差しでは小さく出る
案（個別株を 15 → 10・浮いた5の行き先で3つ）:
  a … NASDAQ100 へ（QQQM 45 / SMH 25 / ITA 10 / XLV 10 / 個別株 10）
  c … ETF 側へ今の比のまま按分（QQQM 40・SMH 25・ITA 10・XLV 10 を 85 → 90 に同じ比で）
  b … GDX へ（QQQM 40 / SMH 25 / ITA 10 / XLV 10 / GDX 5 / 個別株 10）
  比べる相手 G（Q2 用）… GDX の5を NASDAQ100 から（etfcand の勧め: QQQM 35 / … / GDX 5 / 個別株 15）
物差し ①（判定に使う）: etfcand の第2段の道具そのもの（etfcand.stage2 の hook で受け取る measure・judge・show）
  ＝4つの世界 A1・A2・B・C と20年の毎月の積立の確率、感度5本（main・S2・K4・K1・K2）、
  判定の決まりは etf_ita_xlk の verdict / summarize。自己検問も etfcand のまま
  （etf_ita_xlk の席A の ITA・QQQM の行と一致しなければ止まる）。GDX の行も etfcand と同じ道（代理 FSAGX）。
勧め方（計算の前に固定）:
  Q1（主）個別株を減らして既存の ETF へ回すか … 案a・案c をそれぞれ 今 と比べ、V と S の両方で『堅い価値あり』の
    案だけを勧める（2つとも通れば main の Δ平均 の V と S の平均が大きいほう・同じなら Δ最悪 の平均）。
    通る案が無ければ『個別株は15のまま』（変える根拠がデータに無い）。
  Q2（主）GDX を足すなら5をどこから取るか … 案b − G を V と S で。両方で『堅い価値あり』なら『個別株から』を勧める。
    それ以外は『NASDAQ100 から（etfcand の勧めのまま）』と言い、データが言ったこと（価値なし・差が小さい・前提しだい）を添える。
  参考（判定に使わない）: 案b − 今（GDX の効き目を含む）・G − 今・各形の物差しそのもの。
  ②③④と銘柄ごとのぶれの目安は判定に使わない。採否はユーザー（この道具は portfolio.json を書かない）。
② 100年の代用（参考）: alloc_check と同じ置き方（NASDAQ100＝テック65%＋市場35%・SMH＝Chips・ITA＝Aero＋Guns・
   VOO＝市場・XLV＝Drugs＋MedEq＋Hlth を前月末の時価総額で加重）に GDX＝Gold（French 49・1963-07〜）を足し、
   30年（起点1965〜1995）と20年（起点1965〜2005）の毎月の積立の市場との比（中央値・下位10%点・最悪・勝った割合）。
③ 注文書の時期の目安（参考）: 今の保有（future30_xlk.holdings と同じ読み方）・値段は横ばい・売らない・
   入金は今月から state.json の pf:monthly_total、nisa.monthly_from から nisa.monthly_total_jpy。
   個別株の区分の比率が目標（15 / 10）を下回る月（＝区分の比率で新しいお金が入り始める月）。
   あわせて、持っていない席の社を先に1株ずつ買う決まり（main の castle_unowned_first）の対象になるか
   （各社の目標＝個別株%×席の中の重み×(総資産＋入金)・不足が1株の半分以上・1株が入金以下）を今月の値段で。
④ 集中（参考）: night/lookthrough.py --what-if に各形の目標の姿（ETF は SHLD・FBT を含む実際の目標・個別株は席の重み）を
   渡し、『★指定 …（網 N%）』の行の NVDA と半導体の連鎖（下限〜上限）を写す。GDX は中身が未取得なので『未取得』に乗る
   （金鉱株で半導体は持たない＝下限が正しい側）。
銘柄ごとのぶれの目安（参考）: castle_rule の根拠の『投下可5社の対 QQQM の追従のぶれ 年11%』を個別株の比率に掛けた値
   （全体の値動きに足される固有のぶれの大きさの目安・相関0と置く）。
出力: out/castle10_check.json
"""
import datetime, json, math, os, re, statistics as S, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etfcand as EC          # noqa: E402
import alloc_check as AC      # noqa: E402
import gaps_common as G       # noqa: E402
import future30 as F          # noqa: E402
import future30_xlk as FX     # noqa: E402

OUT = os.path.join(BASE, 'out', 'castle10_check.json')
SCRATCH = os.path.join(BASE, 'out', '_nx_cache', 'castle10_etfcand_unused.json')   # hook を渡すと書かれない（念のため別の場所）

ETF_NOW = {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'XLV': 10}          # 4つの世界の物差しでの今の ETF 側（etfcand の『今の形』）
ETF_A = {'QQQM': 45, 'SMH': 25, 'ITA': 10, 'XLV': 10}
ETF_C = {k: v * 90 / 85 for k, v in ETF_NOW.items()}
ETF_G = {'QQQM': 35, 'SMH': 25, 'ITA': 10, 'XLV': 10}
CASTLE_NOW, CASTLE_NEW, GDX = 15, 10, 5
# ④ 集中は実際の目標の姿（SHLD・FBT を含む）で
REAL_NOW = {'QQQM': 40, 'SMH': 25, 'ITA': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5}
TRACK_ERR = 11.0     # castle_rule の根拠: 投下可5社の対 QQQM の追従のぶれ（年%）

NAMES = {'0': '今（個別株15）', 'a': '案a 個別株10・NASDAQ100へ', 'c': '案c 個別株10・ETF側へ按分',
         'b': '案b 個別株10・GDXへ', 'G': '比べる相手G 個別株15・GDXの5をNASDAQ100から'}


def whole(etf, castle, mode, prox, gdx_key=None, gdx=0):
    f = dict(etf)
    if gdx:
        f[gdx_key] = f.get(gdx_key, 0) + gdx
    if mode == 'V':
        f['VOO'] = f.get('VOO', 0) + castle
    else:
        for k, v in prox.items():
            f[k] = f.get(k, 0) + castle * v
    return f


def make_forms(prox, gdx_key):
    out = {}
    for mode in ('V', 'S'):
        out[mode + '0'] = whole(ETF_NOW, CASTLE_NOW, mode, prox)
        out[mode + 'a'] = whole(ETF_A, CASTLE_NEW, mode, prox)
        out[mode + 'c'] = whole(ETF_C, CASTLE_NEW, mode, prox)
        out[mode + 'b'] = whole(ETF_NOW, CASTLE_NEW, mode, prox, gdx_key, GDX)
        out[mode + 'G'] = whole(ETF_G, CASTLE_NOW, mode, prox, gdx_key, GDX)
    return out


PAIRS = {   # 名前 → (形, 相手)
    'Q1 案a − 今（V 個別株＝市場）': ('Va', 'V0'), 'Q1 案a − 今（S 席の業種の写し）': ('Sa', 'S0'),
    'Q1 案c − 今（V 個別株＝市場）': ('Vc', 'V0'), 'Q1 案c − 今（S 席の業種の写し）': ('Sc', 'S0'),
    'Q2 案b − G（V 個別株＝市場）': ('Vb', 'VG'), 'Q2 案b − G（S 席の業種の写し）': ('Sb', 'SG'),
    '参考 案b − 今（V）': ('Vb', 'V0'), '参考 案b − 今（S）': ('Sb', 'S0'),
    '参考 G − 今（V）': ('VG', 'V0'), '参考 G − 今（S）': ('SG', 'S0'),
}


def forward(prox):
    def hook(ctx):
        gk = [k for fid, k in ctx['fam_rows'].items() if (ctx['infos'].get(fid) or {}).get('t') == 'GDX']
        if len(gk) != 1:
            raise SystemExit(f'✗ etfcand の第2段に GDX の行が1本でない（{gk}）＝測れない')
        gkey = gk[0]
        FM = make_forms(prox, gkey)
        meas = {k: ctx['measure'](f) for k, f in FM.items()}
        rows = {k: ctx['show'](m) for k, m in meas.items()}
        jud = {nm: ctx['judge'](meas[a], meas[b]) for nm, (a, b) in PAIRS.items()}
        return dict(gdx_key=gkey, gdx_info={k: v for k, v in (ctx['infos'].get([fid for fid, k in ctx['fam_rows'].items() if k == gkey][0]) or {}).items()
                                            if k != '代理の候補の相関'},
                    forms={k: {t: round(v, 3) for t, v in f.items()} for k, f in FM.items()}, rows=rows, judge=jud,
                    self_check=ctx['self_check'], base_w=ctx['base_w'])
    return EC.stage2(src=EC.OUT, dst=SCRATCH, posthoc_on=False, hook=hook, extra_assets=('VOO',))


def decide(J):
    q1 = {}
    for x in ('a', 'c'):
        v = J[f'Q1 案{x} − 今（V 個別株＝市場）']; s = J[f'Q1 案{x} − 今（S 席の業種の写し）']
        ok = v['まとめ'] == '堅い価値あり' and s['まとめ'] == '堅い価値あり'
        dm = (v['感度ごと']['main']['Δ']['平均'] + s['感度ごと']['main']['Δ']['平均']) / 2
        dw = (v['感度ごと']['main']['Δ']['最悪'] + s['感度ごと']['main']['Δ']['最悪']) / 2
        q1[x] = dict(通る=ok, V=v['まとめ'], S=s['まとめ'], Δ平均の平均=round(dm, 3), Δ最悪の平均=round(dw, 3))
    passing = sorted([x for x in q1 if q1[x]['通る']], key=lambda x: (-q1[x]['Δ平均の平均'], -q1[x]['Δ最悪の平均']))
    rec1 = (NAMES[passing[0]] + 'を勧める') if passing else '個別株は15のまま（変える根拠がデータに無い）'
    v = J['Q2 案b − G（V 個別株＝市場）']; s = J['Q2 案b − G（S 席の業種の写し）']
    if v['まとめ'] == '堅い価値あり' and s['まとめ'] == '堅い価値あり':
        rec2 = 'GDX の5は個別株から取る（案b）を勧める'
    else:
        rec2 = f"GDX の5は NASDAQ100 から（etfcand の勧めのまま）——案b − G は V『{v['まとめ']}』（主 {v['主']}）・S『{s['まとめ']}』（主 {s['主']}）"
    return dict(Q1=q1, Q1の勧め=rec1, Q2=dict(V=v['まとめ'], S=s['まとめ'], V主=v['主'], S主=s['主']), Q2の勧め=rec2)


def century(prox):
    cols, ret, capm, me, be, share, mkt = F.load()
    endm = max(mkt)
    tech = G.french_tech()
    allm = sorted(mkt)
    parts = {'QQQM': F.mix([(0.65, tech), (0.35, mkt)], allm), 'SMH': ret['Chips'],
             'ITA': F.capw(ret, capm, ['Aero', 'Guns'], allm), 'VOO': mkt,
             'XLV': F.capw(ret, capm, ['Drugs', 'MedEq', 'Hlth'], allm), 'GDX': ret['Gold']}
    FM = {}
    for mode in ('V', 'S'):
        FM[mode + '0'] = whole(ETF_NOW, CASTLE_NOW, mode, prox)
        FM[mode + 'a'] = whole(ETF_A, CASTLE_NEW, mode, prox)
        FM[mode + 'c'] = whole(ETF_C, CASTLE_NEW, mode, prox)
        FM[mode + 'b'] = whole(ETF_NOW, CASTLE_NEW, mode, prox, 'GDX', GDX)
        FM[mode + 'G'] = whole(ETF_G, CASTLE_NOW, mode, prox, 'GDX', GDX)
    out = {}
    for nm, f in FM.items():
        tw = sum(f.values())
        s = F.mix([(w / tw, parts[k]) for k, w in f.items() if w > 0], allm)
        d = {}
        for n, lab, starts in ((360, '30年の積立（起点1965〜1995）', range(1965, 1996)),
                               (240, '20年の積立（起点1965〜2005）', range(1965, 2006))):
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
                      '市場に勝った割合': round(sum(x > 1 for x in xs) / len(xs), 2)}
        out[nm] = d
    return out


def timing(order, prox_w):
    h, buckets, tot = FX.holdings()
    st = json.load(open(os.path.join(BASE, 'state.json')))
    d = st.get('data') or st
    tg = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    num = lambda x: int(float(str(x).replace(',', ''))) if x not in (None, '') else 0
    m0 = num(d.get('pf:monthly_total'))
    m1 = num((tg.get('nisa') or {}).get('monthly_total_jpy')) or m0
    start = int((tg.get('nisa') or {}).get('monthly_from', '2027-01').replace('-', ''))
    held = buckets.get('個別株', 0)
    res = {}
    for pct in (CASTLE_NOW, CASTLE_NEW):
        m, cum, hit = 202610, 0, None
        for i in range(1, 481):
            cum += m1 if m >= start else m0
            if held / (tot + cum) < pct / 100:
                hit = (i, m)
                break
            m = G.add_months(m, 1)
        res[f'個別株{pct}%'] = None if not hit else f'{hit[0]}か月目（{hit[1] // 100}-{hit[1] % 100:02d}）'
    dash = json.load(open(os.path.join(BASE, 'out', 'dashboard.json')))
    fx = float(dash['fx']['USDJPY'])
    owned = {r['t'] for r in h['銘柄']}
    uf = {}
    for pct in (CASTLE_NOW, CASTLE_NEW):
        rows = []
        for t in order:
            if t in owned:
                rows.append(dict(t=t, 持っている=True))
                continue
            px = float(dash['quotes'][t]['px']) * fx
            tgt = pct / 100 * prox_w[t] * (tot + m0)
            rows.append(dict(t=t, 目標の円=round(tgt), 一株の円=round(px), 対象=bool(tgt >= 0.5 * px and px <= m0)))
        uf[f'個別株{pct}%'] = rows
    return {'保有の日（株数）': h['保有の日（株数）'], '価格の日': h['価格の日'], 'ドル円': fx, '総額(円)': tot,
            '個別株(円)': held, '個別株(%)': round(100 * held / tot, 1),
            '入金の前提': f'今月から毎月 ¥{m0:,}、{start // 100}-{start % 100:02d} から ¥{m1:,}・値段は横ばい・売らない',
            '区分の比率で新しいお金が入り始める月': res,
            '持っていない席の社を先に1株（castle_unowned_first・今月の値段）': uf}


def concentration(prox_w):
    specs = {'今': (REAL_NOW, CASTLE_NOW, 0), '案a': ({**REAL_NOW, 'QQQM': 45}, CASTLE_NEW, 0),
             '案c': ({k: v * 90 / 85 for k, v in REAL_NOW.items()}, CASTLE_NEW, 0),
             '案b': (REAL_NOW, CASTLE_NEW, GDX), 'G': ({**REAL_NOW, 'QQQM': 35}, CASTLE_NOW, GDX)}
    out = {}
    for nm, (net, c, gdx) in specs.items():
        castle = ','.join(f'{t}={c * w:.3f}' for t, w in prox_w.items())
        nets = dict(net)
        if gdx:
            nets['GDX'] = gdx
        spec = ','.join(f'{k}={v:.3f}' for k, v in nets.items())
        p = subprocess.run([sys.executable, os.path.join(BASE, 'night', 'lookthrough.py'), '--what-if', '--castle', castle, '--net', spec],
                           capture_output=True, text=True, timeout=300, cwd=BASE)
        line = next((ln.strip() for ln in p.stdout.splitlines() if re.match(r'^★指定 \S+（網 \d+%）', ln.strip())), None)
        if not line:
            raise SystemExit('✗ lookthrough の what-if の『★指定 …（網 N%）』の行が見つからない＝出力の形が変わった')
        mm = re.search(r'NVDA\s+([\d.]+)%\s*⛔?', line.split('件')[-1]) or re.search(r'NVDA\s+([\d.]+)%', line)
        semi = re.search(r'([\d.]+)〜\s*([\d.]+)%', line)
        out[nm] = {'城（総資産に対する%）': castle, '網（総資産に対する%）': spec, 'lookthrough の行（そのまま）': line,
                   'NVDA(%)': float(mm.group(1)) if mm else None,
                   '半導体の連鎖(%)': [float(semi.group(1)), float(semi.group(2))] if semi else None}
    return out


def main():
    order, prox_w, prox = AC.seats()
    fw = forward(prox)
    dec = decide(fw['judge'])
    cn = century(prox)
    tm = timing(order, prox_w)
    cc = concentration(prox_w)
    te = {f'個別株{p}%': round(p / 100 * TRACK_ERR, 2) for p in (CASTLE_NOW, CASTLE_NEW)}
    out = {'generated': datetime.date.today().isoformat(), 'tool': 'night/castle10_check.py',
           '位置づけ': '判断の材料（事後・仮説の検定ではない）。形・判定の決まり・勧め方は計算の前にこのファイルに固定',
           '席（今の投下可・Ωの順）': order, '席の重み（個別株の中）': prox_w,
           '席の業種の写し（個別株の中の比）': {k: round(v, 4) for k, v in prox.items()},
           '形の名前': NAMES, '4つの世界の今の ETF 側（etfcand の今の形）': fw['base_w'], 'GDX の行': fw['gdx_info'],
           '自己検問': fw['self_check'],
           '形（合計の比）': fw['forms'], '形ごとの物差し（主）': fw['rows'], '判定': fw['judge'],
           '勧め（決まりどおり）': dec,
           '② 100年の代用（市場との比）': cn, '③ 注文書の時期（目安）': tm, '④ 集中（目標の姿・ETF の中身まで）': cc,
           '銘柄ごとのぶれの目安（年%・全体に足される固有のぶれ・相関0）': te}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('席', order, '写し', out['席の業種の写し（個別株の中の比）'])
    for k, r in fw['rows'].items():
        print(f"{k:<3} {NAMES[k[1]]:<34} 平均{r['平均']:6.2f} 最悪{r['最悪']:6.2f} 15%以上{r['確率']:5.1f} 5%未満{r['五未満']:5.1f} "
              f"ぶれ{r['ぶれ']:5.1f} 最大下落{r['最大下落']:6.1f} 過去20年{r['過去20年で15%以上']:5.1f} 世界{r['世界ごと']}")
    for nm, j in fw['judge'].items():
        print(f"{nm:<30} 主 {j['主']:6} まとめ {j['まとめ']:10} Δ{j['感度ごと']['main']['Δ']} 感度{[j['感度ごと'][v]['判定'] for v in j['感度ごと']]}")
    print('勧め', json.dumps(dec, ensure_ascii=False))
    for nm, d in cn.items():
        a, b = d['30年の積立（起点1965〜1995）'], d['20年の積立（起点1965〜2005）']
        print(f"{nm:<3} 30年 中央{a['中央値']} 下位10%{a['下位10%点']} 最悪{a['最悪']} 勝ち{a['市場に勝った割合']} | "
              f"20年 中央{b['中央値']} 下位10%{b['下位10%点']} 最悪{b['最悪']} 勝ち{b['市場に勝った割合']}")
    print(json.dumps(tm, ensure_ascii=False))
    for nm, d in cc.items():
        print(nm, d['NVDA(%)'], d['半導体の連鎖(%)'], '|', d['lookthrough の行（そのまま）'])
    print('固有のぶれの目安', te)
    print('書いた', OUT)


if __name__ == '__main__':
    main()
