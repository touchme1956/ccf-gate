#!/usr/bin/env python3
"""night/industry_trends.py — 業種ごとの売上の伸び・利益率・投資の強さを自動で集計する（読むだけ）

ユーザー指示（2026-09-28）「業種ごとの成長率や財務や売り上げの成長などを自動分析して今後伸びる業種を、みていくツールが欲しい」。
事前登録: out/industry_trends_prereg.json（物差しと答え合わせの決まりは測る前に固定した）

データ（鍵なし・CIで回る）:
  - SEC XBRL frames（us-gaap・年次 CYyyyy／自己資本は CYyyyyQ4I）…売上・営業利益・純利益・営業CF・設備投資・研究開発費
  - SEC submissions …各社の SIC（out/sic_by_cik.json に貯めて、新しい社だけ取りに行く）
  - Ken French: Siccodes49（SIC→49業種）と 49業種の月次リターン（時価加重）

出力: out/industry_trends.json（門の industry.html が読む）
使い方: python3 night/industry_trends.py [--no-fetch]   （--no-fetch は手元の frames のキャッシュだけで回す）
"""
import io, json, math, os, sys, time, zipfile, datetime, urllib.request, statistics as S
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from tech_persist import block, cagr as rcagr, spear  # 同じ French の読み方・順位相関を使う（二重実装を作らない）

EMAIL = "fortis5280@gmail.com"
HDRS = {"User-Agent": f"hachimon-gate research {EMAIL}"}
CACHE = os.path.join(BASE, 'out', '_frames_cache')
SICF = os.path.join(BASE, 'out', 'sic_by_cik.json')
OUT = os.path.join(BASE, 'out', 'industry_trends.json')
FR = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}.zip'

# 売上のタグは「代替」＝同じものを会社ごとに別の名前で出している。同じ社・同じタグの2年でだけ成長を測る
REV_TAGS = ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet',
            'RevenueFromContractWithCustomerIncludingAssessedTax']
FLOW = {'oi': 'OperatingIncomeLoss', 'ni': 'NetIncomeLoss', 'ocf': 'NetCashProvidedByUsedInOperatingActivities',
        'capex': 'PaymentsToAcquirePropertyPlantAndEquipment', 'rd': 'ResearchAndDevelopmentExpense'}
MIN_REV = 50e6
Y0 = 2009

JA = {'Agric': '農業', 'Food': '食品', 'Soda': '清涼飲料', 'Beer': '酒類', 'Smoke': 'たばこ', 'Toys': '玩具・娯楽用品',
      'Fun': '娯楽', 'Books': '出版・印刷', 'Hshld': '家庭用品', 'Clths': '衣料', 'Hlth': '医療サービス', 'MedEq': '医療機器',
      'Drugs': '医薬品', 'Chems': '化学', 'Rubbr': 'ゴム・樹脂', 'Txtls': '繊維', 'BldMt': '建材', 'Cnstr': '建設',
      'Steel': '鉄鋼', 'FabPr': '金属加工', 'Mach': '機械', 'ElcEq': '電気機器', 'Autos': '自動車', 'Aero': '航空機',
      'Ships': '造船・鉄道車両', 'Guns': '防衛', 'Gold': '貴金属', 'Mines': '鉱業', 'Coal': '石炭', 'Oil': '石油・ガス',
      'Util': '公益', 'Telcm': '通信', 'PerSv': '個人向けサービス', 'BusSv': '企業向けサービス', 'Hardw': 'コンピュータ機器',
      'Softw': 'ソフトウェア', 'Chips': '半導体・電子部品', 'LabEq': '計測・分析機器', 'Paper': '紙', 'Boxes': '包装',
      'Trans': '運輸', 'Whlsl': '卸売', 'Rtail': '小売', 'Meals': '外食・ホテル', 'Banks': '銀行', 'Insur': '保険',
      'RlEst': '不動産', 'Fin': '金融（その他）', 'Other': 'その他'}


def get(url, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=90).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** i)
        except Exception:
            time.sleep(2 ** i)
    return None


def frame(tag, period, fetch=True):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, f'{tag}_{period}.json')
    if os.path.exists(fn) and (not fetch or time.time() - os.path.getmtime(fn) < 20 * 86400):
        return json.load(open(fn))
    if not fetch:
        return []
    raw = get(f'https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json')
    time.sleep(0.15)
    data = [{'cik': e['cik'], 'name': e.get('entityName', ''), 'val': e['val']} for e in json.loads(raw)['data']] if raw else []
    json.dump(data, open(fn, 'w'))
    return data


def ff49_map():
    z = zipfile.ZipFile(io.BytesIO(get(FR.format('Siccodes49'))))
    L = z.read(z.namelist()[0]).decode('latin-1').split('\n')
    rng, cur = [], None
    for l in L:
        s = l.strip()
        if not s:
            continue
        p = s.split()
        if p[0].isdigit() and len(p) >= 2 and not ('-' in p[0]):
            cur = p[1]
        elif '-' in p[0] and cur:
            a, b = p[0].split('-')
            if a.isdigit() and b.isdigit():
                rng.append((int(a), int(b), cur))
    def f(sic):
        for a, b, k in rng:
            if a <= sic <= b:
                return k
        return 'Other'
    return f


def sic_map(ciks, fetch=True):
    m = json.load(open(SICF)) if os.path.exists(SICF) else {}
    # 既存の銘柄キャッシュ（ティッカー→cik・sic）から先に埋める
    old = os.path.join(BASE, 'out', '_sic_cache.json')
    if os.path.exists(old):
        for v in json.load(open(old)).values():
            if v.get('cik') and v.get('sic'):
                m.setdefault(str(int(v['cik'])), v['sic'])
    miss = [c for c in ciks if str(c) not in m]
    print(f'SIC: 既知 {len(ciks) - len(miss)} / 取得 {len(miss)}', file=sys.stderr)
    if fetch:
        for i, c in enumerate(miss):
            raw = get(f'https://data.sec.gov/submissions/CIK{int(c):010d}.json')
            m[str(c)] = (json.loads(raw).get('sic') or '') if raw else ''
            time.sleep(0.12)
            if i % 500 == 499:
                json.dump(m, open(SICF, 'w'), sort_keys=True)
                print(f'  … {i + 1}/{len(miss)}', file=sys.stderr)
    json.dump(m, open(SICF, 'w'), sort_keys=True)
    return m


def main():
    fetch = '--no-fetch' not in sys.argv
    this = datetime.date.today().year
    years = list(range(Y0, this))
    # --- 採取 ---
    rev = defaultdict(lambda: defaultdict(dict))   # cik -> tag -> year -> val
    names = {}
    for t in REV_TAGS:
        for y in years:
            for e in frame(t, f'CY{y}', fetch):
                rev[e['cik']][t][y] = e['val']; names[e['cik']] = e['name']
    flow = {k: defaultdict(dict) for k in FLOW}
    for k, t in FLOW.items():
        for y in years:
            for e in frame(t, f'CY{y}', fetch):
                flow[k][e['cik']][y] = e['val']
    eq = defaultdict(dict)
    for y in years:
        for e in frame('StockholdersEquity', f'CY{y}Q4I', fetch):
            eq[e['cik']][y] = e['val']
    # 最後の年は frames がそろっているか（売上のある社の数が前年の85%以上）で決める
    cnt = {y: sum(1 for c in rev if any(y in rev[c][t] for t in rev[c])) for y in years}
    last = max(y for y in years if cnt[y] >= 0.85 * cnt.get(y - 1, cnt[y]))
    years = [y for y in years if y <= last]

    def rv(c, y):
        for t in REV_TAGS:
            if y in rev[c].get(t, {}):
                return rev[c][t][y]
        return None

    big = [c for c in rev if max((rv(c, y) or 0) for y in years[-3:]) >= MIN_REV]
    sic = sic_map(big, fetch)
    ff = ff49_map()
    ind = {}
    for c in big:
        s = sic.get(str(c)) or ''
        if s.isdigit() and int(s) > 0:
            ind[c] = ff(int(s))

    # --- 業種×年の集計 ---
    agg = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    dropped = 0
    for c, k in ind.items():
        for y in years:
            r = rv(c, y)
            if r and r > 0:
                A = agg[k][y]; A['rev'] += r; A['n'] += 1
                if y in flow['oi'][c]:
                    A['oi'] += flow['oi'][c][y]; A['rev_oi'] += r
                if y in flow['ocf'][c] and y in flow['capex'][c]:
                    A['fcf'] += flow['ocf'][c][y] - flow['capex'][c][y]; A['rev_fcf'] += r
                if y in flow['capex'][c]:
                    A['capex'] += flow['capex'][c][y]; A['rev_cx'] += r
                if y in flow['rd'][c]:
                    A['rd'] += flow['rd'][c][y]; A['rev_rd'] += r
                if y in flow['ni'][c] and eq[c].get(y, 0) > 0:
                    A['ni'] += flow['ni'][c][y]; A['eq'] += eq[c][y]
            # 同じ社・同じタグの2年でだけ成長を測る
            if y - 1 >= Y0:
                for t in REV_TAGS:
                    a, b = rev[c].get(t, {}).get(y - 1), rev[c].get(t, {}).get(y)
                    if a and b and a > 0 and b > 0:
                        if not (0.2 <= b / a <= 5):   # 桁の誤り・大型合併は外す（件数は記録）
                            dropped += 1; break
                        A = agg[k][y]; A['g0'] += a; A['g1'] += b; A['gn'] += 1; A['gup'] += (b > a)
                        break

    def ratio(k, y, a, b):
        A = agg[k].get(y)
        return A[a] / A[b] if A and A[b] > 0 else None

    def g(k, y):
        return ratio(k, y, 'g1', 'g0') - 1 if ratio(k, y, 'g1', 'g0') else None

    def gN(k, y, n):
        v = [g(k, x) for x in range(y - n + 1, y + 1)]
        return (math.prod(1 + x for x in v) ** (1 / n) - 1) if all(x is not None for x in v) else None

    def opm(k, y): return ratio(k, y, 'oi', 'rev_oi')
    def breadth(k, y): return ratio(k, y, 'gup', 'gn')

    INDS = sorted({k for k in agg})

    def pctrank(vals):
        ks = [k for k in vals if vals[k] is not None]
        o = sorted(ks, key=lambda k: vals[k])
        return {k: i / (len(o) - 1) for i, k in enumerate(o)} if len(o) > 1 else {}

    def momentum(y):
        comp = {'g3': {k: gN(k, y, 3) for k in INDS},
                'acc': {k: (gN(k, y, 3) - gN(k, y - 3, 3)) if gN(k, y, 3) is not None and gN(k, y - 3, 3) is not None else None for k in INDS},
                'opmd': {k: (opm(k, y) - opm(k, y - 3)) if opm(k, y) is not None and opm(k, y - 3) is not None else None for k in INDS},
                'br': {k: breadth(k, y) for k in INDS}}
        R = {c: pctrank(v) for c, v in comp.items()}
        out = {}
        for k in INDS:
            if all(k in R[c] for c in R) and agg[k][y]['gn'] >= 5:
                out[k] = S.mean(R[c][k] for c in R)
        return out, comp

    # --- リターン（French 49業種・時価加重）---
    ret = block('49_Industry_Portfolios')
    f3 = block('F-F_Research_Data_Factors', None)
    mkt = {m: f3['Mkt-RF'][m] + f3['RF'][m] for m in f3['RF']}
    endm = max(mkt)

    def mshift(m, k):
        i = (m // 100) * 12 + m % 100 - 1 - k
        return (i // 12) * 100 + i % 12 + 1

    def xs(k, a, b):
        if k not in ret or b > endm:
            return None
        r, m = rcagr(ret[k], a, b), rcagr(mkt, a, b)
        return (r - m) if r is not None and m is not None else None

    # --- 答え合わせ（事前登録どおり）---
    bt = []
    for t in range(2012, 2100):
        if t + 3 > last or t - 6 < Y0:
            continue
        mom, _ = momentum(t)
        ks = [k for k in mom if gN(k, t + 3, 3) is not None]
        if len(ks) < 20:
            continue
        s1 = spear([mom[k] for k in ks], [gN(k, t + 3, 3) for k in ks])
        a, b = (t + 1) * 100 + 7, (t + 4) * 100 + 6
        kr = [k for k in ks if xs(k, a, b) is not None]
        s2 = spear([mom[k] for k in kr], [xs(k, a, b) for k in kr]) if len(kr) >= 20 else None
        top = sorted(kr, key=lambda k: -mom[k])[:5]
        bt.append({'起点': t, '業種数': len(ks), '問い1_順位相関(次の3年の売上成長)': round(s1, 3),
                   '問い2_順位相関(次の3年の超過リターン)': None if s2 is None else round(s2, 3),
                   '勢いの上位5': top,
                   '上位5の次の3年の超過(年率%)': round(S.mean(xs(k, a, b) for k in top) * 100, 2) if top else None,
                   '株価の窓': f'{a}→{b}' if b <= endm else f'{a}→{b}（未完・{endm}まで）'})

    def summ(key):
        v = [x[key] for x in bt if x[key] is not None]
        if not v:
            return None
        return {'起点の数': len(v), '平均': round(S.mean(v), 3), '正の起点': f'{sum(x > 0 for x in v)}/{len(v)}',
                '判定': '当たる向き' if S.mean(v) > 0 and sum(x > 0 for x in v) >= len(v) * 2 / 3 else '当たるとは言えない'}
    top5 = [x['上位5の次の3年の超過(年率%)'] for x in bt if x['上位5の次の3年の超過(年率%)'] is not None and '未完' not in x['株価の窓']]

    # --- 今の一覧 ---
    mom, comp = momentum(last)
    rows = []
    for k in INDS:
        A = agg[k][last]
        if A['n'] < 5:
            continue
        # 業種の上位の社（売上の大きい順）
        mem = sorted([c for c in ind if ind[c] == k and rv(c, last)], key=lambda c: -rv(c, last))[:6]
        rows.append({
            'k': k, 'ja': JA.get(k, k), '社数': int(A['n']), '売上合計(十億$)': round(A['rev'] / 1e9, 1),
            '成長1年': g(k, last), '成長3年': gN(k, last, 3), '成長5年': gN(k, last, 5), '成長10年': gN(k, last, 10),
            '加速': comp['acc'][k], '営業利益率': opm(k, last), '利益率の3年変化': comp['opmd'][k],
            'FCF率': ratio(k, last, 'fcf', 'rev_fcf'), 'ROE': ratio(k, last, 'ni', 'eq'),
            '設備投資率': ratio(k, last, 'capex', 'rev_cx'),
            '設備投資率の3年変化': (ratio(k, last, 'capex', 'rev_cx') - ratio(k, last - 3, 'capex', 'rev_cx'))
            if ratio(k, last, 'capex', 'rev_cx') is not None and ratio(k, last - 3, 'capex', 'rev_cx') is not None else None,
            '研究開発率': ratio(k, last, 'rd', 'rev_rd'), '広がり': breadth(k, last), '勢い': mom.get(k),
            '年ごとの売上成長': {y: g(k, y) for y in years if g(k, y) is not None},
            '年ごとの営業利益率': {y: opm(k, y) for y in years if opm(k, y) is not None},
            '超過リターン1年': xs(k, mshift(endm, 11), endm),
            '超過リターン3年': xs(k, mshift(endm, 35), endm),
            '超過リターン5年': xs(k, mshift(endm, 59), endm),
            '超過リターン10年': xs(k, mshift(endm, 119), endm),
            '大きい社': [{'name': names.get(c, str(c))[:40], 'rev': round(rv(c, last) / 1e9, 1),
                       'g': (lambda a, b: (b / a - 1) if a and b else None)(rv(c, last - 1), rv(c, last))} for c in mem]})
    for r in rows:
        for key, v in list(r.items()):
            if isinstance(v, float):
                r[key] = round(v, 4)
            elif isinstance(v, dict) and key.startswith('年ごと'):
                r[key] = {str(y): round(x, 4) for y, x in v.items()}
    rows.sort(key=lambda r: -(r['勢い'] if r['勢い'] is not None else -1))
    doc = {
        'generated': datetime.date.today().isoformat(), 'tool': 'night/industry_trends.py',
        'prereg': 'out/industry_trends_prereg.json', '最新の年': last, 'リターンの最終月': endm,
        '母集団': f'SEC frames の us-gaap 年次・直近3年のどこかで売上5000万ドル以上・SIC→French 49業種 = {len(ind)}社',
        '外した対の数': dropped,
        '読み方': ['勢い＝3年の売上成長・加速・利益率の変化・広がりの業種内順位の平均（0〜1）',
                 '成長は同じ社の2年を比べた率（会社の出入りで伸びたように見えない）',
                 '超過リターン＝その業種の株価（時価加重・配当込み）− 市場 の年率'],
        '答え合わせ': {'起点ごと': bt, '問い1_売上の伸びは続くか': summ('問い1_順位相関(次の3年の売上成長)'),
                     '問い2_株価は上がったか': summ('問い2_順位相関(次の3年の超過リターン)'),
                     '勢いの上位5_次の3年の超過(年率%)': {'中央': sorted(top5)[len(top5) // 2] if top5 else None,
                                                  '勝った起点': f'{sum(x > 0 for x in top5)}/{len(top5)}'}},
        '⚠限界': json.load(open(os.path.join(BASE, 'out', 'industry_trends_prereg.json')))['limits'] + [
            '歴史の基礎率（out/tech_persist.json）: 過去10年に株価で勝った上位5業種が次の10年も勝ったのは20%',
            '売上5000万ドル未満・IFRS の外国企業・非上場は入らない'],
        'rows': rows}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    a = doc['答え合わせ']
    print(f'→ {OUT}  最新年 {last} ・業種 {len(rows)} ・社 {len(ind)}')
    print('問い1', a['問い1_売上の伸びは続くか']); print('問い2', a['問い2_株価は上がったか']); print('上位5', a['勢いの上位5_次の3年の超過(年率%)'])
    for r in rows[:12]:
        print(f"{r['ja']:10} 勢い{r['勢い']} 3年{r['成長3年']} 加速{r['加速']} 利益率{r['営業利益率']} 社{r['社数']}")


if __name__ == '__main__':
    main()
