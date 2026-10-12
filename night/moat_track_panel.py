#!/usr/bin/env python3
"""night/moat_track_panel.py — 堀の検定②の材料（年ごとの資本利益率・利益率の表）を companyfacts から作る（2026-10-11新設・読むだけ）

決断待ち moat_redesign_1011 の②（事前登録 out/moat_track_prereg.json）の下ごしらえ。関係（相関）はここでは一切測らない。
門の採点・刻み・重み・関門には触れない（絶対のルール1）。

何を作るか（会社ごと・年ごと）:
  ・その時点で読めた数字（point-in-time）: 各ビンテージ Y の締め日 (Y+1)-07-01 までに提出された 10-K だけ
    （同じ年に複数の提出があれば締め日以前で最後のもの＝backtest_core.annual_rows と同じ）
  ・今日の数字（latest）: 締め日なし＝前方の窓（asof+1〜asof+10）に使う
  年ごとの値: 売上・営業利益・粗利・営業利益率・粗利率・のれん込み ROIC・のれんと無形を除いた ROIC（門の roic の分母）
定義（backtest_core.pit_metrics の年ごとの計算と同じ。違いは税だけ）:
  ROIC＝営業利益×0.79÷投下資本（税は固定0.79＝gate0・retro_cohort と同じ。2017年の米国の税制改正で前方だけ
    NOPAT が跳ねるのを避ける。順位は税引前の営業利益÷投下資本と同じ）
  のれん込みの投下資本 icg＝自己資本＋有利子負債（> 0 の年だけ）
  のれん・無形を除いた投下資本 ic＝icg − のれん − 無形。backtest_core と同じ検問——icg ≤ 0 か
    ic < 0.2×max(自己資本〔負なら総資産〕, 1) の年は算出不能。のれん・無形は他の年に報告があるのにその年だけ欠けたら算出不能
  有利子負債・無形は総額タグを優先し、無ければ構成要素の和（backtest_core.series_total_or_sum）
  売上・粗利の原価・自己資本は候補＝代替。候補ごとに年の値を取り、retro_growth_persistence.merge_years
    （gate0 の接ぎ規則・重なる年が2%以内で一致するときだけ欠けた年を埋める）で1本にする。売上タグは gate0 と同じ一覧
  粗利＝GrossProfit。無い年は 売上 − 原価（CostOfRevenue → CostOfGoodsAndServicesSold の代替）。それも無ければ欠測
入力: companyfacts.zip（リポジトリ直下・gitignore・SEC の一括ファイル）
出力: out/_moat2_panel.json（gitignore・作り直せる）
使い方: python3 night/moat_track_panel.py            # 4並列・約1分（既定はビンテージ 2012〜2015 → out/_moat2_panel.json）
        python3 night/moat_track_panel.py --selfcheck  # backtest_core.pit_metrics との一致だけを確かめる
        python3 night/moat_track_panel.py --vint 2012-2020 --out out/_moat3_panel.json
          # 2026-10-12〜（堀の再現の検定 moat_repl）: ビンテージを広げる。2017 以降を含むときは 2018年の読解の社も下限なしで残す。
          #   既定の動き（2012〜2015・読解 2013/2015）は変えていない＝② の表と同じ
"""
import json, multiprocessing as mp, os, sys, time, zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import backtest_core as BC                 # noqa: E402  annual_rows・series_total_or_sum・pit_metrics（自己検問）
import retro_growth_persistence as RGP     # noqa: E402  merge_years（gate0 の接ぎ規則）・REV_TAGS（gate0 の売上タグ）

ZIP = os.path.join(BASE, 'companyfacts.zip')
OUT = os.path.join(BASE, 'out', '_moat2_panel.json')
VINT = (2012, 2013, 2014, 2015)
CUT = {y: f'{y + 1}-07-01' for y in VINT}
TAX = 0.79
MIN_REV = 200e6          # 母集団の下限（どれかのビンテージの入口の売上）。読解の社は下限なしで残す
EQ_TAGS = ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest']
COST_TAGS = ['CostOfRevenue', 'CostOfGoodsAndServicesSold']
Y_LO, Y_HI = 2006, 2025
FWD_LO = min(VINT) + 1   # 今日の数字は前方の窓（最古のビンテージの +1 年＝2013 から）だけに使う


def merged(j, tags, cutoff, ymin=None):
    """候補＝代替: 候補ごとの年次の値を gate0 の接ぎ規則で1本に。
       ymin を渡すとその年より前を捨ててから継ぐ（今日の数字＝前方の窓用。merge_years は年数の多い候補を主にするので、
       2018年の収益認識の基準の変更でタグが替わった社〔KO・MSFT〕は古いタグが主になり、2%の継ぎ目の検問で新しい年が落ちていた）"""
    cands = []
    for t in tags:
        d = BC.annual_rows(j, t, cutoff)
        if ymin is not None:
            d = {y: v for y, v in d.items() if y >= ymin}
        if d:
            cands.append((t, d))
    return RGP.merge_years(cands) or {}


def series(j, cutoff, ymin=None):
    return {
        'rev': merged(j, RGP.REV_TAGS, cutoff, ymin),
        'op': BC.annual_rows(j, 'OperatingIncomeLoss', cutoff),
        'gp': BC.annual_rows(j, 'GrossProfit', cutoff),
        'cost': merged(j, COST_TAGS, cutoff, ymin),
        'eq': merged(j, EQ_TAGS, cutoff, ymin),
        'assets': BC.annual_rows(j, 'Assets', cutoff),
        'gw': BC.annual_rows(j, 'Goodwill', cutoff),
        'debt': BC.series_total_or_sum(j, BC.DEBT_TOTAL, BC.DEBT_PARTS, cutoff),
        'intan': BC.series_total_or_sum(j, BC.INT_TOTAL, BC.INT_PARTS, cutoff),
    }


def year_row(s, y, tax_of=None):
    """1年分: [売上, 営業利益, 粗利率, 営業利益率, ROIC_のれん込み, ROIC_のれん無形除く]（欠測は None）。
       tax_of を渡すと NOPAT の税をその関数で決める（自己検問で backtest_core の実効税率を再現するときだけ）"""
    rev, op = s['rev'].get(y), s['op'].get(y)
    gm = opm = rg = rt = None
    if rev is not None and rev > 0:
        gp = s['gp'].get(y)
        if gp is None and s['cost'].get(y) is not None:
            gp = rev - s['cost'][y]
        if gp is not None:
            v = gp / rev
            gm = v if -1 <= v <= 1 else None
        if op is not None:
            v = op / rev
            opm = v if -1 <= v <= 1 else None
    if op is not None:
        nop = op * (TAX if tax_of is None else (1 - tax_of(y)))
        e = s['eq'].get(y)
        if e is not None:
            d = s['debt'].get(y, 0.0)
            icg = e + d
            if icg > 0:
                rg = nop / icg
            gw, it = s['gw'], s['intan']
            g_ = gw.get(y, 0.0) if (not gw or y in gw or min(gw, default=y) > y) else None
            i_ = it.get(y, 0.0) if (not it or y in it or min(it, default=y) > y) else None
            if g_ is not None and i_ is not None:
                ic = icg - g_ - i_
                base = e if e > 0 else s['assets'].get(y, 0)
                if not (icg <= 0 or ic < 0.2 * max(base, 1)):
                    rt = nop / ic
    r6 = lambda v: None if v is None else round(v, 6)
    return [r6(rev), r6(op), r6(gm), r6(opm), r6(rg), r6(rt)]


_Z = None


def set_vint(vint):
    """ビンテージを差し替える（--vint）。CUT・FWD_LO も同じ規則で作り直す"""
    global VINT, CUT, FWD_LO
    VINT = tuple(vint)
    CUT = {y: f'{y + 1}-07-01' for y in VINT}
    FWD_LO = min(VINT) + 1


def _init(vint=None):
    global _Z
    _Z = zipfile.ZipFile(ZIP)
    if vint:
        set_vint(vint)


def work(args):
    name, keep = args
    try:
        j = json.loads(_Z.read(name))
    except Exception:
        return None
    if not (j.get('facts') or {}).get('us-gaap'):
        return None
    cik = int(name[3:13])
    pit = {}
    big = False
    for y in VINT:
        s = series(j, CUT[y])
        rows = {yy: year_row(s, yy) for yy in range(Y_LO, y + 1)}
        rows = {yy: r for yy, r in rows.items() if any(v is not None for v in r)}
        if rows:
            pit[y] = rows
            rv = (rows.get(y) or [None])[0]
            if rv is not None and rv >= MIN_REV:
                big = True
    if not (big or cik in keep):
        return None
    s = series(j, None, ymin=FWD_LO)
    lat = {yy: year_row(s, yy) for yy in range(FWD_LO, Y_HI + 1)}
    lat = {yy: r for yy, r in lat.items() if any(v is not None for v in r)}
    return cik, {'name': j.get('entityName'), 'pit': pit, 'latest': lat}


def read_ciks():
    """読解の社（2013・2015）の CIK（retro_cohort と retro_sic から）"""
    m = {}
    for y in (2012, 2013, 2015):
        for r in json.load(open(os.path.join(BASE, 'out', f'retro_cohort_{y}.json')))['rows']:
            if r.get('ticker') and r.get('cik'):
                m.setdefault(r['ticker'], int(r['cik']))
    rs = json.load(open(os.path.join(BASE, 'out', 'retro_sic.json')))
    for r in (rs['rows'] if isinstance(rs, dict) and 'rows' in rs else rs):
        if r.get('ticker') and r.get('cik'):
            m.setdefault(r['ticker'], int(r['cik']))
    t = set()
    for y in (2013, 2015):
        d = json.load(open(os.path.join(BASE, 'out', f'retro_moat_pillars_{y}.json')))
        t |= {r['ticker'] for r in (d['rows'] if isinstance(d, dict) and 'rows' in d else d) if r.get('ticker')}
    miss = sorted(x for x in t if x not in m)
    if miss:
        raise SystemExit(f'✗ 読解の社に CIK が無い: {miss[:10]}')
    return {m[x] for x in t}, {x: m[x] for x in t}


def read_ciks_2018():
    """2018年の読解（retro_moat_2018・_rest＝2018-07-01 までの提出を読んだ177社）の CIK。ティッカー→CIK は read_ciks と同じ在庫"""
    m = {}
    for y in (2012, 2013, 2015):
        for r in json.load(open(os.path.join(BASE, 'out', f'retro_cohort_{y}.json')))['rows']:
            if r.get('ticker') and r.get('cik'):
                m.setdefault(r['ticker'], int(r['cik']))
    rs = json.load(open(os.path.join(BASE, 'out', 'retro_sic.json')))
    for r in (rs['rows'] if isinstance(rs, dict) and 'rows' in rs else rs):
        if r.get('ticker') and r.get('cik'):
            m.setdefault(r['ticker'], int(r['cik']))
    t = set()
    for f in ('retro_moat_2018.json', 'retro_moat_2018_rest.json'):
        d = json.load(open(os.path.join(BASE, 'out', f)))
        t |= {(r.get('t') or r.get('ticker')) for r in (d['rows'] if isinstance(d, dict) and 'rows' in d else d)
              if (r.get('t') or r.get('ticker'))}
    miss = sorted(x for x in t if x not in m)
    if miss:
        raise SystemExit(f'✗ 2018年の読解の社に CIK が無い: {miss[:10]}')
    return {m[x] for x in t}, {x: m[x] for x in t}


def selfcheck(n=400):
    """自己検問: 税だけ backtest_core と同じ実効税率に戻し、入力も backtest_core と同じ（代替は series_pick）にしたとき、
       年ごとの計算が pit_metrics の roic_med5・roicg_med5 と一致するか（締め日 2016-07-01・読解の社から n 社）"""
    _, t2c = read_ciks()
    z = zipfile.ZipFile(ZIP)
    cut = '2016-07-01'
    ok = bad = skip = 0
    worst = []
    for t, cik in sorted(t2c.items())[:n]:
        try:
            j = json.loads(z.read(f'CIK{cik:010d}.json'))
        except KeyError:
            skip += 1
            continue
        pm = BC.pit_metrics(j, cut)
        if not pm:
            skip += 1
            continue
        s = {'rev': BC.series_pick(j, BC.TAGS['rev'], cut), 'op': BC.series_pick(j, BC.TAGS['op'], cut),
             'gp': {}, 'cost': {}, 'eq': BC.series_pick(j, BC.TAGS['eq'], cut),
             'assets': BC.series_pick(j, BC.TAGS['assets'], cut), 'gw': BC.annual_rows(j, 'Goodwill', cut),
             'debt': BC.series_total_or_sum(j, BC.DEBT_TOTAL, BC.DEBT_PARTS, cut),
             'intan': BC.series_total_or_sum(j, BC.INT_TOTAL, BC.INT_PARTS, cut)}
        tax = BC.series_pick(j, BC.TAGS['tax'], cut)
        pre = BC.series_pick(j, BC.TAGS['pre'], cut)

        def tr(y):
            if y in pre and pre[y] not in (0, None) and abs(pre[y]) > 1:
                return max(0.0, min(0.6, tax[y] / pre[y]))
            return 0.25
        y_max = pm['year']
        rt, rg = [], []
        for y in sorted(set(s['op']) & set(s['eq'])):
            if y < y_max - 5 or y not in tax:
                continue
            r = year_row(s, y, tax_of=tr)
            if r[5] is not None:          # backtest_core は除いた ROIC が算出不能な年を両方とも飛ばす
                rt.append(r[5] * 100)
                rg.append(r[4] * 100)
        import statistics as S
        if len(rt) < 3:
            bad += 1
            worst.append((t, 'n<3', pm))
            continue
        a, b = round(S.median(rt), 1), round(S.median(rg), 1)
        if a == pm['roic_med5'] and b == pm['roicg_med5']:
            ok += 1
        else:
            bad += 1
            worst.append((t, (a, b), (pm['roic_med5'], pm['roicg_med5'])))
    return {'一致': ok, '不一致': bad, '対象外（pit_metrics が値を出さない・ファイルなし）': skip, '不一致の例': worst[:10]}


def main():
    if not os.path.exists(ZIP):
        raise SystemExit('✗ companyfacts.zip が無い（SEC の一括ファイルをリポジトリ直下へ）')
    if '--selfcheck' in sys.argv:
        print(json.dumps(selfcheck(), ensure_ascii=False, indent=1))
        return
    out = OUT
    if '--vint' in sys.argv:
        a, b = sys.argv[sys.argv.index('--vint') + 1].split('-')
        set_vint(range(int(a), int(b) + 1))
    if '--out' in sys.argv:
        out = os.path.join(BASE, sys.argv[sys.argv.index('--out') + 1])
    keep, _ = read_ciks()
    if max(VINT) >= 2017:
        keep = keep | read_ciks_2018()[0]
    names = [n for n in zipfile.ZipFile(ZIP).namelist() if n.startswith('CIK') and n.endswith('.json')]
    t0 = time.time()
    res = {}
    with mp.Pool(4, initializer=_init, initargs=(VINT,)) as pool:
        for i, r in enumerate(pool.imap_unordered(work, [(n, keep) for n in names], chunksize=16), 1):
            if r:
                res[str(r[0])] = r[1]
            if i % 2000 == 0:
                print(f'  {i}/{len(names)} 残した {len(res)}  {time.time() - t0:.0f}秒', flush=True)
    meta = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/moat_track_panel.py', 'zip_bytes': os.path.getsize(ZIP),
            'zip_mtime': time.strftime('%Y-%m-%d', time.localtime(os.path.getmtime(ZIP))), 'vintages': list(VINT), 'cutoffs': CUT,
            'row': ['売上', '営業利益', '粗利率', '営業利益率', 'ROIC_のれん込み', 'ROIC_のれん無形除く'], 'tax': TAX,
            'min_rev': MIN_REV, 'fwd_lo': FWD_LO, 'read_ciks': len(keep), 'n': len(res)}
    with open(out, 'w') as f:
        json.dump({'meta': meta, 'firms': res}, f, separators=(',', ':'))
    print(f'書いた {out}  {len(res)}社  {time.time() - t0:.0f}秒')


if __name__ == '__main__':
    main()
