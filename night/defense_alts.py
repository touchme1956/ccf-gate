#!/usr/bin/env python3
"""night/defense_alts.py — 防衛の ETF・投資信託で ITA より良いものはあるか（2026-10-10新設・読むだけ）

ユーザーの問い「もっといい防衛のETFや投資信託はないの？」。
事前登録 out/defense_alts_prereg.json（eb3f176・測る前にコミット）どおりに測り、判定の決まりを当てる。
判定は門の外（DCA 側）。門Ωの採点・四関門・売却規律・配分には触れない。

データ（混ぜない・欠測を埋めない＝ルール7）:
  ETF の月次 … Yahoo の調整後終値（配当込み）を mw_common.yahoo で（取引所の現地時刻で月を切る・今月の途中は落とす）
  為替 ……… FRED DEXJPUS の月末（gaps_common.fred）。Yahoo の為替月足は夏時間で月がずれるので使わない
  投資信託 … 投資信託協会の基準価額（分配金は再投資）を fetch_returns.fund_series で
  業種 ……… Ken French 49業種（industry_long）・テックの合成と米国市場（gaps_common）
  中身 ……… Alpha Vantage ETF_PROFILE（2026-10-08 時点・下の定数）・513A はファクトシート（2026-09-30）

実行: python3 night/defense_alts.py   → out/defense_alts.json
"""
import datetime, json, math, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as MC          # noqa: E402
import gaps_common as GC        # noqa: E402
from industry_long import lines, block   # noqa: E402

OUT = os.path.join(BASE, 'out', 'defense_alts.json')
PREREG = os.path.join(BASE, 'out', 'defense_alts_prereg.json')
END = 202609            # 最後の丸1か月（ETF）＝事前登録 eb3f176 の測定の基準時点（記録として固定）
# 基準時点＝END の月末。記録の年数（判定の条件(2)）はここまでで数える——2026-10-10 の判定を再現できるよう固定する
# （回し直すときは END とこの日付を一緒に新しい月末へ。再検定は todo defense_alts_retest_2033）
CUTOFF = datetime.date(2026, 9, 30)
SLOT = {'QQQ': 50, 'SMH': 20, 'X': 15}   # その他15% の形（個別株15%は物差しの外・85で割る）

# ───────── 候補の事実（出所と日付は out/defense_alts_prereg.json と回答の Sources） ─────────
FACTS = {
    'ITA': dict(名='iShares 米国航空宇宙・防衛', 種類='米国上場ETF', 楽天=True, 費用=0.37, 設定='2006-05-01',
                NISA='要確認（米国上場・楽天のアプリで。todo ita_nisa_check）'),
    'SHLD': dict(名='Global X 防衛テック', 種類='米国上場ETF', 楽天=True, 費用=0.50, 設定='2023-09-11',
                 NISA='要確認（米国上場・楽天のアプリで）'),
    'MISL': dict(名='First Trust Indxx 米国航空宇宙・防衛', 種類='米国上場ETF', 楽天=True, 費用=0.60, 設定='2022-10-25',
                 NISA='要確認（米国上場・楽天のアプリで）'),
    '466A': dict(名='グローバルX 防衛テック ETF（SHLD を円で持つ）', 種類='東証ETF', 楽天=True, 費用=0.5275,
                 設定='2025-11-21', NISA='運用会社のページに成長投資枠対象と明記（楽天での表示は未確認）'),
    '513A': dict(名='グローバルX 防衛テック-日本株式 ETF', 種類='東証ETF', 楽天=True, 費用=0.649, 設定='2026-02-24',
                 NISA='対象（楽天の成長投資枠の保有ランキングに載る）'),
    'たわら防衛': dict(名='たわらノーロード フォーカス 防衛・航空宇宙', 種類='投資信託', 楽天=True, 費用=0.77,
                   設定='2025-11-28', NISA='運用会社は成長投資枠対応・楽天のページは表示が食い違う'),
    '欧州防衛': dict(名='欧州防衛・航空宇宙株式インデックスファンド', 種類='投資信託', 楽天=True, 費用=0.77,
                 設定='2025-11-18', 償還='2030-11-15', NISA='償還まで20年未満＝成長投資枠の対象外'),
    'PPA': dict(名='Invesco 航空宇宙・防衛', 種類='米国上場ETF', 楽天=False, 費用=0.58, 設定='2005-10-26',
                NISA='楽天で買えない'),
    'XAR': dict(名='SPDR S&P 航空宇宙・防衛（等ウェイト）', 種類='米国上場ETF', 楽天=False, 費用=0.35, 設定='2011-09-28',
                NISA='楽天で買えない'),
}

# ───────── 中身（Alpha Vantage ETF_PROFILE・2026-10-08 時点） ─────────
#   区分は主な事業で分けた目安: 防衛 / 防衛テック / 両方（民間航空と防衛） / 民間（航空機の部品・整備） / 宇宙・新 / 素材 / 治安
ITA_H = [("GE", 20.73, "民間"), ("RTX", 16.11, "両方"), ("BA", 7.70, "両方"), ("LMT", 4.57, "防衛"),
         ("TDG", 4.53, "両方"), ("NOC", 4.53, "防衛"), ("GD", 4.46, "防衛"), ("HWM", 4.44, "民間"),
         ("HONA", 3.99, "両方"), ("LHX", 3.36, "防衛"), ("RKLB", 2.98, "宇宙・新"), ("AXON", 2.80, "治安"),
         ("ATI", 1.91, "素材"), ("CW", 1.53, "防衛"), ("CRS", 1.49, "素材"), ("FTAI", 1.46, "民間"),
         ("WWD", 1.45, "民間"), ("HEI-A", 1.30, "両方"), ("TXT", 1.01, "両方"), ("BWXT", 1.00, "防衛"),
         ("HEI", 0.95, "両方"), ("HII", 0.80, "防衛"), ("MOG-A", 0.79, "両方"), ("KTOS", 0.66, "防衛"),
         ("HXL", 0.49, "素材"), ("AVAV", 0.44, "防衛"), ("VSEC", 0.39, "民間"), ("SARO", 0.38, "民間"),
         ("MRCY", 0.35, "防衛"), ("AIR", 0.35, "民間"), ("KRMN", 0.31, "防衛"), ("ACHR", 0.28, "宇宙・新"),
         ("DRS", 0.22, "防衛"), ("RDW", 0.22, "宇宙・新"), ("BETA", 0.21, "宇宙・新"), ("ARXS", 0.19, "両方"),
         ("ATRO", 0.19, "民間"), ("LUNR", 0.19, "宇宙・新"), ("VVX", 0.17, "防衛"), ("LOAR", 0.17, "民間"),
         ("DCO", 0.17, "両方"), ("FLY", 0.16, "宇宙・新"), ("VOYG", 0.16, "宇宙・新"), ("YSS", 0.07, "宇宙・新"),
         ("RCAT", 0.07, "防衛"), ("NPK", 0.06, "防衛"), ("CDRE", 0.06, "治安"), ("SWBI", 0.05, "治安"),
         ("RGR", 0.04, "治安"), ("SPCE", 0.04, "宇宙・新")]
# SHLD は指数の決まりで「売上の50%以上が防衛テック（サイバー・防衛テクノロジー・高度な軍事システム）」の会社だけ
SHLD_H = [("PLTR", 11.32, "米国", "防衛テック"), ("RTX", 9.04, "米国", "防衛"), ("GD", 8.38, "米国", "防衛"),
          ("LMT", 8.20, "米国", "防衛"), ("NOC", 7.69, "米国", "防衛"), ("BAE Systems", 4.68, "欧州", "防衛"),
          ("Hanwha Aerospace", 3.89, "韓国", "防衛"), ("Rheinmetall", 3.76, "欧州", "防衛"),
          ("Thales", 3.75, "欧州", "防衛"), ("LHX", 3.62, "米国", "防衛"), ("Saab", 3.57, "欧州", "防衛"),
          ("Leonardo", 3.55, "欧州", "防衛"), ("Elbit Systems", 3.15, "イスラエル", "防衛"),
          ("LDOS", 2.38, "米国", "防衛"), ("Kongsberg", 2.17, "欧州", "防衛"), ("BWXT", 2.04, "米国", "防衛"),
          ("HII", 1.64, "米国", "防衛"), ("MOG-A", 1.59, "米国", "防衛"), ("KTOS", 1.34, "米国", "防衛"),
          ("LIG D&A", 0.99, "韓国", "防衛"), ("Korea Aerospace", 0.98, "韓国", "防衛"),
          ("Babcock", 0.93, "欧州", "防衛"), ("AVAV", 0.92, "米国", "防衛"), ("Dassault Aviation", 0.88, "欧州", "防衛"),
          ("Hensoldt", 0.83, "欧州", "防衛"), ("MRCY", 0.77, "米国", "防衛"), ("PSN", 0.72, "米国", "防衛"),
          ("PL", 0.72, "米国", "防衛"), ("Aselsan", 0.66, "トルコ", "防衛"), ("Hanwha Systems", 0.65, "韓国", "防衛"),
          ("AMTM", 0.61, "米国", "防衛"), ("OSIS", 0.49, "米国", "防衛"), ("KRMN", 0.48, "米国", "防衛"),
          ("CSG", 0.41, "欧州", "防衛"), ("TKMS", 0.37, "欧州", "防衛"), ("QinetiQ", 0.37, "欧州", "防衛"),
          ("VOYG", 0.30, "米国", "防衛"), ("Chemring", 0.29, "欧州", "防衛"), ("BBAI", 0.21, "米国", "防衛テック"),
          ("Exail", 0.20, "欧州", "防衛"), ("Electro Optic Systems", 0.20, "豪州・カナダ", "防衛"),
          ("Bittium", 0.20, "欧州", "防衛"), ("DroneShield", 0.16, "豪州・カナダ", "防衛"),
          ("YSS", 0.16, "米国", "防衛"), ("Kraken Robotics", 0.15, "豪州・カナダ", "防衛"),
          ("RCAT", 0.14, "米国", "防衛"), ("Austal", 0.11, "豪州・カナダ", "防衛"), ("BKSY", 0.11, "米国", "防衛"),
          ("Aryt", 0.05, "イスラエル", "防衛")]
MISL_H = [("PLTR", 10.33, "防衛テック"), ("RTX", 8.56, "両方"), ("BA", 7.86, "両方"), ("GE", 7.67, "民間"),
          ("SPCX", 6.87, "宇宙・新"), ("LMT", 4.28, "防衛"), ("NOC", 4.00, "防衛"), ("HEI", 3.92, "両方"),
          ("GD", 3.91, "防衛"), ("HWM", 3.89, "民間"), ("RKLB", 3.70, "宇宙・新"), ("LHX", 3.68, "防衛"),
          ("TDG", 3.60, "両方"), ("ASTS", 2.80, "宇宙・新"), ("CW", 2.63, "防衛"), ("FTAI", 2.33, "民間"),
          ("WWD", 2.14, "民間"), ("LDOS", 1.79, "防衛"), ("TXT", 1.55, "両方"), ("CACI", 1.49, "防衛"),
          ("MOG-A", 1.33, "両方"), ("HII", 1.30, "防衛"), ("KTOS", 1.20, "防衛"), ("DRS", 1.20, "防衛"),
          ("AVAV", 1.00, "防衛"), ("KRMN", 0.83, "防衛"), ("HXL", 0.76, "素材"), ("LOAR", 0.69, "民間"),
          ("MRCY", 0.66, "防衛"), ("AIR", 0.58, "民間"), ("SAIC", 0.53, "防衛"), ("PSN", 0.52, "防衛"),
          ("KBR", 0.48, "防衛"), ("FLY", 0.44, "宇宙・新"), ("LUNR", 0.36, "宇宙・新"), ("ATRO", 0.32, "民間"),
          ("DCO", 0.30, "両方"), ("VOYG", 0.26, "宇宙・新"), ("NPK", 0.10, "防衛")]
# 513A ファクトシート（2026-09-30）の上位10（全15社・合計94.30%）。各社とも防衛は売上の一部（総合重機・電機）
J513_H = [("日本電気", 19.01), ("IHI", 15.99), ("三菱重工業", 15.86), ("三菱電機", 13.55), ("川崎重工業", 13.05),
          ("日本製鋼所", 5.08), ("日清紡ホールディングス", 4.07), ("スカパーJSAT", 3.03),
          ("シンフォニア テクノロジー", 2.79), ("古河電気工業", 1.87)]


# ───────── 計算の部品 ─────────
def mrange(a, b):
    out, m = [], a
    while m <= b:
        out.append(m)
        y, mo = divmod(m, 100)
        m = (y + (mo == 12)) * 100 + (1 if mo == 12 else mo + 1)
    return out


def stats(rs):
    """月次リターンの並び → 年率・年率ボラ・最大下落（%）"""
    n = len(rs)
    if n < 6:
        return None
    lvl, pk, dd = 1.0, 1.0, 0.0
    for r in rs:
        lvl *= 1 + r
        pk = max(pk, lvl)
        dd = min(dd, lvl / pk - 1)
    mu = sum(rs) / n
    vol = math.sqrt(sum((r - mu) ** 2 for r in rs) / (n - 1) * 12)
    cg = lvl ** (12 / n) - 1
    return {'月数': n, '年率': round(cg * 100, 2), '年率ボラ': round(vol * 100, 2), '最大下落': round(dd * 100, 1),
            '年率÷ボラ': round(cg / vol, 3) if vol else None}


def corr(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    return round(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb), 3) if va and vb else None


def cum(r, a, b):
    """窓 a→b（月末の値どうし）の累積＝a の翌月から b までの積"""
    ms = mrange(a, b)[1:]
    if not all(m in r for m in ms):
        return None
    v = 1.0
    for m in ms:
        v *= 1 + r[m]
    return round((v - 1) * 100, 1)


def slot_series(rq, rs, rx, ms):
    tot = sum(SLOT.values())
    return [(SLOT['QQQ'] * rq[m] + SLOT['SMH'] * rs[m] + SLOT['X'] * rx[m]) / tot for m in ms]


def have(ms, *series):
    return [m for m in ms if all(m in s for s in series)]


def years_since(d):
    y, mo, da = map(int, d.split('-'))
    return round((CUTOFF - datetime.date(y, mo, da)).days / 365.25, 1)


def comp(h, key):
    out = {}
    for row in h:
        out[row[key]] = round(out.get(row[key], 0) + row[1], 2)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def eff_n(ws):
    t = sum(ws)
    return round(1 / sum((w / t) ** 2 for w in ws), 1)


# ───────── データ ─────────
def load_etfs():
    R, miss = {}, []
    for t in ('ITA', 'SHLD', 'MISL', 'PPA', 'XAR', 'QQQ', 'SMH', 'SPY', '466A.T', '513A.T'):
        try:
            r = MC.yahoo(t, '1mo')
            R[t] = {k: v for k, v in r.items() if k <= END}
        except Exception as e:   # 取れなければ測れない（埋めない）
            miss.append(f'{t}: {type(e).__name__}')
    return R, miss


def load_fund():
    """たわら防衛の月末の基準価額（分配金再投資）→ 月次リターン。取れなければ None"""
    try:
        import fetch_returns as FR
        s = FR.fund_series({'isin': 'JP90C000SAB4', 'associFundCd': '4731925B', 'navPer': 10000})
    except Exception:
        s = None
    if not s:
        return None
    last = {}
    for d, (_, tr) in sorted(s.items()):
        last[int(d[:4]) * 100 + int(d[5:7])] = tr
    ks = sorted(k for k in last if k <= END)
    return {k: last[k] / last[p] - 1 for p, k in zip(ks, ks[1:])}


def to_jpy(r, fx):
    out = {}
    for m, v in r.items():
        y, mo = divmod(m, 100)
        p = (y - (mo == 1)) * 100 + (12 if mo == 1 else mo - 1)
        if m in fx and p in fx:
            out[m] = (1 + v) * fx[m] / fx[p] - 1
    return out


# ───────── 本体 ─────────
def section_a(R):
    out = {}
    for label, a, names in (('SHLD の最初の丸1か月から', 202310, ('ITA', 'SHLD', 'MISL')),
                            ('MISL の最初の丸1か月から', 202211, ('ITA', 'MISL'))):
        ms = have(mrange(a, END), R['QQQ'], R['SMH'], *[R[t] for t in names])
        blk = {'窓': f'{ms[0]}〜{ms[-1]}（{len(ms)}か月・ドル建て）', '単体': {}, 'その他15%の形（QQQ50:SMH20:X15）': {}}
        for t in names:
            x = [R[t][m] for m in ms]
            s = stats(x)
            s['QQQとの相関'] = corr(x, [R['QQQ'][m] for m in ms])
            s['SMHとの相関'] = corr(x, [R['SMH'][m] for m in ms])
            blk['単体'][t] = s
            blk['その他15%の形（QQQ50:SMH20:X15）'][t] = stats(slot_series(R['QQQ'], R['SMH'], R[t], ms))
        blk['単体']['QQQ'] = stats([R['QQQ'][m] for m in ms])
        out[label] = blk
    return out


def section_a_jpy(R, fund, fx):
    out = {'注': '記録が1年に満たない＝値だけ（判定に使わない）。ITA・SHLD は FRED DEXJPUS の月末で円に直した'}
    ita_j, shld_j = to_jpy(R['ITA'], fx), to_jpy(R['SHLD'], fx)
    for label, ser, a in (('466A', R.get('466A.T'), 202512), ('たわら防衛', fund, 202512), ('513A', R.get('513A.T'), 202603)):
        if not ser:
            out[label] = '取れなかった（測れない）'
            continue
        ms = have(mrange(a, END), ser, ita_j, shld_j)
        if len(ms) < 3:
            out[label] = f'共通の月が {len(ms)} か月しかない（測れない）'
            continue
        def cumm(s):
            v = 1.0
            for m in ms:
                v *= 1 + s[m]
            return round((v - 1) * 100, 1)
        def mdd(s):
            lvl = pk = 1.0
            dd = 0.0
            for m in ms:
                lvl *= 1 + s[m]
                pk = max(pk, lvl)
                dd = min(dd, lvl / pk - 1)
            return round(dd * 100, 1)
        out[label] = {'窓': f'{ms[0]}〜{ms[-1]}（{len(ms)}か月・円建て）',
                      '累積': {label: cumm(ser), 'ITA（円）': cumm(ita_j), 'SHLD（円）': cumm(shld_j)},
                      '最大下落': {label: mdd(ser), 'ITA（円）': mdd(ita_j), 'SHLD（円）': mdd(shld_j)}}
    return out


CRISES_B = {'GFC 2007-10→2009-02': (200710, 200902), '国防予算の削減 2011-04→2011-10': (201104, 201110),
            'COVID 2020-01→2020-03': (202001, 202003), '2022 2021-12→2022-09': (202112, 202209)}


def section_b(R):
    out = {}
    for t, a in (('PPA', 200511), ('XAR', 201110)):
        ms = have(mrange(a, END), R['QQQ'], R['SMH'], R['ITA'], R[t])
        blk = {'窓': f'{ms[0]}〜{ms[-1]}（{len(ms)}か月・ドル建て）', '単体': {}, 'その他15%の形（QQQ50:SMH20:X15）': {},
               '危機の窓（累積%）': {}}
        for x in ('ITA', t):
            s = stats([R[x][m] for m in ms])
            s['QQQとの相関'] = corr([R[x][m] for m in ms], [R['QQQ'][m] for m in ms])
            s['SMHとの相関'] = corr([R[x][m] for m in ms], [R['SMH'][m] for m in ms])
            blk['単体'][x] = s
            blk['その他15%の形（QQQ50:SMH20:X15）'][x] = stats(slot_series(R['QQQ'], R['SMH'], R[x], ms))
        for nm, (c0, c1) in CRISES_B.items():
            if c0 >= ms[0] - 1:
                blk['危機の窓（累積%）'][nm] = {x: cum(R[x], c0, c1) for x in ('ITA', t, 'QQQ', 'SMH')}
        out[f'ITA と {t}'] = blk
    return out


CRISES_C = {'1973-01→1974-09': (197301, 197409), 'ITバブル崩壊 2000-03→2002-09': (200003, 200209),
            'COVID 2020-01→2020-03': (202001, 202003), '2022 2021-12→2022-09': (202112, 202209)}


def section_c():
    L = lines('49_Industry_Portfolios')
    ret = block(L, 'Average Value Weighted Returns -- Monthly')
    ind = {k: {m: v / 100 for m, v in ret[k].items() if v is not None and v > -99} for k in ('Guns', 'Aero', 'Ships', 'Chips')}
    tech = GC.french_tech()
    mkt = GC.french_mkt()[0]
    ndx = {m: 0.65 * tech[m] + 0.35 * mkt[m] for m in tech if m in mkt}
    a = min(ind['Guns'])
    ms = have(mrange(a, max(ind['Guns'])), ind['Guns'], ind['Aero'], ind['Ships'], ind['Chips'], tech, mkt)
    out = {'窓': f'{ms[0]}〜{ms[-1]}（{len(ms)}か月・米国・時価加重・配当込み）',
           '注': 'NASDAQ100 の代わり＝テック（Hardw+Softw+Chips）65%＋米国市場35%・SMH の代わり＝Chips。Guns は今 LMT が大半・Ships は鉄道車両も含む',
           '単体': {}, 'その他15%の形（NDX代50:Chips20:X15）': {}, '危機の窓（累積%）': {}}
    series = {'Guns（ミサイル・弾薬）': ind['Guns'], 'Aero（航空機・部品）': ind['Aero'], 'Ships（造船）': ind['Ships'],
              'テック': tech, '米国市場': mkt}
    for nm, s in series.items():
        x = [s[m] for m in ms]
        st = stats(x)
        st['テックとの相関'] = corr(x, [tech[m] for m in ms])
        out['単体'][nm] = st
    for nm, s in list(series.items())[:3] + [('NASDAQ100の代わりに回す（相棒なし）', ndx)]:
        out['その他15%の形（NDX代50:Chips20:X15）'][nm] = stats(slot_series(ndx, ind['Chips'], s, ms))
    for cn, (c0, c1) in CRISES_C.items():
        out['危機の窓（累積%）'][cn] = {nm: cum(s, c0, c1) for nm, s in series.items()}
    return out


def section_d():
    sh_reg = {}
    for nm, w, reg, cls in SHLD_H:
        sh_reg[reg] = round(sh_reg.get(reg, 0) + w, 2)
    return {
        'ITA': {'区分': comp(ITA_H, 2), '上位5社': round(sum(w for _, w, _ in ITA_H[:5]), 2),
                '実効の社数': eff_n([w for _, w, _ in ITA_H]), 'Palantir': 0.0, '地域': {'米国': 100.0}},
        'SHLD': {'区分': comp([(n, w, c) for n, w, _, c in SHLD_H], 2), '地域': dict(sorted(sh_reg.items(), key=lambda kv: -kv[1])),
                 '上位5社': round(sum(w for _, w, _, _ in SHLD_H[:5]), 2), '実効の社数': eff_n([w for _, w, _, _ in SHLD_H]),
                 'Palantir': 11.32, '注': '指数の決まりで売上の50%以上が防衛テックの会社だけ（最大50社・1社8%上限で5月と11月に組み直す）'},
        'MISL': {'区分': comp(MISL_H, 2), '上位5社': round(sum(w for _, w, _ in MISL_H[:5]), 2),
                 '実効の社数': eff_n([w for _, w, _ in MISL_H]), 'Palantir': 10.33, 'SpaceX': 6.87, '地域': {'米国': 100.0}},
        '513A': {'上位10（9/30）': dict(J513_H), '社数': 15, '注': '総合重機・電機が中心で、防衛は各社の売上の一部'},
    }


def verdict(A, B):
    rows = {}
    for t, f in FACTS.items():
        yrs = years_since(f['設定'])
        r1 = f['楽天'] and not f.get('償還')
        r2 = yrs >= 10
        rows[t] = {'楽天で買える': f['楽天'], 'NISA': f['NISA'], '記録の年数': yrs,
                   '(1) 楽天・NISA（償還20年未満を外す）': '○' if r1 else '×',
                   '(2) 自分の記録10年以上': '○' if r2 else '×'}
        if t == 'ITA':
            rows[t]['結論'] = '今の本'
        elif not r1:
            rows[t]['結論'] = '外す（(1)）'
        elif not r2:
            rows[t]['結論'] = '判定できない（(2)・記録が短い）'
        else:
            rows[t]['結論'] = '(3)(4)へ'
    cands = [t for t, v in rows.items() if v['結論'] == '(3)(4)へ']
    return {'表': rows, '(3)(4)へ進んだ本': cands,
            '判定': ('ITA のまま（楽天で買える代わりの本はどれも自分の記録が10年に満たない）' if not cands
                     else '(3)(4) を確かめる')}


def main():
    R, miss = load_etfs()
    fund = load_fund()
    fx = GC.fred('DEXJPUS')
    A = section_a(R)
    out = {
        'asof': '2026-10-10',
        '事前登録': 'out/defense_alts_prereg.json（eb3f176・測る前にコミット）',
        '事前登録との違い': ['B の ITA と PPA は事前登録に「2005-11〜」と書いたが、ITA は 2006-05-01 の設定でそれより前の値が無い。'
                        '共通の窓は ITA の最初の丸1か月の 2006-06〜 になった（書き方の誤り・判定に使わない参考の部分）',
                        'C の窓の終わりは French の最新の 2026-08（ETF は 2026-09）'],
        '取れなかった': miss + ([] if fund else ['たわら防衛の基準価額']),
        '候補の事実': {t: dict(f, 記録の年数=years_since(f['設定'])) for t, f in FACTS.items()},
        '判定': None,
        'A 共通の窓（実際の値動き）': A,
        "A' 円建ての短い記録": section_a_jpy(R, fund, fx),
        'B 長い窓（楽天で買えない PPA・XAR）': section_b(R),
        'C 業種の長い歴史（French 49）': section_c(),
        'D 中身（2026-10-08・513A は 9/30）': section_d(),
    }
    out['判定'] = verdict(A, out['B 長い窓（楽天で買えない PPA・XAR）'])
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:12000])


if __name__ == '__main__':
    main()
