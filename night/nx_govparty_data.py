#!/usr/bin/env python3
"""night/nx_govparty_data.py — nx 角度 govparty（政府への依存度の高い業種 × 大統領の党）の**データの取得・整形だけ**
（成績は計算しない・業種や市場のリターンは一切読まない・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…別のSessionで検証していない新たな分析を」。
事前登録: out/nx_govparty_prereg.json（測る前に固定）／全体の線: out/nx_prereg.json（C1〜C8・格付け）。

何をするか
  Belo, Gala & Li（2013, JFE／2011年10月の working paper の付録 A-1）の『業種の政府への依存度』を、BEA のベンチマーク
  産業連関表（Use 表）ごとに作り、Ken French の49業種と GICS 11 セクターへ畳む。
     依存度 e_i = x_i / y_i,   x = (I − A)^(-1) c
       c_i = 行 i（財）を政府の最終需要（連邦〔国防・非国防〕＋州と地方・消費と投資）が買った額（行ごとに足して負は0）
       A_ij = U_ij / g_j（U_ij = 産業 j が財 i を中間財として買った額、g_j = 産業 j の産出＝その列の全行の合計〔付加価値・輸入を含む・合計行は除く〕）
       y_i = 財 i の産出＝行 i の全列の合計（中間需要＋最終需要〔輸入の負の列・在庫の増減を含む〕・合計列は除く）＝BGL の手順4
     BGL との違い: BGL は BEA の『産業×財の総所要量表』をそのまま使った。ここでは Use 表から (I − A)^(-1) を自前で作る
     （財＝産業の近似。各年の表の書式が違い、総所要量表が全年そろっていないため）。財と産業の番号は同じ表の中で同じ体系。
  政府の最終需要の列（各年の表の書類で名前を確かめた・FD_DOC）:
     1947・1958: 97 連邦政府の購入（国防と非国防が分かれていない）・98 州と地方政府の購入
     1963: 9710 連邦・国防／9720 連邦・その他／9860〜9890 州と地方
     1967: 971000 連邦・国防／972000 連邦・その他／986000〜989000 州と地方
     1972〜1987: 960000 連邦・国防／970000 連邦・非国防／98xxxx・99xxxx 州と地方
     1992: 9600C0・9600I0 国防（消費・投資）／9700C0・9700I0 非国防／98xxxx・99xxxx 州と地方
     1997・2002: F06* 国防／F07* 非国防／F08*・F09* 州と地方      2007・2017: F06* 国防／F07* 非国防／F10* 州と地方
  ★2002年以降の表は、政府の消費支出が『一般政府という産業』（S00500 連邦国防・S00600 連邦非国防・S00700／GSLGE・GSLGH・GSLGO 州と地方）
    を経由する（民間の財は一般政府の産業が中間財として買い、その産出を F06C00 などの最終需要が買う）。1997年以前は民間の財を
    最終需要の列が直接買う（政府の産業〔84・820000・S00500〕は付加価値だけ）。レオンチェフの系に一般政府の産業を入れているので、
    どちらの書式でも民間の業種の『直接＋間接』の依存度は同じ定義で出る（探索の direct は、一般政府の産業が買った分を直接に数える）。
  系（レオンチェフの行列）に入れる番号: 行にも列にもある産業の番号（政府企業・一般政府の産業・出張と事務用品のダミー産業・
     家計・海外の産業を含む）。入れないもの: 輸入の行（80・8001・800100・800000・S00300）・屑と中古品で列の無い行・付加価値の行・
     合計（T0**）・在庫評価調整（IVA）・列しか無い買うだけの産業（行が無い＝需要されない）。
     1987年表だけ、新設と補修の建設（11xxxx・12xxxx）は行が細かく列が 110000 一本なので、列の無い 11・12 の行を 110000 に束ねる
     （行の合計が 110000 の列の合計と一致することを assert する）。
  French 49 へ: 部門 → French の割合は night/nx_leadlag_data.py の写し（sic_era_shares・era85_shares・naics_era_shares）を
     そのまま使う（書き換えない）。業種の依存度 = Σ_部門 max(y,0)×割合×e ÷ Σ_部門 max(y,0)×割合（産出で加重）。
     GICS 11 へは French 49 を FR2GICS で畳む（French の産出で加重）。
  変形（探索用）: all（主）・federal・defense・nondefense（連邦非国防＋州と地方）・statelocal・direct_all（一段目だけ）。
     1947・1958 は連邦が国防と非国防に分かれていないので defense・nondefense は作らない（None）。

政治の暦（公の記録）: 大統領の党と就任日・党が替わった選挙の結果が分かった日・上院の多数党（https://www.senate.gov/history/partydiv.htm
  を 2026-09-28 に読んで確かめた）・報告のみの米国外5か国の首相／首班の左右（英・加・豪・独・日）。

使い方: python3 night/nx_govparty_data.py          → out/_nx_cache/nx_govparty_io.json（sha256 を表示）
        python3 night/nx_govparty_data.py --show   → 表ごとの被覆・恒等式の検算・分布（産業連関の事実だけ。リターンは読まない）
"""
import sys, os, json, hashlib, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N            # noqa: E402
import nx_leadlag_data as L       # noqa: E402  写しと表の読み手を流用（書き換えない）

OUT = os.path.join(N.CACHE, 'nx_govparty_io.json')
TABLES = ['1947', '1958', '1963', '1967', '1972', '1977', '1982', '1987', '1992', '1997', '2002', '2007', '2017']

# ── いつから使えるか（測る前に固定）。signal = その月末から使ってよい最初の月、hold = 最初に持つ月。
#    1947 は BGL（付録 A-1）が「1947年表の情報は1955年に公開」と書き、1955年7月から使っている → 年しか分からないので12月公表とみなす（遅い側）。
#    nx_leadlag の SCHEDULE_EARLY は BLS の当初版（1951）を採ったが、手元の85部門表は OBE の並べ直し（1970年ごろ）なので、ここでは遅い BGL の日付を採る。
#    1958 以降は nx_leadlag と同じ（1958 は SCB 1965年9月号・1963 以降は L.SCHEDULE）
SCHEDULE = ([{'table': '1947', 'published': '1955（BGL 2011 WP 付録 A-1 の記述。月は不明→12月とみなす）。手元の85部門表は OBE の並べ直し（様式の後知恵あり）', 'signal': 195601, 'hold': 195602},
             {'table': '1958', 'published': L.SCHEDULE_EARLY[1]['published'], 'signal': L.SCHEDULE_EARLY[1]['signal'], 'hold': L.SCHEDULE_EARLY[1]['hold']}]
            + [dict(s) for s in L.SCHEDULE])
NOT_SCHEDULED = dict(L.NOT_SCHEDULED)

# ── 最終需要の列の書類（各年の Sectoring Plan / Format / IO-Code の文面で確かめた名前）
FD_DOC = {
    '1947': '1947 Transactions 85-detail Format.doc「numbering scheme … correspond to that of the 1958 table」「transferred imports are shown as a negative final demand column」→ 92 PCE・93 固定資本・94 在庫・95 輸出・96 移転輸入（負）・97 連邦・98 州と地方',
    '1958': '1958 IO Transactions Format.rtf: 92 Personal Consumption Expenditures・93 Gross Private Fixed Capital Formation・94 Net Inventory Change・95 Net Exports・97 Federal Government Purchases・98 State and Local Government Purchases',
    '1963': '1963 Sectoring Plan.rtf: 96.60 PCE・96.70 GPFCF・96.80 Net inventory change・96.90 Net exports・97.10 Federal Government purchases, defense・97.20 Federal Government purchases, other・98.60〜98.90 State & local government purchases',
    '1967': '1967 Sectoring Plan.doc: 910000 PCE・920000 GPFCF・930000 在庫・940000 Net exports・971000 Federal, defense・972000 Federal, other・986000〜989000 State & local',
    '1972': '1972 Sectoring Plan.doc: 910000〜950000（PCE・固定資本・在庫・輸出・輸入）・960000 Federal, defense・970000 Federal, other・980000 S&L education・991000〜993000 S&L',
    '1977': '1977 Sectoring Plan.rtf: 1972 と同じ体系（980001〜 S&L）',
    '1982': 'Io-code.doc: 960000 Federal Government purchases, national defense・970000 nondefense・98xxxx・99xxxx S&L',
    '1987': '1982 と同じ6桁の体系（書類に最終需要の名前の表は無い。列の番号と合計の大きさが1982年と同じ形）',
    '1992': 'io-code.txt: 9600C0/9600I0 national defense（消費・投資）・9700C0/9700I0 nondefense・9800xx・99xxxx State and local',
    '1997': 'IO-CodeDetail.txt: F06C00/F06I00 National defense・F07C00/F07I00 Nondefense・F08C00/F08I00 S&L education・F09C00/F09I00 S&L other',
    '2002': 'Appendix B.xls: F06C/F06I Federal defense・F07C/F07I nondefense・F08C/F08I S&L education・F09C/F09I S&L other',
    '2007': 'xlsx の見出し: F06C00/F06S00/F06E00/F06N00 Federal defense・F07* nondefense・F10* State and local（T001/T004/T007 は合計）',
    '2017': 'xlsx の見出し: 2007 と同じ（T001 は合計）',
}
# 一般政府の産業（産出を政府の最終需要へ売る。direct_all の計算で『政府が直接買った』とみなす中間財の買い手）
GOVIND = {'1947': ['84'], '1958': ['84'], '1963': ['8400'], '1967': ['840000'],
          '1972': ['820000'], '1977': ['820000'], '1982': ['820000'], '1987': ['820000'], '1992': ['820000'],
          '1997': ['S00500'], '2002': ['S00500', 'S00600', 'S00700'], '2007': ['S00500', 'S00600', 'S00700'],
          '2017': ['S00500', 'S00600', 'GSLGE', 'GSLGH', 'GSLGO']}
# 在庫評価調整（会計の調整で財ではない）→ 系に入れない
IVA = {'1947': '87', '1958': '87', '1963': '8700', '1967': '870000', '1972': '850000', '1977': '850000', '1982': '850000',
       '1987': '850000', '1992': '850000', '1997': 'S00700'}
CATS = {'all': {'fed_def', 'fed_nondef', 'fed', 'sl'}, 'federal': {'fed_def', 'fed_nondef', 'fed'},
        'defense': {'fed_def'}, 'nondefense': {'fed_nondef', 'sl'}, 'statelocal': {'sl'}}


def fd_class(y, c):
    """列の番号 → 'fed_def' | 'fed_nondef' | 'fed'（連邦・分かれていない） | 'sl' | 'other'（民間の最終需要・輸出入・在庫） | 'total' | None（産業）"""
    if c.startswith('T0'):
        return 'total'
    if y in ('1947', '1958'):
        return {'92': 'other', '93': 'other', '94': 'other', '95': 'other', '96': 'other', '97': 'fed', '98': 'sl'}.get(c)
    if y == '1963':
        if c in ('9660', '9670', '9680', '9690'):
            return 'other'
        if c == '9710':
            return 'fed_def'
        if c == '9720':
            return 'fed_nondef'
        if c[:2] == '98':
            return 'sl'
        return 'total' if c[:2] == '99' else None
    if y == '1967':
        if c in ('910000', '920000', '930000', '940000'):
            return 'other'
        if c == '971000':
            return 'fed_def'
        if c == '972000':
            return 'fed_nondef'
        if c[:2] == '98':
            return 'sl'
        return 'total' if c[:2] == '99' else None
    if y in ('1972', '1977', '1982', '1987', '1992'):
        if c[:2] in ('91', '92', '93', '94', '95'):
            return 'other'
        if c[:2] == '96':
            return 'fed_def'
        if c[:2] == '97':
            return 'fed_nondef'
        if c[:2] in ('98', '99'):
            return 'sl'
        return None
    if c[:1] == 'F':
        k = c[:3]
        if k in ('F01', 'F02', 'F03', 'F04', 'F05'):
            return 'other'
        if k == 'F06':
            return 'fed_def'
        if k == 'F07':
            return 'fed_nondef'
        if k in ('F08', 'F09', 'F10'):
            return 'sl'
        raise ValueError(f'{y}: 分からない最終需要の列 {c}')
    return None


def is_primary_row(y, r):
    """付加価値・輸入・合計の行（財ではない）"""
    if r.startswith(('T0', 'V0')) or r in ('S00300', 'S00900'):
        return True
    if y in ('1947', '1958'):
        return r in ('80', '89')
    if y == '1963':
        return r in ('8001', '8002', '8900') or r[:2] in ('88', '89', '90')
    return r[:2] in ('80', '88', '89', '90') or (y == '1967' and r == '950000')


def build_table(y, M, NC):
    import numpy as np
    pairs = L.read_table(y)
    rows = {r for r, _ in pairs}
    cols = {c for _, c in pairs}
    ind_cols = {c for c in cols if fd_class(y, c) is None}
    fd_cols = {c: fd_class(y, c) for c in cols if fd_class(y, c) not in (None, 'total')}
    # 行 → 系の番号（1987 の建設だけ束ねる）
    agg = {}
    for r in rows:
        if r in ind_cols:
            agg[r] = r
    if y == '1987':
        grp = [r for r in rows if r[:2] in ('11', '12') and r not in ind_cols]
        for r in grp:
            agg[r] = '110000'
        rt = sum(v for (r, c), v in pairs.items() if r in grp and fd_class(y, c) != 'total')
        ct = sum(v for (r, c), v in pairs.items() if c == '110000')
        assert abs(rt - ct) <= 1e-3 * ct, ('1987 建設の束ねの検算が合わない', rt, ct)
    S = sorted({agg[r] for r in agg if not is_primary_row(y, r)} - {IVA.get(y)})
    ix = {c: k for k, c in enumerate(S)}
    n = len(S)
    U = np.zeros((n, n)); g = np.zeros(n); yv = np.zeros(n)
    c_cat = {k: np.zeros(n) for k in ('fed_def', 'fed_nondef', 'fed', 'sl')}
    for (r, c), v in pairs.items():
        if c in ix and not r.startswith('T0'):
            g[ix[c]] += v                                  # 産業 c の産出（列の全行・合計行は除く）
        if r not in agg or agg[r] not in ix:
            continue
        i = ix[agg[r]]
        if fd_class(y, c) == 'total':
            continue
        yv[i] += v                                         # 財 r の産出（行の全列・合計列は除く）
        if c in ix:
            U[i, ix[c]] += v
        elif c in fd_cols and fd_cols[c] in c_cat:
            c_cat[fd_cols[c]][i] += v
    A = np.divide(U, g, out=np.zeros_like(U), where=g > 0)
    IminusA = np.eye(n) - A
    res = {'era': 'SIC85' if y in ('1947', '1958') else ('SIC' if int(y) <= 1992 else 'NAICS'), 'n_system': n}
    # 恒等式の検算: 最終需要すべて（輸入・在庫を含む）を c に入れると x は y に戻るはず（財＝産業の近似の誤差の大きさ）
    c_fd_all = np.zeros(n)
    for (r, c), v in pairs.items():
        if r in agg and agg[r] in ix and c in fd_cols:
            c_fd_all[ix[agg[r]]] += v
    x_all = np.linalg.solve(IminusA, c_fd_all)
    ok = yv > 0
    dev = np.abs(x_all[ok] / yv[ok] - 1)
    wdev = float((np.abs(x_all[ok] - yv[ok])).sum() / yv[ok].sum())
    res['identity_check'] = {'median_abs_dev_x_over_y': round(float(np.median(dev)), 4), 'output_weighted_abs_dev': round(wdev, 4),
                             'share_codes_dev_gt_10pct': round(float((dev > 0.10).mean()), 3)}
    expo = {}
    diag_v = {}
    for name, cats in list(CATS.items()) + [('direct_all', CATS['all'])]:
        if y in ('1947', '1958') and name in ('defense', 'nondefense'):
            expo[name] = None
            continue
        cvec = sum(c_cat[k] for k in cats)
        cvec = np.clip(cvec, 0, None)                          # 政府の売り（手数料など）の負の値は『買っていない』＝0
        if name == 'direct_all':
            gi = [ix[k] for k in GOVIND[y] if k in ix]
            dvec = cvec.copy()
            for k in gi:
                s_k = min(1.0, cvec[k] / g[k]) if g[k] > 0 else 0.0   # 一般政府の産業の産出のうち政府の最終需要へ行く割合
                dvec = dvec + U[:, k] * s_k
            x = dvec
        else:
            x = np.linalg.solve(IminusA, cvec)
        raw = np.divide(x, yv, out=np.full(n, np.nan), where=yv > 0)
        clipped_hi = int(np.nansum(raw > 1.0)); clipped_lo = int(np.nansum(raw < 0.0))
        e = np.clip(raw, 0.0, 1.0)
        expo[name] = {S[k]: (None if np.isnan(e[k]) else float(e[k])) for k in range(n)}
        diag_v[name] = {'gov_final_demand_total': round(float(cvec.sum()), 1), 'clipped_above_1': clipped_hi, 'clipped_below_0': clipped_lo,
                        'max_raw': round(float(np.nanmax(raw)), 3) if np.isfinite(np.nanmax(raw)) else None}
    res['by_variant'] = diag_v
    # 部門 → French の割合（nx_leadlag の写しをそのまま）
    codes = sorted(rows | cols)
    if y in ('1947', '1958'):
        sh, route = L.era85_shares(y, codes, M)
    elif int(y) <= 1992:
        sh, route = L.sic_era_shares(y, codes, M)
    else:
        sh, route = L.naics_era_shares(y, codes, M, NC)
    rowtot = {}
    for (r, c), v in pairs.items():
        if fd_class(y, c) != 'total':
            rowtot[r] = rowtot.get(r, 0.0) + v
    fr = {}
    out_F = {f: 0.0 for f in L.FR49}
    for name in expo:
        if expo[name] is None:
            fr[name] = None
            continue
        num = {f: 0.0 for f in L.FR49}; den = {f: 0.0 for f in L.FR49}
        for r, s in sh.items():
            if r not in agg or agg[r] not in ix:
                continue
            e = expo[name][agg[r]]
            w = max(rowtot.get(r, 0.0), 0.0)
            if e is None or w <= 0:
                continue
            for f, a in s.items():
                num[f] += w * a * e; den[f] += w * a
                if name == 'all':
                    out_F[f] += w * a
        fr[name] = {f: (num[f] / den[f] if den[f] > 0 else None) for f in L.FR49}
    gics = {}
    for name, d in fr.items():
        if d is None:
            gics[name] = None
            continue
        num = {s: 0.0 for s in L.GICS11}; den = {s: 0.0 for s in L.GICS11}
        for f, e in d.items():
            if f in L.FR2GICS and e is not None and out_F[f] > 0:
                num[L.FR2GICS[f]] += out_F[f] * e; den[L.FR2GICS[f]] += out_F[f]
        gics[name] = {s: (num[s] / den[s] if den[s] > 0 else None) for s in L.GICS11}
    # 分布（BGL の表1と比べる: 詳細部門の平均 13.2%・90%超の業種が 30% 未満）
    priv = [agg[r] for r in sh if r in agg and agg[r] in ix]
    ev = [expo['all'][k] for k in set(priv) if expo['all'][k] is not None]
    res['detail_distribution_all'] = {'n_private_codes': len(ev), 'mean': round(sum(ev) / len(ev), 4) if ev else None,
                                      'share_below_0.30': round(sum(1 for v in ev if v < 0.30) / len(ev), 3) if ev else None}
    res['mapping'] = {'codes_with_french_shares': len(sh), 'via_plan': route.get('plan'), 'via_parent_fallback_n': len(route.get('parent_fallback', [])),
                      'unmapped': route.get('unmapped', [])[:40], 'french_without_exposure': [f for f in L.FR49 if fr['all'][f] is None]}
    res['gov_industries_in_system'] = [k for k in GOVIND[y] if k in ix]
    return {'fr49': fr, 'fr49_output': out_F, 'gics11': gics}, res


# ───────────────────────── 政治の暦（公の記録） ─────────────────────────
PRESIDENTS = [  # (名前, 党, 就任日)。党の出典: 公の記録（National Archives / whitehouse.gov の歴代大統領）。任期途中の昇格（Truman・Johnson・Ford）は党が替わらない
    ('Coolidge', 'R', '1923-08-02'), ('Hoover', 'R', '1929-03-04'), ('F. Roosevelt', 'D', '1933-03-04'), ('Truman', 'D', '1945-04-12'),
    ('Eisenhower', 'R', '1953-01-20'), ('Kennedy', 'D', '1961-01-20'), ('L. Johnson', 'D', '1963-11-22'), ('Nixon', 'R', '1969-01-20'),
    ('Ford', 'R', '1974-08-09'), ('Carter', 'D', '1977-01-20'), ('Reagan', 'R', '1981-01-20'), ('G.H.W. Bush', 'R', '1989-01-20'),
    ('Clinton', 'D', '1993-01-20'), ('G.W. Bush', 'R', '2001-01-20'), ('Obama', 'D', '2009-01-20'), ('Trump', 'R', '2017-01-20'),
    ('Biden', 'D', '2021-01-20'), ('Trump', 'R', '2025-01-20')]
# 党が替わった選挙の『結果が分かった日』（探索 E9 の選挙の暦）。2000年は Bush v. Gore（12-12）の翌日の Gore の敗北宣言 12-13
SWITCH_ELECTIONS = [('1932-11-08', 'D'), ('1952-11-04', 'R'), ('1960-11-08', 'D'), ('1968-11-05', 'R'), ('1976-11-02', 'D'), ('1980-11-04', 'R'),
                    ('1992-11-03', 'D'), ('2000-12-13', 'R'), ('2008-11-04', 'D'), ('2016-11-08', 'R'), ('2020-11-07', 'D'), ('2024-11-05', 'R')]
# 上院の多数党の変わり目（https://www.senate.gov/history/partydiv.htm を 2026-09-28 に読んだ。議会の開会は奇数年の1月3日として扱う・1953年以降）
SENATE = [('1953-01-03', 'R'), ('1955-01-03', 'D'), ('1981-01-03', 'R'), ('1987-01-03', 'D'), ('1995-01-03', 'R'),
          ('2001-01-03', 'D'), ('2001-01-20', 'R'), ('2001-06-06', 'D'), ('2002-11-12', 'R'), ('2007-01-03', 'D'),
          ('2015-01-03', 'R'), ('2021-01-03', 'R'), ('2021-01-20', 'D'), ('2025-01-03', 'R')]
# 報告のみ（格付けに使わない）: 米国外の首相／首班の党の左右（就任日）。左 = 英労働党・加自由党・豪労働党・独 SPD・日 民主党。
INTL_HEADS = {
    'gbr': [('1997-05-02', 'L', 'Blair/Brown 労働党'), ('2010-05-11', 'R', 'Cameron〜Sunak 保守党'), ('2024-07-05', 'L', 'Starmer 労働党')],
    'can': [('1993-11-04', 'L', 'Chrétien/Martin 自由党'), ('2006-02-06', 'R', 'Harper 保守党'), ('2015-11-04', 'L', 'Trudeau/Carney 自由党')],
    'aus': [('1996-03-11', 'R', 'Howard 自由党'), ('2007-12-03', 'L', 'Rudd/Gillard 労働党'), ('2013-09-18', 'R', 'Abbott〜Morrison 自由党'), ('2022-05-23', 'L', 'Albanese 労働党')],
    'deu': [('1998-10-27', 'L', 'Schröder SPD'), ('2005-11-22', 'R', 'Merkel CDU'), ('2021-12-08', 'L', 'Scholz SPD'), ('2025-05-06', 'R', 'Merz CDU')],
    'jpn': [('1996-01-11', 'R', '自民党'), ('2009-09-16', 'L', '鳩山/菅/野田 民主党'), ('2012-12-26', 'R', '自民党')],
}


def ym(s):
    return int(s[:4]) * 100 + int(s[5:7])


def party_series(first=192607, last=202612):
    """信号の月 t（その月末に分かる）→ 党。三つの暦:
       main     : 就任の翌月末から（就任月 ≤ t−1）→ 持つのは就任月＋2 から
       bgl      : 就任月の月末から（就任月 ≤ t）→ 持つのは就任月＋1 から（BGL の『月初の大統領』）
       election : 党が替わった選挙の結果が分かった月の翌月末から（結果の月 ≤ t−1）"""
    def add(m, k):
        yy, mm = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
        return yy * 100 + mm + 1
    months = []
    m = first
    while m <= last:
        months.append(m); m = add(m, 1)
    pres = [(ym(d), p) for _, p, d in PRESIDENTS]
    out = {'main': {}, 'bgl': {}, 'election': {}}
    for t in months:
        out['main'][t] = [p for s, p in pres if s <= add(t, -1)][-1]
        out['bgl'][t] = [p for s, p in pres if s <= t][-1]
        el = [p for d, p in SWITCH_ELECTIONS if ym(d) <= add(t, -1)]
        out['election'][t] = el[-1] if el else 'R'   # 1926-07 時点の大統領は共和（Coolidge）
    sen = {}
    for t in months:
        if t >= 195301:
            end = f'{t // 100:04d}-{t % 100:02d}-31'
            sen[t] = [p for d, p in SENATE if d <= end][-1]
    out['senate_at_signal_month_end'] = sen
    return out


def build():
    L.fetch_all()
    M = L.Mapper()
    NC = L.NaicsChain()
    tables, diag = {}, {}
    for y in TABLES:
        t, d = build_table(y, M, NC)
        tables[y] = t
        diag[y] = d
    def rnd(o):
        if isinstance(o, dict):
            return {k: rnd(v) for k, v in o.items()}
        return round(o, 8) if isinstance(o, float) else o
    tables = rnd(tables)
    ps = party_series()
    cal = {'presidents': PRESIDENTS, 'switch_elections': SWITCH_ELECTIONS, 'senate': SENATE, 'intl_heads_report_only': INTL_HEADS,
           'party_by_signal_month': {k: {str(m): p for m, p in v.items()} for k, v in ps.items()}}
    out = {'generated': datetime.date.today().isoformat(),
           'what': 'BEA ベンチマーク産業連関表 → 業種の政府への依存度（BGL の直接＋間接〔レオンチェフ〕・変形つき）を French 49 と GICS 11 へ。政治の暦。業種・市場のリターンは読んでいない',
           'industries': L.FR49, 'fr2gics': L.FR2GICS, 'gics11': L.GICS11,
           'schedule': SCHEDULE, 'not_scheduled': NOT_SCHEDULED, 'fd_doc': FD_DOC, 'govind': GOVIND, 'iva': IVA,
           'tables': tables, 'diagnostics': diag, 'calendar': cal}
    out['sha256_tables'] = hashlib.sha256(json.dumps(tables, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    out['sha256_calendar'] = hashlib.sha256(json.dumps(cal, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    tmp = OUT + '.tmp'
    open(tmp, 'w').write(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=0))
    os.replace(tmp, OUT)
    return out


def show(o):
    for y, d in o['diagnostics'].items():
        v = d['by_variant']['all']
        print(f"{y} {d['era']:5s} 系 {d['n_system']} 恒等式 {d['identity_check']} 政府の最終需要 {v['gov_final_demand_total']} "
              f"1超で切った {v['clipped_above_1']}（最大 {v['max_raw']}） 詳細の分布 {d['detail_distribution_all']} "
              f"依存度の無い French {d['mapping']['french_without_exposure']} 一般政府の産業 {d['gov_industries_in_system']}")


if __name__ == '__main__':
    o = build()
    print('書いた:', OUT, 'sha256(tables)=', o['sha256_tables'], 'sha256(calendar)=', o['sha256_calendar'])
    if '--show' in sys.argv:
        show(o)
