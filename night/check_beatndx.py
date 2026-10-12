#!/usr/bin/env python3
"""night/check_beatndx.py — night/beatndx.py の部品を、作った数字で確かめる（ネット不要・1秒）

倍率の式・債券の値・テックの合成の重み・年齢の倍率・勢いの信号に先読みが無いこと・回す規則・
持ち方を変えた量の数え方・積立の倍率と年率・判定と提案の選び方・事前登録との一致。
"""
import json, math, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import beatndx as B  # noqa: E402

N = {'ok': 0, 'ng': 0}


def ok(cond, msg):
    if cond:
        N['ok'] += 1
    else:
        N['ng'] += 1
        print('✗', msg)


def close(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol


# ── 倍率（毎日戻す・借入の費用・現金の利息）
f = 0.0002
ok(close(B.lev_day(0.01, 1.0, f), 0.01), 'L=1 は値動きそのもの')
ok(close(B.lev_day(0.01, 0.0, f), f), 'L=0 は短期金利だけ')
ok(close(B.lev_day(0.01, 1.5, f), 1.5 * 0.01 - 0.5 * (f + 0.015 / 252)), 'L=1.5 は0.5倍分に 短期金利＋1.5%/252 を払う')
ok(close(B.lev_day(0.01, 0.5, f), 0.5 * 0.01 + 0.5 * f), 'L=0.5 は半分が短期金利を受け取る（上乗せは払わない）')
ok(close(B.lev_day(-0.02, 2.0, f), 2 * -0.02 - 1.0 * (f + 0.015 / 252)), 'L=2 の下げ')
ser = {1: 0.01, 2: -0.02, 3: 0.03}
g = (1 + B.lev_day(0.01, 1.5, f)) * (1 + B.lev_day(-0.02, 1.5, f)) * (1 + B.lev_day(0.03, 1.5, f)) - 1
ok(close(B.lev_month(ser, [1, 2, 3], 1.5, lambda d: f), g), 'lev_month は日ごとに戻した倍率の積')
ok(close(B.compound(ser, [1, 2, 3]), 1.01 * 0.98 * 1.03 - 1), 'compound')

# ── 10年債
ok(close(B.bond_price(0.04, 0.04), 1.0, 1e-12), '利札＝利回りなら額面')
ok(B.bond_price(0.04, 0.03) > 1 and B.bond_price(0.04, 0.05) < 1, '利回りが下がれば値上がり・上がれば値下がり')
dur = -(B.bond_price(0.04, 0.0401) - 1) / 0.0001
ok(7.8 < dur < 8.4, f'10年・4%の修正デュレーションは約8.1（{dur:.2f}）')
ok(close(B.bond_price(0.0, 0.0), 1.0), '利回り0（ゼロ除算しない）')
yld = {19700101: 0.05, 19700102: 0.05, 19700105: 0.04}
bd = B.bond_daily(yld, [19700101, 19700102, 19700103, 19700105])
ok(19700101 not in bd, '最初の日はリターンを作らない（前日が無い）')
ok(close(bd[19700102], 0.05 / 252), '利回りが動かない日は利息だけ')
ok(close(bd[19700103], 0.05 / 252), '欠けた日は利回りが前日のまま（利息だけ）')
ok(close(bd[19700105], B.bond_price(0.05, 0.04) - 1 + 0.05 / 252), '利回りが下がった日は値上がり＋前日の利回りの利息')

# ── テックの合成（前月末の時価で加重・月の中は値動きで重みが動く）
ind = {'Hardw': {19650701: 0.1, 19650702: 0.0}, 'Softw': {19650701: 0.0, 19650702: 0.1}, 'Chips': {}}
w = {'Hardw': {196507: 1.0}, 'Softw': {196507: 3.0}, 'Chips': {}}
td = B.tech_daily(ind, w, {196507: [19650701, 19650702]})
ok(close(td[19650701], 0.025), '1日目＝重み1:3の加重平均')
ok(close(td[19650702], 0.3 / 4.1), '2日目＝値動きで動いた重み（1.1:3）で加重')
ok(close((1 + td[19650701]) * (1 + td[19650702]) - 1, (1 * 1.1 + 3 * 1.1) / 4 - 1), '月の積＝月初の時価で買って持った値動き')
ind2 = {'Hardw': {19650701: 0.1}, 'Softw': {}, 'Chips': {19650701: -0.1}}
td2 = B.tech_daily(ind2, {'Hardw': {196507: 1.0}, 'Softw': {196507: 5.0}, 'Chips': {196507: 1.0}}, {196507: [19650701]})
ok(close(td2[19650701], 0.0), 'その日に値が無い業種は外して残りで加重（0と読まない）')

# ── 年齢の倍率（Lifecycle）
ok(B.life_L(0, 240) == 2 and B.life_L(59, 240) == 2, 'はじめの5年は2倍')
ok(close(B.life_L(60, 240), 2.0) and close(B.life_L(120, 240), 1.5) and close(B.life_L(179, 240), 1 + 1 / 120), '5〜15年でまっすぐ下げる')
ok(B.life_L(180, 240) == 1 and B.life_L(239, 240) == 1, '15年目からは1倍')
ok(B.life_L(29, 120) == 2 and close(B.life_L(60, 120), 1.5) and B.life_L(90, 120) == 1, '10年の窓は 25%・75% で縮める')

# ── 勢いの信号（先読みなし）
lv = {B.add_months(196001, i): 1.0 + 0.01 * i for i in range(30)}
m = B.add_months(196001, 20)
ok(B.tr_signal(lv, m) is True, '上げ続けなら前の月末は平均より上')
lv2 = dict(lv); lv2[m] = 0.01
ok(B.tr_signal(lv2, m) is True, 'その月の自分の月末は使わない（先読みなし）')
ok(B.tr_signal(lv2, B.add_months(m, 1)) is False, '翌月の信号には効く')
ok(B.tr_signal(lv, B.add_months(196001, 5)) is None, '10か月そろわなければ None')
flat = {B.add_months(196001, i): 1.0 for i in range(30)}
ok(B.tr_signal(flat, m) is False, '平均と同じなら「上」ではない')

# ── ぶれで倍率
ok(B.vt_L([0.0, 0.0]) == 1.5, 'ぶれが0なら上限')
lowv = [0.001, -0.001] * 10
ok(B.vt_L(lowv) == 1.5, 'ぶれが小さければ上限1.5倍')
hiv = [0.05, -0.05] * 10
ok(B.vt_L(hiv) == 0.5, 'ぶれが大きければ下限0.5倍')
mid = [0.0126, -0.0126] * 10
sd = __import__('statistics').stdev(mid) * math.sqrt(252)
ok(close(B.vt_L(mid), 0.20 / sd), '間なら 年20%÷前月のぶれ')
ok(B.vt_L([0.01]) is None, '1日だけではぶれを測れない')

# ── 回す（dual momentum）
ok(B.dm_pick({'ndx': 0.2, 'semi': 0.3, 'mkt': 0.1}, 0.05) == 'semi', 'いちばん高いもの')
ok(B.dm_pick({'ndx': 0.2, 'semi': 0.2, 'mkt': 0.1}, 0.05) == 'ndx', '同点は並びの順')
ok(B.dm_pick({'ndx': 0.02, 'semi': 0.01, 'mkt': 0.0}, 0.05) is None, '短期金利より低ければ現金')

# ── 混ぜる（毎月戻す）
ok(close(B.drift_w(0.7, 0.0, 0.0), 0.7), '動かなければ重みはそのまま')
ok(close(B.drift_w(0.5, 0.2, 0.0), 0.6 / 1.1), '片方が上がれば重みが増える')

# ── 積立
months = [196001, 196002, 196003]
ok(close(B.dca_final({mm: 0.0 for mm in months}, {}, months), 3.0), '動かなければ入れた額')
ok(close(B.dca_final({mm: 0.0 for mm in months}, {196002: 0.5}, months), 2.5), '費用は今ある元手にだけ（新しく入れる分には掛けない）')
ok(close(B.dca_final({196001: 0.1, 196002: 0.0, 196003: 0.0}, {196001: 0.5}, months), 3.1), '最初の月は元手が0なので費用なし')
ok(close(B.irr_from_final(240.0, 240), 0.0, 1e-9), '入れた額のままなら年率0')
V = sum(1.01 ** k for k in range(1, 241))
ok(close(B.irr_from_final(V, 240), 1.01 ** 12 - 1, 1e-9), '月1%なら年率 1.01^12−1')
ls = B.lump_series({196001: 0.1, 196002: 0.0}, {196001: 0.5, 196002: 0.01}, [196001, 196002])
ok(close(ls[196001], 0.1) and close(ls[196002], -0.01), '一括: 最初の月は費用なし・以後は元手から引く')


# ── 作り方（作った一つの時代で）
def fake_era(seed=1):
    import random
    rnd = random.Random(seed)
    nd, se, mk = {}, {}, {}
    for mm in B.month_range(196001, 197012):
        y, mo = divmod(mm, 100)
        for day in range(1, 21):
            d = y * 10000 + mo * 100 + day
            nd[d] = rnd.gauss(0.0006, 0.012)
            se[d] = rnd.gauss(0.0008, 0.018)
            mk[d] = rnd.gauss(0.0004, 0.009)
    e = {'ndx': nd, 'semi': se, 'mkt': mk, 'rf': lambda d: 0.0001, 'bond': {d: 0.0002 for d in nd}}
    e['dbm'] = {k: B.by_month(e[k]) for k in ('ndx', 'semi', 'mkt')}
    e['mon'] = {k: {mm: B.compound(e[k], ds) for mm, ds in e['dbm'][k].items()} for k in ('ndx', 'semi', 'mkt')}
    e['rfm'] = {mm: (1.0001 ** len(ds)) - 1 for mm, ds in e['dbm']['ndx'].items()}
    lvl, gg = {}, 1.0
    for mm in sorted(e['mon']['ndx']):
        gg *= 1 + e['mon']['ndx'][mm]
        lvl[mm] = gg
    e['level'] = lvl
    return e


e = fake_era()
ms = B.month_range(196201, 196912)
r0, c0, _, _ = B.strat(e, 'B0', ms)
ok(all(close(r0[mm], e['mon']['ndx'][mm]) for mm in ms) and not c0, 'B0＝NASDAQ100 の月次・費用なし')
r1, _, _, _ = B.strat(e, 'L150', ms)
ok(all(close(r1[mm], B.lev_month(e['ndx'], e['dbm']['ndx'][mm], 1.5, e['rf'])) for mm in ms), 'L150')
rt, ct, swt, trt = B.strat(e, 'TR150', ms)
for mm in ms:
    s = B.tr_signal(e['level'], mm)
    if not close(rt[mm], B.lev_month(e['ndx'], e['dbm']['ndx'][mm], 1.5 if s else 1.0, e['rf'])):
        ok(False, f'TR150 の倍率が信号と合わない {mm}')
        break
else:
    ok(True, 'TR150 は前の月末の信号どおりの倍率')
ok(all(close(ct[mm], 0.001 * trt[mm]) and trt[mm] in (0.0, 0.5) for mm in ms), 'TR150 の費用＝0.1%×0.5（変えた月だけ）')
ok(sum(swt.values()) == sum(1 for mm in ms if trt[mm] > 0), '変えた回数')
# 先読みなし: ある月の日々のリターンを変えても、その月の倍率は変わらない
e2 = fake_era()
mm = ms[30]
for d in e2['dbm']['ndx'][mm]:
    e2['ndx'][d] = -0.05
e2['mon']['ndx'][mm] = B.compound(e2['ndx'], e2['dbm']['ndx'][mm])
gg = 1.0
for k in sorted(e2['mon']['ndx']):
    gg *= 1 + e2['mon']['ndx'][k]
    e2['level'][k] = gg
rt2, _, _, trt2 = B.strat(e2, 'TR150', ms)
L_orig = 1.5 if B.tr_signal(e['level'], mm) else 1.0
ok(close(rt2[mm], B.lev_month(e2['ndx'], e2['dbm']['ndx'][mm], L_orig, e2['rf'])), 'TR150: その月の値を変えてもその月の倍率は同じ（先読みなし）')
rv, cv, _, trv = B.strat(e, 'VT', ms)
Lv = B.vt_L([e['ndx'][d] for d in e['dbm']['ndx'][B.add_months(ms[5], -1)]])
ok(close(rv[ms[5]], B.lev_month(e['ndx'], e['dbm']['ndx'][ms[5]], Lv, e['rf'])), 'VT は前の月の日次のぶれで倍率')
rs, cs, sws, trs = B.strat(e, 'S30', ms)
pm = B.add_months(ms[3], -1)
ok(close(rs[ms[3]], 0.7 * e['mon']['ndx'][ms[3]] + 0.3 * e['mon']['semi'][ms[3]]), 'S30 の月次＝70:30 の加重')
ok(close(trs[ms[3]], 2 * abs(0.7 - B.drift_w(0.7, e['mon']['ndx'][pm], e['mon']['semi'][pm]))) and not any(sws.values()), 'S30 の費用＝戻した量（目標は変えない）')
rd, cd, swd, trd = B.strat(e, 'DM', ms)
okdm = True
prev = None
for i, mm in enumerate([B.add_months(ms[0], -1)] + ms):
    win = [B.add_months(mm, -j) for j in range(12, 0, -1)]
    r12 = {a: math.prod(1 + e['mon'][a][x] for x in win) - 1 for a in ('ndx', 'semi', 'mkt')}
    rf12 = math.prod(1 + e['rfm'][x] for x in win) - 1
    p = B.dm_pick(r12, rf12)
    if i:
        want = e['rfm'][mm] if p is None else e['mon'][p][mm]
        t = 0.0 if p == prev else (1.0 if (p is None or prev is None) else 2.0)
        okdm = okdm and close(rd[mm], want) and close(trd[mm], t)
    prev = p
ok(okdm, 'DM: 前の12か月の勝者を持つ・入れ替えは2・現金との出入りは1')
rc, cc, _, trc = B.strat(e, 'C1', ms)
ra, ca, _, _ = B.strat(e, 'TR150', ms)
rb, cb, _, _ = B.strat(e, 'S30', ms)
mm = ms[7]
ok(close(rc[mm], 0.5 * ra[mm] + 0.5 * rb[mm]), 'C1 の月次＝半分ずつ')
ok(close(cc[mm], 0.5 * ca[mm] + 0.5 * cb[mm] + 0.001 * trc[mm]), 'C1 の費用＝袖の中の費用の半分ずつ＋袖の間の戻し')
rr, _, _, _ = B.strat(e, 'RP150', ms)
comp = {d: 0.6 * e['ndx'][d] + 0.4 * 0.0002 for d in e['ndx']}
ok(close(rr[ms[2]], B.lev_month(comp, e['dbm']['ndx'][ms[2]], 1.5, e['rf'])), 'RP150＝60:40 を毎日1.5倍')
mo_, rl, cl = B.life_window(e, ms[0], 24, {})
ok(close(rl[ms[0]], B.lev_month(e['ndx'], e['dbm']['ndx'][ms[0]], 2.0, e['rf'])) and ms[0] not in cl, 'LIFE の最初の月は2倍・費用なし')
ok(close(cl[ms[7]], 0.001 * abs(B.life_L(7, 24) - B.life_L(6, 24))), 'LIFE の費用＝倍率を下げた量×0.1%')


# ── 判定と提案の選び方
def fake_res(spec):
    res = {}
    for era in 'AB':
        mth = {}
        for k in B.METHODS:
            if k == 'B0':
                continue
            med, win, worst, lump = spec.get(k, {}).get(era, (1.0, 0.5, 0.7, False))
            crit = {'median': med >= 1.05, 'win_rate': win >= 0.6, 'worst': worst >= 0.8}
            if k != 'LIFE':
                crit['lump'] = lump
            mth[k] = {'dca20': {'median': med, 'win_rate': win, 'worst': [0, worst]}, 'criteria': crit, 'passed': all(crit.values())}
        res[era] = {'methods': mth}
    return res


V, sel = B.verdicts(fake_res({'L150': {'A': (1.2, 0.8, 0.85, True), 'B': (1.3, 0.9, 0.9, True)},
                              'TR150': {'A': (1.1, 0.7, 0.855, True), 'B': (1.4, 0.9, 0.95, True)},
                              'S30': {'B': (1.5, 1.0, 1.1, True)}}))
ok(V['L150']['verdict'].startswith('NASDAQ100 を超えた') and V['S30']['verdict'] == '片方の時代だけ（B）' and V['VT']['verdict'] == '超えなかった', '判定の三つの言葉')
ok(sel['pick'] == 'L150', '最悪の比の小さいほうが0.01以内で並ぶなら、中央の比の小さいほうが大きいもの（TR150 0.855 と L150 0.85 → 中央 1.2 の L150）')
V, sel = B.verdicts(fake_res({'L150': {'A': (1.2, 0.8, 0.85, True), 'B': (1.3, 0.9, 0.9, True)},
                              'TR150': {'A': (1.1, 0.7, 0.90, True), 'B': (1.4, 0.9, 0.95, True)}}))
ok(sel['pick'] == 'TR150', '最悪の比の小さいほうが大きいもの（0.01より離れていれば中央の比は見ない）')
V, sel = B.verdicts(fake_res({'S30': {'B': (1.5, 1.0, 1.1, True)}, 'MK130': {'A': (1.1, 0.7, 0.9, True), 'B': (1.06, 0.7, 0.85, False)}}))
ok(sel['candidates'] == [] and sel['pick'] == 'MK130', '一つも無ければ、満たさない条件が最も少ないもの')

# ── 事前登録との一致
pre = json.load(open(B.PRE, encoding='utf-8'))
ok(list(pre['methods']) == B.METHODS, '作り方の13本が事前登録と同じ順・同じ名前')
pb = pre['criteria']['pass_both']
ok('1.05' in pb and '60%' in pb and '0.80' in pb and B.LINES == {'median': 1.05, 'win_rate': 0.60, 'worst': 0.80}, '線が事前登録と同じ')
ok('1.5%' in pre['costs']['borrowing'] and B.SPREAD == 0.015 and '0.1%' in pre['costs']['trading'] and B.TRADE == 0.001, '費用が事前登録と同じ')
ok('1965-07〜1980-01' in pre['metrics']['dca20'] and '2000-01〜2006-10' in pre['metrics']['dca20'] and B.DCA20 == {'A': (196507, 198001), 'B': (200001, 200610)}, '20年積立の起点が事前登録と同じ')

print(f"check_beatndx: {N['ok']} 件 OK・{N['ng']} 件 NG")
sys.exit(1 if N['ng'] else 0)
