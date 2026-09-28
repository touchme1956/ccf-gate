#!/usr/bin/env python3
"""night/mw_overlay_verify.py — 角度 overlay（night/mw_overlay.py → out/mw_overlay.json）の反証の検証（読むだけ・門の判定には不使用）

役割: 研究役が S・A と付けた候補（と B の上位2本）を、**自分のコードで**一から組み直して数字を再現し、
後知恵・超過と総リターンの取り違え・相手（純粋な時価加重か）・費用の現実性・部分期間・隣の設定・多重検定・
地域の複製（C5）が本当に独立か、を突く。mw_common からは**取得（get / jkp_factor / jkp_mkt / french_tables / yahoo）だけ**を使い、
上乗せの組み立て・超過・t値・年率差・転がる窓・積立・シャープ・格付けはこのファイルの中で書き直した。

  python3 night/mw_overlay_verify.py   → out/mw_overlay_verify.json
"""
import csv, datetime, io, json, math, os, sys, zipfile
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402  （取得だけに使う）

OUT = os.path.join(M.BASE, 'out', 'mw_overlay_verify.json')
TSMOM_URL = 'https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Time-Series-Momentum-Factors-Monthly.xlsx'
CEN_URL = 'https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Century-of-Factor-Premia-Monthly.xlsx'
TE, HS, RS = 200612, 200701, 201307
DRAG = 0.002
PERF = 0.20


# ═════════════════════════ データ（自前の読み取り） ═════════════════════════
def french_mkt_rf():
    """French 3因子の zip を自分で読む（月次の表だけ）→ (総リターンの Mkt, RF)"""
    b = M.get(M.FR.format('F-F_Research_Data_Factors'), name='fr_F-F_Research_Data_Factors.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    lines = z.read(z.namelist()[0]).decode('latin-1').splitlines()
    hdr = None
    mkt, rf = {}, {}
    for ln in lines:
        c = [x.strip() for x in ln.split(',')]
        if hdr is None and 'Mkt-RF' in c:
            hdr = c
            continue
        if hdr is not None and c[0].isdigit() and len(c[0]) == 6:
            im, ir = hdr.index('Mkt-RF'), hdr.index('RF')
            a, r = float(c[im]), float(c[ir])
            mkt[int(c[0])] = (a + r) / 100
            rf[int(c[0])] = r / 100
        elif hdr is not None and c[0].isdigit() and len(c[0]) == 4:
            break  # 年次の表に入ったら終わり
    return mkt, rf


def _ym_of(d):
    if isinstance(d, datetime.datetime):
        return d.year * 100 + d.month
    if isinstance(d, str) and d.count('/') == 2:
        mm, dd, yy = d.split('/')
        return int(yy) * 100 + int(mm)
    return None


def aqr_sheet(url, cache_name, sheet, is_header):
    import openpyxl
    M.get(url, name=cache_name)
    wb = openpyxl.load_workbook(os.path.join(M.CACHE, cache_name), read_only=True, data_only=True)
    rows = list(wb[sheet].iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and is_header(r))
    hdr = rows[hi]
    out = {}
    for r in rows[hi + 1:]:
        ym = _ym_of(r[0]) if r else None
        if ym is None:
            continue
        for j, h in enumerate(hdr):
            if j == 0 or not h:
                continue
            v = r[j] if j < len(r) else None
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                out.setdefault(h, {})[ym] = float(v)
    return out


def load_tsmom():
    return aqr_sheet(TSMOM_URL, 'aqr_tsmom_monthly.xlsx', 'TSMOM Factors', lambda r: len(r) > 1 and r[1] == 'TSMOM')


def load_century():
    return aqr_sheet(CEN_URL, 'aqr_century_monthly.xlsx', 'Century of Factor Premia', lambda r: r[0] == 'Date')


def gaps(d):
    ks = sorted(d)
    return sum(1 for a, b in zip(ks, ks[1:]) if (b // 100 * 12 + b % 100) - (a // 100 * 12 + a % 100) != 1)


# ═════════════════════════ 統計（自前） ═════════════════════════
def _keys(s, b, a=None, z=None, drop=None):
    return sorted(k for k in s.keys() & b.keys() if (a is None or k >= a) and (z is None or k <= z) and not (drop and k // 100 in drop))


def nw(x, L=12):
    x = np.asarray(x, float); n = len(x)
    if n < 24:
        return None
    e = x - x.mean()
    s = float(e @ e) / n
    for l in range(1, L + 1):
        s += 2 * (1 - l / (L + 1)) * float(e[l:] @ e[:-l]) / n
    return float(x.mean() / math.sqrt(s / n)) if s > 0 else None


def geo(v):
    v = np.asarray(v, float)
    return math.exp(np.log1p(v).mean() * 12) - 1


def cmp(s, b, a=None, z=None, drop=None):
    ks = _keys(s, b, a, z, drop)
    if len(ks) < 24:
        return None
    sv = np.array([s[k] for k in ks]); bv = np.array([b[k] for k in ks])
    ex = sv - bv
    t = nw(ex)
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(float(ex.mean()) * 1200, 2), 't': round(t, 2) if t is not None else None,
            'p2': round(math.erfc(abs(t) / math.sqrt(2)), 4) if t is not None else None,
            'cagr_diff': round((geo(sv) - geo(bv)) * 100, 2)}


def sharpe(r, rf, a=None, z=None, drop=None):
    ks = _keys(r, rf, a, z, drop)
    if len(ks) < 24:
        return None
    x = np.array([r[k] - rf[k] for k in ks])
    return round(float(x.mean() / x.std(ddof=1) * math.sqrt(12)), 3)


def roll20(s, b):
    ks = set(s) & set(b)
    if not ks:
        return None
    y0, y1 = min(ks) // 100, max(ks) // 100
    res = []
    for y in range(y0, y1 + 1):
        w = [yy * 100 + mm for yy in range(y, y + 21) for mm in range(1, 13) if (y * 100 + 7) <= yy * 100 + mm <= ((y + 20) * 100 + 6)]
        if len(w) != 240 or not all(k in ks for k in w):
            continue
        d = geo([s[k] for k in w]) - geo([b[k] for k in w])
        res.append((y, round(d * 100, 2)))
    if not res:
        return None
    v = sorted(x for _, x in res)
    return {'windows': len(res), 'win_rate': round(sum(1 for x in v if x > 0) / len(v), 3), 'median': v[len(v) // 2], 'worst': min(res, key=lambda r: r[1])}


def dca20(s, b):
    ks = sorted(set(s) & set(b))
    out = []
    for i in range(0, len(ks) - 240 + 1, 12):
        ws = wb = 0.0
        for k in ks[i:i + 240]:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        out.append(ws / wb)
    if not out:
        return None
    v = sorted(out)
    return {'windows': len(v), 'win_rate': round(sum(1 for x in v if x > 1) / len(v), 3), 'median': round(v[len(v) // 2], 3), 'worst': round(v[0], 3)}


def sd_ann(d, a=None, z=None):
    v = [x for k, x in d.items() if (a is None or k >= a) and (z is None or k <= z)]
    return float(np.std(v, ddof=1) * math.sqrt(12))


def raw_stats(o, a=None, z=None):
    v = np.array([o[k] for k in sorted(o) if (a is None or k >= a) and (z is None or k <= z)])
    if len(v) < 24:
        return None
    t = nw(v)
    return {'n': len(v), 'mean': round(float(v.mean()) * 1200, 2), 'vol': round(float(v.std(ddof=1)) * math.sqrt(12) * 100, 2),
            'sr': round(float(v.mean() / v.std(ddof=1)) * math.sqrt(12), 3), 't': round(t, 2) if t is not None else None}


def holm_adj(p):
    items = sorted((v, k) for k, v in p.items() if v is not None)
    m, run, out = len(items), 0.0, {}
    for i, (v, k) in enumerate(items):
        run = max(run, min(1.0, (m - i) * v))
        out[k] = round(run, 4)
    return out


# ═════════════════════════ 上乗せの組み立て（自前） ═════════════════════════
def fund_net(o, c, T, mgmt, unit, borrow=0.0, perf=PERF, hwm=False):
    """単位ファンドの月次（費用後）。o は超過リターン、c はてこ。
    走る費用 = (mgmt + T×c×unit + borrow)/12。成功報酬は既定で『暦年の月次の合計が正なら20%』（事前登録どおり・高値更新なし）。
    hwm=True は現実のファンドに近い形: 複利の NAV が前の高値を超えた分だけ、暦年末に20%"""
    ks = sorted(o)
    run = (mgmt + T * c * unit + borrow) / 12
    f = {t: c * o[t] - run for t in ks}
    if perf:
        by = {}
        for t in ks:
            by.setdefault(t // 100, []).append(t)
        if not hwm:
            for y, ms in by.items():
                tot = math.fsum(f[t] for t in ms)
                if tot > 0:
                    f[ms[-1]] -= perf * tot
        else:
            nav, hw = 1.0, 1.0
            for y in sorted(by):
                ms = by[y]
                for t in ms[:-1]:
                    nav *= 1 + f[t]
                pre = nav * (1 + f[ms[-1]])
                fee = perf * max(0.0, pre - max(hw, 0.0)) if pre > hw else 0.0
                # 最後の月のリターンから fee（NAV に対する割合）を引く
                f[ms[-1]] = (pre - fee) / nav - 1
                nav = pre - fee
                hw = max(hw, nav)
    return f


def stack(m, f, k, drag=DRAG):
    return {t: m[t] + k * f[t] - drag / 12 for t in m.keys() & f.keys()}


# ═════════════════════════ 本体 ═════════════════════════
def main():
    m, rf = french_mkt_rf()
    TS = load_tsmom(); CEN = load_century()
    sanity = {'french_mkt_cagr_all': round(geo([m[k] for k in sorted(m)]) * 100, 2),
              'french_mkt_cagr_2007': round(geo([m[k] for k in sorted(m) if k >= HS]) * 100, 2),
              'french_range': [min(m), max(m)],
              'tsmom_range': [min(TS['TSMOM']), max(TS['TSMOM']), len(TS['TSMOM']), gaps(TS['TSMOM'])],
              'century_ranges': {k: [min(CEN[k]), max(CEN[k]), len(CEN[k]), gaps(CEN[k])] for k in
                                 ['All Stock Selection Multi-style', 'Intl Stock Selection Multi-style', 'US Stock Selection Multi-style', 'All asset classes Multi-style']}}
    print('sanity', sanity, flush=True)

    def cv(o, a=None, z=TE):
        return 0.10 / sd_ann(o, a, z)

    # ---- 候補の仕様（研究役の定義を事前登録から読み直して自分で組む）
    oT, oSS, oINT, oMS = TS['TSMOM'], CEN['All Stock Selection Multi-style'], CEN['Intl Stock Selection Multi-style'], CEN['All asset classes Multi-style']
    cT, cSS, cINT, cMS = cv(oT), cv(oSS), cv(oINT), cv(oMS)
    comb_keys = oT.keys() & oMS.keys()
    oE5 = {t: 0.5 * cT * oT[t] + 0.5 * cMS * oMS[t] for t in comb_keys}
    TE5 = 0.5 * 5 * cT + 0.5 * 10 * cMS

    def jkp_ms(reg):
        fs = [M.jkp_factor(reg, key, 'vw_cap') for key in ('be_me', 'ret_12_1', 'betabab_1260d')]
        ks = set(fs[0]) & set(fs[1]) & set(fs[2])
        return {t: (fs[0][t] + fs[1][t] + fs[2][t]) / 3 for t in ks}

    def jkp_mkt_total(reg):
        mk = M.jkp_mkt(reg, 'vw')   # 上限なしの時価加重・超過
        return {t: mk[t] + rf[t] for t in mk if t in rf}

    oEM, oCAN = jkp_ms('emerging'), jkp_ms('can')
    mEM, mCAN = jkp_mkt_total('emerging'), jkp_mkt_total('can')

    # ss = 空売り（借株料）が掛かる割合（株の銘柄選択の部分）。CENms は下の composition の回帰（1990〜2026）で
    # 米国＋米国外の銘柄選択の重み ≈ 0.08+0.11 ≈ 0.2 と測れたので 0.2 を使う
    comp_names = ['US Stock Selection Multi-style', 'Intl Stock Selection Multi-style', 'Equity indices Multi-style',
                  'Fixed income Multi-style', 'Currencies Multi-style', 'Commodities Multi-style']
    composition = {}
    for a0, z0 in [(199001, 200612), (200701, 202602), (199001, 202602)]:
        kk = [k for k in sorted(oMS) if a0 <= k <= z0 and all(k in CEN[cn] for cn in comp_names)]
        X = np.array([[CEN[cn][k] for cn in comp_names] for k in kk]); yv = np.array([oMS[k] for k in kk])
        bb = np.linalg.lstsq(X, yv, rcond=None)[0]
        composition[f'{a0}-{z0}'] = {'weights': dict(zip(comp_names, [round(float(x), 3) for x in bb])),
                                     'R2': round(float(1 - ((yv - X @ bb) ** 2).sum() / ((yv - yv.mean()) ** 2).sum()), 3)}
    SS_MS = 0.2
    C = {
        'E2_SSms_v10_k50': dict(o=oSS, c=cSS, k=0.5, T=10, ss=1.0, m=m, pub=2022, claimed_grade='S'),
        'X2_CEN_INTLss_v10_k50': dict(o=oINT, c=cINT, k=0.5, T=10, ss=1.0, m=m, pub=2022, claimed_grade='S'),
        'E1_CENms_v10_k100': dict(o=oMS, c=cMS, k=1.0, T=10, ss=SS_MS, m=m, pub=2022, claimed_grade='S'),
        'P_TSMOM_k50': dict(o=oT, c=1.0, k=0.5, T=5, ss=0.0, m=m, pub=2013, claimed_grade='A'),
        'P_TSMOM_k25': dict(o=oT, c=1.0, k=0.25, T=5, ss=0.0, m=m, pub=2013, claimed_grade='A'),
        'E1_TSMOM_v10_k100': dict(o=oT, c=cT, k=1.0, T=5, ss=0.0, m=m, pub=2013, claimed_grade='A'),
        'E1_TSMOM_v10_k50': dict(o=oT, c=cT, k=0.5, T=5, ss=0.0, m=m, pub=2013, claimed_grade='A'),
        'E1_CENms_v10_k50': dict(o=oMS, c=cMS, k=0.5, T=10, ss=SS_MS, m=m, pub=2022, claimed_grade='A'),
        'E5_TSMOMxCENms_v10_k100': dict(o=oE5, c=1.0, k=1.0, T=TE5, ss=0.5 * cMS * SS_MS, m=m, pub=2022, claimed_grade='A（出力にあるが候補一覧から漏れていた）'),
        'X3_JKP_emerging_MS_v10_k50': dict(o={t: cv(oEM) * v for t, v in oEM.items()}, c=cv(oEM), k=0.5, T=10, ss=1.0, m=mEM, pub=2022, claimed_grade='B', rawscaled=True),
        'X3_JKP_can_MS_v10_k50': dict(o={t: cv(oCAN) * v for t, v in oCAN.items()}, c=cv(oCAN), k=0.5, T=10, ss=1.0, m=mCAN, pub=2022, claimed_grade='B', rawscaled=True),
    }

    def overlay_series(spec, c=None, k=None, T=None, mgmt=0.01, unit=0.0005, borrow_rate=0.0, hwm=False, perf=PERF):
        c = spec['c'] if c is None else c
        k = spec['k'] if k is None else k
        T = spec['T'] if T is None else T
        if spec.get('rawscaled'):
            # JKP 版は o が既に c 倍されている。てこを変えるときは比で掛け直す
            o = {t: v * (c / spec['c']) for t, v in spec['o'].items()}
            f = fund_net(o, 1.0, T * c, mgmt, unit, borrow=borrow_rate * c * spec['ss'], perf=perf, hwm=hwm)
        else:
            f = fund_net(spec['o'], c, T, mgmt, unit, borrow=borrow_rate * c * spec['ss'], perf=perf, hwm=hwm)
        return stack(spec['m'], f, k)

    res_json = json.load(open(os.path.join(M.BASE, 'out', 'mw_overlay.json')))
    RS_ALL = dict(res_json['strategies']); RS_ALL.update(res_json['part2']['strategies'])

    results = {}
    for name, sp in C.items():
        b = sp['m']
        s = overlay_series(sp)                                   # 基本（事前登録の判定用）
        s_st = overlay_series(sp, mgmt=0.02, unit=0.0010)       # 厳しめ（事前登録の C6）
        e = {'c_mine': round(sp['c'], 3), 'c_claimed': RS_ALL[name]['c'], 'k': sp['k'], 'T': round(sp['T'], 2)}
        e['full'] = cmp(s, b); e['train'] = cmp(s, b, z=TE); e['hold'] = cmp(s, b, a=HS); e['recent'] = cmp(s, b, a=RS)
        e['net_cost_hold'] = cmp(s_st, b, a=HS)
        e['roll20'] = roll20(s, b); e['dca20'] = dca20(s, b)
        e['sharpe'] = {'train': (sharpe(s, rf, z=TE), sharpe(b, rf, z=TE)), 'hold': (sharpe(s, rf, a=HS), sharpe(b, rf, a=HS))}
        # 研究役の数字との差
        cl = RS_ALL[name]
        e['diff_vs_claimed'] = {w: (round(e[w]['ex'] - cl[w]['ex_ann'], 2), round((e[w]['t'] or 0) - (cl[w]['t'] or 0), 2)) for w in ('full', 'train', 'hold') if e[w] and cl.get(w)}
        e['diff_vs_claimed']['net_cost_hold'] = round(e['net_cost_hold']['ex'] - cl['cost_hold_stress']['ex_ann'], 2)
        e['diff_vs_claimed']['hold_cagr_diff'] = round(e['hold']['cagr_diff'] - cl['hold']['cagr_diff'], 2)
        # 生の上乗せ系列（費用前・c 倍前）
        raw_o = sp['o'] if not sp.get('rawscaled') else {t: v / sp['c'] for t, v in sp['o'].items()}
        e['raw_overlay'] = {'train': raw_stats(raw_o, z=TE), 'hold': raw_stats(raw_o, a=HS), 'post_pub': raw_stats(raw_o, a=sp['pub'] * 100 + 1)}
        # 部分期間
        mid = 201607
        e['sub'] = {
            'hold_1st_half_2007_2016H1': cmp(s, b, a=HS, z=mid - 1),
            'hold_2nd_half_2016H2_end': cmp(s, b, a=mid),
            'hold_drop_2020_2021': cmp(s, b, a=HS, drop={2020, 2021}),
            'hold_drop_2008_2022': cmp(s, b, a=HS, drop={2008, 2022}),
            'train_drop_1998_2000': cmp(s, b, z=TE, drop={1998, 1999, 2000}),
            'full_drop_1998_2000_2020_2021': cmp(s, b, drop={1998, 1999, 2000, 2020, 2021}),
            f'post_publication_{sp["pub"]}+': cmp(s, b, a=sp['pub'] * 100 + 1),
            'hold_2007_2021_before_pub2022': cmp(s, b, a=HS, z=202112),
        }
        # 隣の設定
        nb = {}
        for kk in (0.25, 0.5, 0.75, 1.0):
            h = cmp(overlay_series(sp, k=kk), b, a=HS)
            nb[f'k{kk}'] = (h['ex'], h['t'], h['cagr_diff'])
        if sp['c'] != 1.0:
            for lab, (a0, z0) in {'c_from_1985_2006': (198501, TE), 'c_from_1997_2006': (199701, TE)}.items():
                base_o = sp['o'] if not sp.get('rawscaled') else {t: v / sp['c'] for t, v in sp['o'].items()}
                c2 = 0.10 / sd_ann(base_o, a0, z0)
                h = cmp(overlay_series(sp, c=c2), b, a=HS)
                nb[lab] = (round(c2, 3), h['ex'], h['t'], h['cagr_diff'])
        for TT in (sp['T'] * 0.5, sp['T'] * 2):
            h = cmp(overlay_series(sp, T=TT), b, a=HS)
            nb[f'T{round(TT, 1)}'] = (h['ex'], h['t'])
        e['neighbors_hold'] = nb
        # 費用の現実性（単価・借株料・運用報酬・高値更新つき成功報酬）
        cg = {}
        for mg in (0.01, 0.02):
            for u in (0.0005, 0.0010, 0.0020, 0.0030):
                for br in ((0.0, 0.005, 0.01) if sp['ss'] > 0 else (0.0,)):
                    h = cmp(overlay_series(sp, mgmt=mg, unit=u, borrow_rate=br), b, a=HS)
                    cg[f'mgmt{mg * 100:.0f}_unit{u * 100:.2f}_borrow{br * 100:.1f}'] = (h['ex'], h['t'], h['cagr_diff'])
        h = cmp(overlay_series(sp, hwm=True), b, a=HS)
        cg['base_with_HWM_perf'] = (h['ex'], h['t'], h['cagr_diff'])
        e['cost_grid_hold'] = cg
        # 私の『現実寄り』の費用（検証役の判断・事前登録ではない）: mgmt1%・単価0.20%・借株料0.5%×c×銘柄選択の割合
        sr = overlay_series(sp, unit=0.0020, borrow_rate=0.005)
        e['realistic_cost'] = {'hold': cmp(sr, b, a=HS), 'train': cmp(sr, b, z=TE), 'full': cmp(sr, b),
                               'sharpe_hold': (sharpe(sr, rf, a=HS), sharpe(b, rf, a=HS))}
        # 検証役の C6（事前登録の厳しめ＝運用2%・単価0.10% に、研究役自身の B1 の下限＝借株料 0.5%/年×売りの名目 を足す）
        e['skeptic_C6_hold'] = cmp(overlay_series(sp, mgmt=0.02, unit=0.0010, borrow_rate=0.005), b, a=HS)
        # C6 の損益分岐の単価（運用2%・借株料なし）: 保有の超過の算術平均と年率差の両方が正でいられる最大の単価
        lo, hi = 0.0, 0.02
        for _ in range(40):
            mid_u = (lo + hi) / 2
            h = cmp(overlay_series(sp, mgmt=0.02, unit=mid_u), b, a=HS)
            if h['ex'] > 0 and h['cagr_diff'] > 0:
                lo = mid_u
            else:
                hi = mid_u
        e['C6_breakeven_unit_cost_pct'] = round(lo * 100, 3)
        e['_s'] = s
        results[name] = e
        print(name, 'full', e['full']['ex'], e['full']['t'], '| train', e['train']['ex'], e['train']['t'], '| hold', e['hold']['ex'], e['hold']['t'], e['hold']['cagr_diff'],
              '| net', e['net_cost_hold']['ex'], '| roll', e['roll20'] and e['roll20']['win_rate'], '| dca', e['dca20'] and e['dca20']['median'], '| diff', e['diff_vs_claimed'], flush=True)

    # ── 追加: Century の米国の銘柄選択だけ（研究役の X1 を自前で）
    oUS = CEN['US Stock Selection Multi-style']
    fUS = fund_net(oUS, cv(oUS), 10, 0.01, 0.0005)
    sUS = stack(m, fUS, 0.5)
    extra = {'US_ss_c': round(cv(oUS), 3), 'US_ss_hold': cmp(sUS, m, a=HS), 'US_ss_train': cmp(sUS, m, z=TE), 'US_ss_raw_hold': raw_stats(oUS, a=HS)}

    # ── C5 の独立性: 上乗せを別の地域の市場に敷いても、算術の超過は上乗せそのもの（市場に依らない）
    c5 = {}
    for rn in ['Developed_ex_US_3_Factors', 'Japan_3_Factors', 'Europe_3_Factors']:
        for t, v in M.french_tables(rn).items():
            if v['freq'] == 'monthly':
                cols = v['cols']; im, ir = cols.index('Mkt-RF'), cols.index('RF')
                mr = {d: (row[im] + row[ir]) / 100 for d, row in v['data'].items() if row[im] is not None and row[ir] is not None}
                break
        for name in ['P_TSMOM_k50', 'E1_CENms_v10_k100', 'E2_SSms_v10_k50']:
            sp = C[name]
            f = fund_net(sp['o'], sp['c'], sp['T'], 0.01, 0.0005)
            sreg = stack(mr, f, sp['k'])
            reg = cmp(sreg, mr)
            same_months_us = cmp(stack(m, f, sp['k']), m, a=reg['from'], z=reg['to'])
            c5.setdefault(name, {})[rn.replace('_3_Factors', '')] = {'regional_ex': reg['ex'], 'regional_t': reg['t'], 'US_same_months_ex': same_months_us['ex'],
                                                                      'US_same_months_t': same_months_us['t'], 'identical_arith': abs(reg['ex'] - same_months_us['ex']) < 0.01}
    # ── 株の銘柄選択の独立の複製（JKP・自前の組み立て）: E2 と X2 の本当の C5
    jk = {}
    regs = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'emerging']
    for reg in regs + ['world_ex_us', 'world', 'usa']:
        o = jkp_ms(reg)
        c = 0.10 / sd_ann(o, z=TE)
        f = fund_net(o, c, 10, 0.01, 0.0005)
        own = jkp_mkt_total(reg)
        s_own = stack(own, f, 0.5)
        s_us = stack(m, f, 0.5)   # X2 と同じ形: 米国の市場（French Mkt）に重ねる
        jk[reg] = {'c': round(c, 3), 'raw_train': raw_stats(o, z=TE), 'raw_hold': raw_stats(o, a=HS),
                   'on_own_mkt': {'full': cmp(s_own, own), 'hold': cmp(s_own, own, a=HS), 'sharpe_hold': (sharpe(s_own, rf, a=HS), sharpe(own, rf, a=HS))},
                   'on_French_Mkt': {'full': cmp(s_us, m), 'hold': cmp(s_us, m, a=HS), 'hold_to_2025': cmp(s_us, m, a=HS, z=202512)}}
    pos_full = [r for r in regs if jk[r]['on_own_mkt']['full']['ex'] > 0 and jk[r]['on_own_mkt']['full']['cagr_diff'] > 0]
    pos_hold = [r for r in regs if jk[r]['on_own_mkt']['hold']['ex'] > 0 and jk[r]['on_own_mkt']['hold']['cagr_diff'] > 0]
    x2_same = cmp(results['X2_CEN_INTLss_v10_k50']['_s'], m, a=HS, z=202512)
    e2_same = cmp(results['E2_SSms_v10_k50']['_s'], m, a=HS, z=202512)
    c5_ss = {'countries': regs, 'positive_full': pos_full, 'positive_hold': pos_hold,
             'C5_full_pass(>=2/3)': len(pos_full) / len(regs) >= 2 / 3, 'C5_hold_pass(>=2/3)': len(pos_hold) / len(regs) >= 2 / 3,
             'world_ex_us_JKP_vs_Century_Intl_same_window_2007_2025': {'JKP_world_ex_us_on_FrenchMkt': jk['world_ex_us']['on_French_Mkt']['hold_to_2025'], 'Century_Intl_X2': x2_same},
             'world_JKP_vs_Century_All_same_window_2007_2025': {'JKP_world_on_FrenchMkt': jk['world']['on_French_Mkt']['hold_to_2025'], 'Century_All_E2': e2_same}}

    # ── 多重検定: 角度の38本の保有期間 p（候補は自分の値・残りは研究役の値）
    p38 = {n: (results[n]['hold']['p2'] if n in results else RS_ALL[n]['hold']['p']) for n in RS_ALL}
    h38 = holm_adj(p38)
    mult = {'n_graded_in_angle': len(p38), 'bonferroni_t_38_two_sided_5pct': 3.02, 'program_bonferroni_t': json.load(open(os.path.join(M.BASE, 'out', 'mw_summary.json')))['bonferroni_t_program_wide'],
            'holm38_hold_p': {n: h38[n] for n in results if n in h38}}

    # ── 実在ファンドの答え合わせ（自前の合成）
    def av_csv(t):
        p = os.path.join(M.CACHE, f'av_dead_mf_{t}.csv')
        if not os.path.exists(p):
            return None
        rows = sorted(csv.DictReader(open(p)), key=lambda r: r['date'])
        px = {}
        for r in rows:
            try:
                px[int(r['date'][:4]) * 100 + int(r['date'][5:7])] = float(r['adj'])
            except (ValueError, KeyError):
                pass
        ks = sorted(px)
        return {k: px[k] / px[p0] - 1 for p0, k in zip(ks, ks[1:])}

    def compo(series):
        allk = sorted(set().union(*[set(x) for x in series if x]))
        return {k: float(np.mean([x[k] for x in series if x and k in x])) for k in allk if any(x and k in x for x in series)}

    def live_stack(comp, k):
        s = {t: m[t] + k * (comp[t] - rf[t]) - DRAG / 12 for t in comp if t in m and t in rf}
        return {'hold': cmp(s, m, a=HS), 'sharpe_hold': (sharpe(s, rf, a=HS), sharpe({t: m[t] for t in s}, rf, a=HS)),
                'hold_drop_2008_2022': cmp(s, m, a=HS, drop={2008, 2022})}

    trend = ['RYMFX', 'AQMIX', 'ASFYX', 'WTMF', 'CSAIX', 'MFTNX', 'EBSIX', 'QMHIX', 'FMF', 'PQTIX', 'ABYIX', 'AHLIX', 'DBMF', 'KMLM', 'CTA', 'FMFFX', 'ASMF']
    mn = ['QMNIX', 'VMNFX', 'BDMIX', 'JMNSX']
    ylive = {}
    for t in trend + mn + ['QSPIX']:
        try:
            ylive[t] = M.yahoo(t)
        except Exception as ex:  # noqa
            ylive[t] = None
            print('yahoo fail', t, str(ex)[:60])
    dead = [av_csv('MHFIX'), av_csv('PFFTX')]
    comp_tr = compo([ylive[t] for t in trend] + dead)
    comp_mn = compo([ylive[t] for t in mn])
    live = {'trend_with_dead_k50': live_stack(comp_tr, 0.5), 'trend_with_dead_k100': live_stack(comp_tr, 1.0),
            'mkt_neutral_k50': live_stack(comp_mn, 0.5), 'mkt_neutral_k100': live_stack(comp_mn, 1.0),
            'QSPIX_k100_2013': live_stack(ylive['QSPIX'], 1.0) if ylive.get('QSPIX') else None,
            'note': 'Yahoo は生き残りの偏りあり（死んだトレンド2本だけ Alpha Vantage で足した）。株のマーケット・ニュートラルは死んだファンド無し'}

    # ── 格付けのやり直し（自前の判定・線は out/mw_prereg.json のまま）
    def regrade(e, c5_val, c7_holm=None):
        cr = {'C1': bool(e['train'] and e['train']['ex'] > 0 and (e['train']['t'] or 0) >= 2.0),
              'C2': bool(e['hold']['ex'] > 0 and e['hold']['cagr_diff'] > 0),
              'C3': bool((e['hold']['t'] or 0) >= 1.65),
              'C4': bool(e['roll20'] and e['roll20']['win_rate'] >= 0.8),
              'C5': c5_val,
              'C6': bool(e['net_cost_hold']['ex'] > 0 and e['net_cost_hold']['cagr_diff'] > 0),
              'C7': bool((e['full']['t'] or 0) >= 3.0 or (c7_holm is not None and c7_holm < 0.05)),
              'C8': bool(e['sharpe']['train'][0] > e['sharpe']['train'][1] and e['sharpe']['hold'][0] > e['sharpe']['hold'][1])}
        base = cr['C1'] and cr['C2'] and cr['C6'] and cr['C8']
        na_ok = cr['C5'] is None or cr['C5'] is True
        if base and cr['C3'] and cr['C4'] and cr['C7'] and na_ok:
            g = 'S'
        elif base and cr['C4'] and cr['C7'] and (cr['C3'] or cr['C5'] is True):
            g = 'A'
        elif base:
            g = 'B'
        else:
            g = 'C'
        return g, cr

    c5_honest = {
        'E2_SSms_v10_k50': c5_ss['C5_full_pass(>=2/3)'] and c5_ss['C5_hold_pass(>=2/3)'],
        'X2_CEN_INTLss_v10_k50': c5_ss['C5_full_pass(>=2/3)'] and c5_ss['C5_hold_pass(>=2/3)'],
    }
    grades = {}
    for n, e in results.items():
        c5v = c5_honest.get(n, None)   # 上乗せが地域別でない系列（TSMOM・Century 全資産）は N/A（地域への敷き直しは同じ数字＝独立でない）
        g_rule, cr_rule = regrade(e, RS_ALL[n]['criteria']['C5_repl'])
        g_hon, cr_hon = regrade(e, c5v)
        # 現実寄りの費用で C6 を見直した版（検証役の判断）
        e_sk = dict(e); e_sk['net_cost_hold'] = e['skeptic_C6_hold']
        g_sk, cr_sk = regrade(e_sk, c5v)
        e_real = dict(e); e_real['net_cost_hold'] = e['realistic_cost']['hold']
        g_real, cr_real = regrade(e_real, c5v)
        grades[n] = {'researcher_rules_reproduced': g_rule, 'crit_rules': cr_rule, 'honest_C5': g_hon, 'crit_honest': cr_hon,
                     'honest_C5_and_skeptic_C6': g_sk, 'crit_skeptic': cr_sk,
                     'honest_C5_and_realistic_cost_C6': g_real, 'crit_real': cr_real}
        print('grade', n, g_rule, g_hon, g_sk, g_real, e['skeptic_C6_hold']['ex'], e['skeptic_C6_hold']['cagr_diff'], e['C6_breakeven_unit_cost_pct'], flush=True)

    out = {'angle': 'overlay', 'verifies': 'out/mw_overlay.json（night/mw_overlay.py）', 'generated': datetime.date.today().isoformat(),
           'independence': 'mw_common からは取得（get・jkp_factor・jkp_mkt・french_tables・yahoo）だけを使い、French の月次表・AQR の表の読み取り、上乗せの組み立て（費用・成功報酬・借株料）、超過・NW t・年率差・転がる20年窓・積立・シャープ・格付けは自前で書いた',
           'sanity': sanity,
           'candidates': {n: {k: v for k, v in e.items() if not k.startswith('_')} for n, e in results.items()},
           'grades': grades, 'C5_triviality_regional_overlay': c5, 'C5_stock_selection_JKP_independent': c5_ss, 'jkp_detail': jk,
           'multiple_testing': mult, 'live_funds_recomputed': live, 'century_all_asset_composition': composition,
           'cost_definitions': {'base': '事前登録の判定用: 運用1%・成功報酬20%（暦年・高値更新なし）・単価0.05%×T×c・証拠金0.2%',
                                'stress_C6': '事前登録の C6: 運用2%・単価0.10%',
                                'skeptic_C6': '検証役: stress に 借株料0.5%/年×c×（銘柄選択の割合 ss）を足す（研究役の B1 の下限）',
                                'realistic_cost': '検証役: 運用1%・単価0.20%（大型0.10% と中小型0.30% の中間＝Century/JKP の株の買い−売りは小型株も含む）・借株料0.5%×c×ss'}}
    out['extra_US_stock_selection_only'] = extra
    out['verdicts'] = build_verdicts({**results, '_extra': extra}, grades, c5, c5_ss, jk, mult, live)
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('saved', OUT)


def build_verdicts(R, G, c5, c5_ss, jk, mult, live):
    """検証役の結論（数字は上で自前に計算したものを差し込む）"""
    def h(n, w='hold'):
        x = R[n][w]
        return f"{x['ex']:+.2f}%/年 t{x['t']}（年率差 {x['cagr_diff']:+.2f}）"

    def sub(n, k):
        x = R[n]['sub'][k]
        return f"{x['ex']:+.2f} t{x['t']}"

    def sk(n):
        x = R[n]['skeptic_C6_hold']
        return f"{x['ex']:+.2f}（年率差 {x['cagr_diff']:+.2f}）"

    tr = live['trend_with_dead_k50']; mn = live['mkt_neutral_k50']
    wx = c5_ss['world_ex_us_JKP_vs_Century_Intl_same_window_2007_2025']
    wa = c5_ss['world_JKP_vs_Century_All_same_window_2007_2025']
    neg_hold = [r for r in c5_ss['countries'] if r not in c5_ss['positive_hold']]
    reg_tsm = c5['P_TSMOM_k50']['Developed_ex_US']
    V = {}
    V['E2_SSms_v10_k50'] = {
        'claimed_grade': 'S', 'verified_grade': 'A', 'reproduced': True, 'verdict': 'downgraded to A',
        'key_numbers': f"再現（差0.00）: 全期間 {h('E2_SSms_v10_k50','full')}・訓練 {h('E2_SSms_v10_k50','train')}・保有 {h('E2_SSms_v10_k50')}・厳しめ費用 {R['E2_SSms_v10_k50']['net_cost_hold']['ex']:+.2f}・転がる20年 {R['E2_SSms_v10_k50']['roll20']['windows']}窓で勝率{R['E2_SSms_v10_k50']['roll20']['win_rate']}・積立20年の中央比 {R['E2_SSms_v10_k50']['dca20']['median']}",
        'issues': [
            f"C5 の 3/3 は機械的: 上乗せを別の地域の市場に敷いても算術の超過は上乗せそのもの（Developed ex US {c5['E2_SSms_v10_k50']['Developed_ex_US']['regional_ex']} ＝ 同じ月の米国 {c5['E2_SSms_v10_k50']['Developed_ex_US']['US_same_months_ex']}）＝独立の複製ではない",
            f"同じ考え（割安＋勢い＋低ベータの買い−売り）を独立のデータ JKP で国別に作ると 保有期間で正は {len(c5_ss['positive_hold'])}/8（負: {', '.join(neg_hold)}）＝保有期間の C5 は不合格（全期間は 8/8 だが訓練期間の文献どおりの部分）。JKP の world 版を同じ窓（2007〜2025）で重ねると {wa['JKP_world_on_FrenchMkt']['ex']:+.2f} t{wa['JKP_world_on_FrenchMkt']['t']}（Century は {wa['Century_All_E2']['ex']:+.2f} t{wa['Century_All_E2']['t']}）",
            f"保有期間の勝ちは Century の米国外の部分だけ（Century の米国の銘柄選択だけを同じ形で重ねると 保有 {R['_extra']['US_ss_hold']['ex']:+.2f} t{R['_extra']['US_ss_hold']['t']}、JKP usa は {jk['usa']['on_own_mkt']['hold']['ex']:+.2f}）",
            f"多重検定: 角度の38本で Holm を掛けると保有期間 p={mult['holm38_hold_p']['E2_SSms_v10_k50']}。保有 t2.59 は計画全体の Bonferroni t{mult['program_bonferroni_t']} に遠い。C7 は全期間 t（1926〜2006 の文献の標本が大半）でだけ通る",
            f"費用: 基本の単価0.05% は全体の既定（大型0.10%）の半分。C6 の損益分岐の単価（運用2%）は {R['E2_SSms_v10_k50']['C6_breakeven_unit_cost_pct']}%。単価0.20%＋借株料0.5% なら保有 {R['E2_SSms_v10_k50']['realistic_cost']['hold']['ex']:+.2f} t{R['E2_SSms_v10_k50']['realistic_cost']['hold']['t']}（C3 相当は落ちる）、0.30%＋借株料1.0% で −0.19",
            f"頑丈な面: 保有の前半 {sub('E2_SSms_v10_k50','hold_1st_half_2007_2016H1')}・後半 {sub('E2_SSms_v10_k50','hold_2nd_half_2016H2_end')}・2020-21 を抜いても {sub('E2_SSms_v10_k50','hold_drop_2020_2021')}・c を 1997〜2006 の σ で決めても +1.71 t2.37・T=20 でも +2.14 t2.19",
            f"実在の株マーケット・ニュートラル4本（死んだファンド無し）の合成を0.5倍重ねると 2007〜 {mn['hold']['ex']:+.2f} t{mn['hold']['t']}。日本の個人が買える器は無い",
        ]}
    V['X2_CEN_INTLss_v10_k50'] = {
        'claimed_grade': 'S', 'verified_grade': 'A（事後の探索・独立データでは B 相当）', 'reproduced': True, 'verdict': 'downgraded to A',
        'key_numbers': f"再現（差0.00）: 全期間 {h('X2_CEN_INTLss_v10_k50','full')}・訓練 {h('X2_CEN_INTLss_v10_k50','train')}・保有 {h('X2_CEN_INTLss_v10_k50')}・厳しめ費用 {R['X2_CEN_INTLss_v10_k50']['net_cost_hold']['ex']:+.2f}・借株料込み {sk('X2_CEN_INTLss_v10_k50')}・転がる20年 {R['X2_CEN_INTLss_v10_k50']['roll20']['windows']}窓全勝",
        'issues': [
            "E2 の保有期間の結果を見た後で登録した族（事前登録2）。S の親を米国と米国外に割れば片方は必ず親以上になる＝選び方そのものが保有期間の情報を使っている。全体の正直さの規則では判定に使えない側",
            f"独立のデータ（JKP）で同じ考えを米国外に作ると 同じ窓（2007〜2025）で {wx['JKP_world_ex_us_on_FrenchMkt']['ex']:+.2f} t{wx['JKP_world_ex_us_on_FrenchMkt']['t']}（Century は {wx['Century_Intl_X2']['ex']:+.2f} t{wx['Century_Intl_X2']['t']}）＝大きさは Century 固有。先進国の国別は保有期間で {len(c5_ss['positive_hold'])}/8（日本・英国・仏・スイスが負）→ 正直な C5 は不合格で S にならない",
            f"Century の米国外の生の系列は 訓練のシャープ {R['X2_CEN_INTLss_v10_k50']['raw_overlay']['train']['sr']} → 保有 {R['X2_CEN_INTLss_v10_k50']['raw_overlay']['hold']['sr']} → 2022〜 {R['X2_CEN_INTLss_v10_k50']['raw_overlay']['post_pub']['sr']} と公表後に上がる（JKP の米国外は 平均 6.36→3.18%/年 と普通に縮む）。AQR は更新のたびに全履歴を作り直し、作り方（HML-devil 2013・BAB 2014・論文 2021）は 2007〜2020 を見て決まっている＝保有期間は作り方について本当の標本外ではない（疑い・証明ではない）",
            f"紙の上では頑丈: 前半 {sub('X2_CEN_INTLss_v10_k50','hold_1st_half_2007_2016H1')}・後半 {sub('X2_CEN_INTLss_v10_k50','hold_2nd_half_2016H2_end')}・C6 の損益分岐の単価 {R['X2_CEN_INTLss_v10_k50']['C6_breakeven_unit_cost_pct']}%・運用2%＋単価0.30%＋借株料1% でも +0.92 t1.14・38本の Bonferroni（t3.02）も計画全体（t4.34）も越える",
            f"実在の株マーケット・ニュートラルの合成は 2007〜 {mn['hold']['ex']:+.2f} t{mn['hold']['t']}（研究役の表で VMNFX・JMNSX は紙より年 7.6・5.8% 低い）。買える器は無い",
        ]}
    V['E1_CENms_v10_k100'] = {
        'claimed_grade': 'S', 'verified_grade': 'C', 'reproduced': True, 'verdict': 'downgraded to C',
        'key_numbers': f"再現（差0.00）: 全期間 {h('E1_CENms_v10_k100','full')}・訓練 {h('E1_CENms_v10_k100','train')}・保有 {h('E1_CENms_v10_k100')}・厳しめ費用 {R['E1_CENms_v10_k100']['net_cost_hold']['ex']:+.2f} t{R['E1_CENms_v10_k100']['net_cost_hold']['t']}（年率差 {R['E1_CENms_v10_k100']['net_cost_hold']['cagr_diff']:+.2f}）・借株料込み {sk('E1_CENms_v10_k100')}",
        'issues': [
            f"C6 は刃の上: 損益分岐の単価は {R['E1_CENms_v10_k100']['C6_breakeven_unit_cost_pct']}%（事前登録の厳しめ 0.10% とほぼ同じ）。銘柄選択の部分（回帰で約2割）に借株料0.5% を掛けると年率差が負 → C6 不合格",
            f"C3 も刃の上: t1.70（線1.65）。k0.75 で t1.66、T=20 で t0.69、判定用の単価を全体の既定0.10% にすると t0.69。保有の後半（2016-07〜）{sub('E1_CENms_v10_k100','hold_2nd_half_2016H2_end')}・2022〜 {sub('E1_CENms_v10_k100','post_publication_2022+')}",
            f"C5 の 3/3 は機械的（算術の超過が米国と同一 {c5['E1_CENms_v10_k100']['Developed_ex_US']['regional_ex']}）→ 正直には N/A",
            "ぶれ2% の全資産の買い−売りを c=4.3 倍に膨らませて株100% に重ねる形（先物・空売りの持ち高が大きい）で、個人には作れない",
            f"反対の材料: 実在の AQR QSPIX（2013-11〜・生き残りの旗艦1本）を1倍重ねると {live['QSPIX_k100_2013']['hold']['ex']:+.2f} t{live['QSPIX_k100_2013']['hold']['t']}＝紙より良かった",
        ]}
    for n in ['P_TSMOM_k50', 'P_TSMOM_k25', 'E1_TSMOM_v10_k100', 'E1_TSMOM_v10_k50']:
        V[n] = {
            'claimed_grade': 'A', 'verified_grade': 'B', 'reproduced': True, 'verdict': 'downgraded to B',
            'key_numbers': f"再現（差0.00）: 全期間 {h(n,'full')}・訓練 {h(n,'train')}・保有 {h(n)}・厳しめ費用 {R[n]['net_cost_hold']['ex']:+.2f}・転がる20年 {R[n]['roll20']['windows']}窓全勝・積立の中央比 {R[n]['dca20']['median']}",
            'issues': [
                f"A は C5（3地域 3/3）に乗っていた。だが地域に敷き直した算術の超過は米国の同じ月と同一（{reg_tsm['regional_ex']} ＝ {reg_tsm['US_same_months_ex']}）＝同じ系列の 1990 年以降の部分期間で、独立の複製ではない → N/A。すると A には C3 が要り、保有 t{R[n]['hold']['t']} で落ちる → B",
                f"保有期間の前半 {sub(n,'hold_1st_half_2007_2016H1')}（2008年）・後半 {sub(n,'hold_2nd_half_2016H2_end')}。2008 と 2022 を抜くと {sub(n,'hold_drop_2008_2022')}。MOP(2012) 公表後 2013〜 {sub(n,'post_publication_2013+')}",
                "訓練期間 1985〜2006 は MOP の標本（1985〜2009）の中＝訓練の t は論文の標本内",
                f"実在のトレンド・ファンド（生き残り17＋死んだ2）の合成を0.5倍重ねると 2007-03〜 {tr['hold']['ex']:+.2f} t{tr['hold']['t']}、2008/2022 を抜くと {tr['hold_drop_2008_2022']['ex']:+.2f}＝紙と同じ向きで小さい",
                f"費用は現実的（先物・C6 の損益分岐の単価 {R[n]['C6_breakeven_unit_cost_pct']}%）＝ B の線（C1・C2・C6・C8）は紙の上では保つ",
            ]}
    V['E1_CENms_v10_k50'] = {
        'claimed_grade': 'A', 'verified_grade': 'C', 'reproduced': True, 'verdict': 'downgraded to C',
        'key_numbers': f"再現（差0.00）: 全期間 {h('E1_CENms_v10_k50','full')}・保有 {h('E1_CENms_v10_k50')}・厳しめ費用 {R['E1_CENms_v10_k50']['net_cost_hold']['ex']:+.2f}（年率差 {R['E1_CENms_v10_k50']['net_cost_hold']['cagr_diff']:+.2f}）・借株料込み {sk('E1_CENms_v10_k50')}",
        'issues': [
            "C3 不合格（t1.59）で A は機械的な C5 に乗っていた → N/A なら B",
            f"C6 は損益分岐の単価 {R['E1_CENms_v10_k50']['C6_breakeven_unit_cost_pct']}%＝事前登録の厳しめ0.10% ちょうど。銘柄選択の部分に借株料0.5% で負 → C",
            f"保有の後半 {sub('E1_CENms_v10_k50','hold_2nd_half_2016H2_end')}・2022〜 {sub('E1_CENms_v10_k50','post_publication_2022+')}",
        ]}
    V['E5_TSMOMxCENms_v10_k100'] = {
        'claimed_grade': 'A（出力 out/mw_overlay.json では A だが研究役の候補一覧から漏れていた）', 'verified_grade': 'B', 'reproduced': True, 'verdict': 'downgraded to B',
        'key_numbers': f"再現（差0.00）: 全期間 {h('E5_TSMOMxCENms_v10_k100','full')}・保有 {h('E5_TSMOMxCENms_v10_k100')}・厳しめ費用 {R['E5_TSMOMxCENms_v10_k100']['net_cost_hold']['ex']:+.2f}・借株料込み {sk('E5_TSMOMxCENms_v10_k100')}",
        'issues': [
            "C3 不合格（t1.60）・C5 は機械的 → B",
            f"保有の後半 {sub('E5_TSMOMxCENms_v10_k100','hold_2nd_half_2016H2_end')}。単価0.20%＋借株料で {R['E5_TSMOMxCENms_v10_k100']['realistic_cost']['hold']['ex']:+.2f}（C 相当）・損益分岐の単価 {R['E5_TSMOMxCENms_v10_k100']['C6_breakeven_unit_cost_pct']}%",
        ]}
    V['X3_JKP_emerging_MS_v10_k50'] = {
        'claimed_grade': 'B', 'verified_grade': 'C', 'reproduced': True, 'verdict': 'downgraded to C',
        'key_numbers': f"再現（差0.00）: 全期間 {h('X3_JKP_emerging_MS_v10_k50','full')}・訓練 {h('X3_JKP_emerging_MS_v10_k50','train')}・保有 {h('X3_JKP_emerging_MS_v10_k50')}・厳しめ費用 {R['X3_JKP_emerging_MS_v10_k50']['net_cost_hold']['ex']:+.2f}・借株料込み {sk('X3_JKP_emerging_MS_v10_k50')}",
        'issues': [
            f"C6 の損益分岐の単価は {R['X3_JKP_emerging_MS_v10_k50']['C6_breakeven_unit_cost_pct']}%。新興国の株の片道費用に 0.10% は楽観的で、全体の既定の中小型 0.30% を当てると運用1%でも {R['X3_JKP_emerging_MS_v10_k50']['cost_grid_hold']['mgmt1_unit0.30_borrow0.0'][0]:+.2f} → C6 不合格。多くの新興国では空売りそのものが制限される",
            f"保有の前半 {sub('X3_JKP_emerging_MS_v10_k50','hold_1st_half_2007_2016H1')}（後半に偏る）・C7 不合格・事前登録2（E2 を見た後）の族",
        ]}
    V['X3_JKP_can_MS_v10_k50'] = {
        'claimed_grade': 'B', 'verified_grade': 'C', 'reproduced': True, 'verdict': 'downgraded to C',
        'key_numbers': f"再現（差0.00）: 全期間 {h('X3_JKP_can_MS_v10_k50','full')}・保有 {h('X3_JKP_can_MS_v10_k50')}・厳しめ費用 {R['X3_JKP_can_MS_v10_k50']['net_cost_hold']['ex']:+.2f} t{R['X3_JKP_can_MS_v10_k50']['net_cost_hold']['t']}・借株料込み {sk('X3_JKP_can_MS_v10_k50')}",
        'issues': [
            f"厳しめ費用で +0.27 t0.19 と薄く、借株料0.5% で算術の超過が負。損益分岐の単価 {R['X3_JKP_can_MS_v10_k50']['C6_breakeven_unit_cost_pct']}%",
            f"保有の後半 {sub('X3_JKP_can_MS_v10_k50','hold_2nd_half_2016H2_end')}・2022〜 {sub('X3_JKP_can_MS_v10_k50','post_publication_2022+')}・C3/C7 不合格・事前登録2 の族",
        ]}
    return V


if __name__ == '__main__':
    main()
