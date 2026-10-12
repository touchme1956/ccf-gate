#!/usr/bin/env python3
"""night/health_etf.py — ヘルスケア・高齢化の ETF（2026-10-11・ユーザー「ヘルスケア・高齢化ETFは？」）

読むだけ。門・採点・配分には触れない。事前登録 out/health_prereg.json（3d2bc1b・測る前に固定）どおり。
  第1部 XLV を今の形に入れる価値（ITA・SCHD と同じ4つの世界と判定の決まり・感度5本）
        J1 席A（QQQM 50 / SMH 20 / X 15）で XLV − NASDAQ100 ／ J2 席Aで XLV − ITA ／
        J3 席D（今の形 QQQM 50 / SMH 20 / ITA 15 から NASDAQ100 の10を XLV へ）− 今の形
  第2部 器の比べ（楽天で買えるヘルスケアの ETF で XLV より良い器があるか・defense_alts と同じ形の決まり）
  第3部 100年の代用（French の Drugs・MedEq・Hlth・参考）
  第4部 日本の投資信託（投信ライブラリーの写真・記述）
計算の部品は morefunds（seat_metrics・row_of・judge・p15_tables）と future30 をそのまま使う（二重に書かない）。
出力: out/health_etf.json
"""
import datetime, json, math, os, re, statistics as S, sys, time, unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_forward_combo as CB    # noqa: E402
import etf_ita_xlk as IX          # noqa: E402
import morefunds as MF            # noqa: E402
import mw_common as M             # noqa: E402
import gaps_common as G           # noqa: E402
import future30 as F              # noqa: E402

OUT = os.path.join(BASE, 'out', 'health_etf.json')
PREREG = 'out/health_prereg.json（3d2bc1b）'
END = 202609
NOW = {'QQQM': 50, 'SMH': 20, 'ITA': 15}
FORMS = {'今の形（QQQM 50 / SMH 20 / ITA 15）': NOW,
         'D10 今の形から NASDAQ100 の10を XLV へ': {'QQQM': 40, 'SMH': 20, 'ITA': 15, 'XLV': 10},
         '参考 D5（NASDAQ100 の5だけ）': {'QQQM': 45, 'SMH': 20, 'ITA': 15, 'XLV': 5},
         '参考 半分ずつ（ITA 7.5 / XLV 7.5）': {'QQQM': 50, 'SMH': 20, 'ITA': 7.5, 'XLV': 7.5}}
VEH = {'XLV': 0.08, 'VHT': 0.09, 'IXJ': 0.38, 'IBB': 0.44, 'BBH': 0.35, 'PPH': 0.35, 'FBT': 0.56, 'FXH': 0.61,
       'GNOM': 0.50, 'HEAL': 0.56}   # 楽天の一覧（out/broker_lineup.json）の経費率 %
VEH_JA = {'XLV': '米国ヘルスケア（S&P500 のヘルスケア部門）', 'VHT': '米国ヘルスケア（全米）', 'IXJ': '世界のヘルスケア',
          'IBB': 'バイオ（時価総額加重）', 'BBH': 'バイオ（25社）', 'PPH': '製薬（25社）', 'FBT': 'バイオ（等加重）',
          'FXH': 'ヘルスケア（AlphaDEX の選別）', 'GNOM': 'ゲノム（テーマ）', 'HEAL': 'ヘルステック（テーマ）'}
JP_PAT = re.compile(r'(ヘルスケア|医療|メディカル|バイオ|高齢|長寿|ライフサイエンス|ヘルス)')
JITA = os.path.join(BASE, 'out', '_nx_cache', 'newfunds', 'jita_full.json')


# ───────────────────────── 第1部 ─────────────────────────
def part1():
    t0 = time.time()
    ctx = CB.build(max_k=1)
    tabs = MF.p15_tables()
    Sx = MF.seat_metrics(ctx, tabs, FORMS)
    # 自己検問: 席Aの XLV・ITA・NASDAQ100 は etf_ita_xlk.json と同じ数字になるはず
    tabA = json.load(open(os.path.join(BASE, 'out', 'etf_ita_xlk.json')))['slots']['A']['table']
    for x in ('XLV', 'ITA', 'QQQM'):
        mine = MF.row_of(Sx, x)
        for k in ('平均', '最悪', '確率', 'ぶれ', '最大下落'):
            assert abs(mine[k] - tabA[x][k]) < 0.011, ('席Aの数字が etf_ita_xlk.json と食い違う', x, k, mine[k], tabA[x][k])
    now_k = '今の形（QQQM 50 / SMH 20 / ITA 15）'
    # 今の形の行は席Aの ITA の行と同じはず
    a, b = MF.row_of(Sx, now_k), MF.row_of(Sx, 'ITA')
    assert all(abs(a[k] - b[k]) < 1e-9 for k in ('平均', '最悪', '確率', 'ぶれ', '最大下落')), ('今の形と席Aの ITA が違う', a, b)
    J1 = MF.judge(Sx, 'XLV', 'QQQM')
    J2 = MF.judge(Sx, 'XLV', 'ITA')
    J3 = MF.judge(Sx, 'D10 今の形から NASDAQ100 の10を XLV へ', now_k)
    J3b = MF.judge(Sx, '参考 D5（NASDAQ100 の5だけ）', now_k)
    Jh = MF.judge(Sx, '参考 半分ずつ（ITA 7.5 / XLV 7.5）', now_k)
    for var in IX.VARS:
        J1['感度ごと'][var].update(XLV=MF.row_of(Sx, 'XLV', var), NASDAQ100=MF.row_of(Sx, 'QQQM', var))
        J2['感度ごと'][var].update(XLV=MF.row_of(Sx, 'XLV', var), ITA=MF.row_of(Sx, 'ITA', var))
        J3['感度ごと'][var].update(D10=MF.row_of(Sx, 'D10 今の形から NASDAQ100 の10を XLV へ', var), 今の形=MF.row_of(Sx, now_k, var))
    if J3['まとめ'] == '堅い価値あり':
        concl = 'NASDAQ100 から10を XLV へ（J3 が堅い価値あり）を勧める'
    elif J2['まとめ'] == '堅い価値あり':
        concl = 'ITA を XLV に替える（J2 が堅い価値あり）を勧める'
    else:
        concl = f'今のまま（J2 {J2["まとめ"]}・J3 {J3["まとめ"]}＝決まりの『堅い価値あり』に届かない）'
    C = CB.CANDS
    mm = Sx['met']['main']
    rank = {lab: 1 + sorted(C, key=lambda x: -float(mm[key][Sx['idx'][x]])).index('XLV') for lab, key in
            (('平均', 'mean'), ('最悪', 'worst'), ('確率', 'p15'))}
    print(f'J1 {J1["主"]}/{J1["まとめ"]}  J2 {J2["主"]}/{J2["まとめ"]}  J3 {J3["主"]}/{J3["まとめ"]}（{time.time() - t0:.0f}秒）', flush=True)
    return {'決まり': json.load(open(os.path.join(BASE, 'out', 'health_prereg.json')))['第1部 XLV を今の形に入れる価値（主の判定）']['判定の決まり'],
            'J1 XLV を入れる価値（席A・XLV − NASDAQ100）': J1,
            'J2 ITA を XLV に替えるか（席A・XLV − ITA）': J2,
            'J3 ITA を残して足すか（席D・NASDAQ100 の10を XLV − 今の形）': J3,
            '参考 D5（NASDAQ100 の5を XLV − 今の形）': J3b,
            '参考 半分ずつ（ITA 7.5 / XLV 7.5 − 今の形）': Jh,
            '形ごとの物差し（主）': {k: MF.row_of(Sx, k) for k in list(FORMS) + ['XLV', 'QQQM']},
            '席Aでの XLV の順位（21本中）': rank,
            '結論（事前登録の決まり）': concl}


# ───────────────────────── 第2部 ─────────────────────────
def cagr(r, ms):
    return math.prod(1 + r[m] for m in ms) ** (12 / len(ms)) - 1


def mdd(r, ms):
    v = pk = 1.0
    worst = 0.0
    for m in ms:
        v *= 1 + r[m]
        pk = max(pk, v)
        worst = min(worst, v / pk - 1)
    return worst


def vol(r, ms):
    xs = [r[m] for m in ms]
    mu = sum(xs) / len(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) * math.sqrt(12)


def corr(a, b, ms):
    xa, xb = [a[m] for m in ms], [b[m] for m in ms]
    ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
    num = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
    return num / math.sqrt(sum((x - ma) ** 2 for x in xa) * sum((y - mb) ** 2 for y in xb))


def part2():
    tick = list(VEH) + ['QQQ', 'SMH', 'SPY']
    R = {t: M.yahoo(t) for t in tick}
    rows = {}
    for t in VEH:
        first = min(R[t])
        yrs = round(((END // 100) * 12 + END % 100 - ((first // 100) * 12 + first % 100) + 1) / 12, 1)
        common = sorted(m for m in set(R[t]) & set(R['XLV']) & set(R['QQQ']) & set(R['SMH']) & set(R['SPY']) if m <= END)
        shape = lambda x: {m: (50 * R['QQQ'][m] + 20 * R['SMH'][m] + 15 * R[x][m]) / 85 for m in common}
        sx, sv = shape(t), shape('XLV')
        d = {'中身': VEH_JA[t], '経費率(%)': VEH[t], '最初の月': first, '記録の年数': yrs, '共通の窓': f'{common[0]}〜{common[-1]}',
             '単体': {'年率(%)': round(100 * cagr(R[t], common), 2), 'ぶれ(%)': round(100 * vol(R[t], common), 1),
                    '最大下落(%)': round(100 * mdd(R[t], common), 1), 'SPY との年率の差(%/年)': round(100 * (cagr(R[t], common) - cagr(R['SPY'], common)), 2),
                    'QQQ との相関': round(corr(R[t], R['QQQ'], common), 2), 'XLV との相関': round(corr(R[t], R['XLV'], common), 2)},
             '席Aの形（QQQ 50 : SMH 20 : X 15）': {'年率(%)': round(100 * cagr(sx, common), 2), '最大下落(%)': round(100 * mdd(sx, common), 1)},
             '同じ窓の XLV の形': {'年率(%)': round(100 * cagr(sv, common), 2), '最大下落(%)': round(100 * mdd(sv, common), 1)}}
        if t == 'XLV':
            d['結論'] = '今の代表'
        else:
            r2 = yrs >= 10
            diff = 100 * (cagr(sx, common) - cagr(sv, common))
            r3 = diff > 0 and mdd(sx, common) > mdd(sv, common)
            r4 = diff > max(0.0, VEH[t] - VEH['XLV'])
            d.update({'(2) 自分の記録10年以上': '○' if r2 else '×', '(3) 形の年率が上 ∧ 最大下落が浅い': '○' if r3 else '×',
                      '(4) 年率の差が経費率の差を超える': '○' if r4 else '×', '形の年率の差(%/年)': round(diff, 2)})
            d['結論'] = ('判定できない（(2)・記録が短い）' if not r2 else
                       'XLV の代わりの候補' if (r3 and r4) else 'XLV のまま（(3)か(4)を満たさない）')
        rows[t] = d
    cands = [t for t, v in rows.items() if v['結論'] == 'XLV の代わりの候補']
    print('第2部', {t: v['結論'] for t, v in rows.items()}, flush=True)
    return {'表': rows, '代わりの候補': cands,
            '判定': ('XLV が代表のまま（楽天で買える他のヘルスケアの器で決まりを満たすものは無い）' if not cands
                     else f'XLV の代わりの候補: {"・".join(cands)}（第1部の判定は XLV で行った）')}


# ───────────────────────── 第3部 ─────────────────────────
def part3():
    cols, ret, capm, me, be, share, mkt = F.load()
    endm = max(mkt)
    tech = G.french_tech()
    allm = sorted(mkt)
    ndx = F.mix([(0.65, tech), (0.35, mkt)], allm)
    dfn = F.capw(ret, capm, ['Aero', 'Guns'], allm)
    hc = F.capw(ret, capm, ['Drugs', 'MedEq', 'Hlth'], allm)
    chips = ret['Chips']
    forms = {'今の目標（NASDAQ100 50・SMH 20・ITA 15・個別株 15）': [(0.50, ndx), (0.20, chips), (0.15, dfn), (0.15, mkt)],
             'その他＝ヘルスケア（ITA の代わり）': [(0.50, ndx), (0.20, chips), (0.15, hc), (0.15, mkt)],
             '今の形＋ヘルスケア10（NASDAQ100 から）': [(0.40, ndx), (0.20, chips), (0.15, dfn), (0.10, hc), (0.15, mkt)],
             'ヘルスケアだけ': [(1.0, hc)]}
    out = {}
    for nm, parts in forms.items():
        s = F.mix(parts, allm)
        d = {}
        for n, lab, starts in ((360, '30年の積立（起点1965〜1995）', range(1965, 1996)), (240, '20年の積立（起点1965〜2005）', range(1965, 2006))):
            v = []
            for y in starts:
                ms = F.months((y + 1) * 100 + 1, n)
                if ms[-1] > endm:
                    continue
                a, b = F.dca_mult(s, ms), F.dca_mult(mkt, ms)
                if a and b:
                    v.append(a / b)
            v.sort()
            q = lambda p: v[min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))]
            d[lab] = {'窓': len(v), '中央値': round(S.median(v), 3), '市場に勝った割合': round(sum(x > 1 for x in v) / len(v), 2),
                      '下位10%点': round(q(0.10), 3), '最悪': round(v[0], 3)}
        out[nm] = d
    sh = {}
    for y in (1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020, 2025):
        sh[str(y)] = round(100 * sum(share[c].get(y, 0) for c in ('Drugs', 'MedEq', 'Hlth')), 1)
    dec = {}
    for a in range(1930, 2030, 10):
        ms = [m for m in allm if a * 100 + 1 <= m <= min((a + 9) * 100 + 12, endm) and m in hc]
        if len(ms) >= 24:
            dec[f'{a}年代' if a < 2020 else '2020〜2026-08'] = round(100 * (cagr(hc, ms) - cagr(mkt, ms)), 1)
    ms_all = [m for m in allm if m in hc]
    full = round(100 * (cagr(hc, ms_all) - cagr(mkt, ms_all)), 2)
    print('第3部', {k: (v['30年の積立（起点1965〜1995）']['中央値'], v['30年の積立（起点1965〜1995）']['最悪']) for k, v in out.items()}, flush=True)
    return {'形ごと（市場との比）': out, 'ヘルスケアの比重の推移(%・12月末)': sh,
            '10年ごとの市場との年率の差(%/年)': dec, f'全期間（{ms_all[0]}〜{ms_all[-1]}）の市場との年率の差(%/年)': full}


# ───────────────────────── 第4部 ─────────────────────────
def nfkc(s):
    return unicodedata.normalize('NFKC', s or '')


def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def rets(r):
    """投信ライブラリーの standardPriceRaNy は累計の騰落率（%）——eMAXIS Slim 米国株式（S&P500）の5年が 162.23 で確かめた。年率に直して両方出す"""
    o = {}
    for n in (5, 10):
        c = fnum(r.get(f'standardPriceRa{n}y'))
        o[f'{n}年の騰落率（累計%）'] = c
        o[f'{n}年の年率(%)'] = None if c is None else round(100 * ((1 + c / 100) ** (1 / n) - 1), 1)
    return o


BENCH_JP = ('iシェアーズ米国株式(S&P500)インデックス・ファンド', 'NEXT FUNDS NASDAQ-100(為替ヘッジなし)連動型上場投信')


def part4():
    d = json.load(open(JITA))
    rows = d if isinstance(d, list) else next(v for v in d.values() if isinstance(v, list))
    out = []
    for r in rows:
        n = nfkc(r.get('fundNm'))
        if not JP_PAT.search(n):
            continue
        if re.search(r'(ブル|ベア|レバレッジ|インバース)', n):
            continue
        tsumi, grow = r.get('nisaFlg') == '1', r.get('nisaGrowthFlg') == '1'
        if not (tsumi or grow):
            continue
        rak = any('楽天' in nfkc(i.get('instName')) for i in (r.get('institutionInfo') or []))
        fee = fnum(r.get('trustReward'))
        out.append(dict(名前=n, NISA='・'.join((['つみたて'] if tsumi else []) + (['成長'] if grow else [])), 楽天で売っている=rak,
                        **{'信託報酬（税込%）': None if fee is None else round(fee * 1.1, 3),
                           '純資産（億円）': None if fnum(r.get('totalNetAssets')) is None else round(fnum(r.get('totalNetAssets')) / 100, 1),
                           '設定日': (r.get('establishedDate') or '')[:10], '毎月決算': r.get('setlFqcy') == '012'}, **rets(r)))
    out.sort(key=lambda x: -(x['純資産（億円）'] or 0))
    bench = {}
    for r in rows:
        n = nfkc(r.get('fundNm'))
        if n in BENCH_JP:
            bench[n] = dict(**{'信託報酬（税込%）': None if fnum(r.get('trustReward')) is None else round(fnum(r.get('trustReward')) * 1.1, 3)}, **rets(r))
    print('第4部', len(out), '本', flush=True)
    return {'出典': '投信総合検索ライブラリーの写真（2026-10-09・out/_nx_cache/newfunds/jita_full.json）', '本数': len(out),
            'つみたて投資枠の印がある本数': sum('つみたて' in x['NISA'] for x in out),
            '比べる相手（同じ写真・指数型）': bench, '一覧（純資産の大きい順）': out,
            '注': '騰落率は投信ライブラリーの累計（standardPriceRa5y/10y・分配金込み）を年率に直した値も併記。信託報酬は税抜×1.1'}


def posthoc_core_rule(p1):
    """事後（判定に使わない）: 30年の構造の案を勧めた決まり（future30_options・更新する芯の案に使った）に席Dを当てるとどうなるか"""
    fo = json.load(open(os.path.join(BASE, 'out', 'future30_options.json')))
    rows = fo['物差し①②_4つの世界と積立の確率（ETF 側・個別株15%は除く）']
    o0 = rows['O0 今']
    out = {'決まり（future30_options）': fo['勧め方']}
    for k in ('D10 今の形から NASDAQ100 の10を XLV へ', '参考 D5（NASDAQ100 の5だけ）'):
        r = p1['形ごとの物差し（主）'][k]
        ok = r['確率'] >= o0['確率_15以上'] - 3 and r['最悪'] > o0['年率_最悪の世界'] and r['五未満'] < o0['確率_5未満']
        out[k] = {'15%以上': r['確率'], '最悪の世界': r['最悪'], '5%未満': r['五未満'], '最大下落': r['最大下落'], '条件を満たすか': bool(ok)}
    for k in ('O1 芯10（SMH から）', 'O3 芯30'):
        r = rows[k]
        out[k] = {'15%以上': r['確率_15以上'], '最悪の世界': r['年率_最悪の世界'], '5%未満': r['確率_5未満'], '最大下落': r['最大下落']}
    out['今'] = {'15%以上': o0['確率_15以上'], '最悪の世界': o0['年率_最悪の世界'], '5%未満': o0['確率_5未満'], '最大下落': o0['最大下落']}
    return out


def main():
    out = {'generated': datetime.date.today().isoformat(), 'tool': 'night/health_etf.py', 'prereg': PREREG}
    out['第1部 XLV を今の形に入れる価値'] = part1()
    out['第2部 器の比べ'] = part2()
    out['第3部 100年の代用（参考）'] = part3()
    out['第4部 日本の投資信託（記述）'] = part4()
    out['事後 30年の構造の決まりに当てたら（判定に使わない）'] = posthoc_core_rule(out['第1部 XLV を今の形に入れる価値'])
    out['⚠'] = json.load(open(os.path.join(BASE, 'out', 'health_prereg.json')))['注意（測る前から分かっている限界）']
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('書いた', OUT)


if __name__ == '__main__':
    main()
