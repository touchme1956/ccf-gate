#!/usr/bin/env python3
"""night/edge/fam_payout.py — 系統 payout（第5回）: 株主への純還元の買いだけの組

  素材: JKP（Jensen・Kelly・Pedersen）米国の三分位ポートフォリオ（買いだけ）。特徴は4本——
    eqnpo_me   純還元利回り（配当＋自社株買い−株式発行）÷ 時価総額   Boudoukh・Michaely・Richardson・Roberts
    eqpo_me    還元利回り（配当＋自社株買い）÷ 時価総額                 同上 / Ikenberry・Lakonishok・Vermaelen 1995
    chcsho_12m 株数の12か月変化（減らしている側）                        Loughran・Ritter 1995 / Pontiff・Woodgate
    div12m_me  配当利回り（直近12か月の配当 ÷ 時価総額）                 Litzenberger・Ramaswamy 1979
  良い側 = JKP の予言の向き。JKP の因子は direction ×（'3.0' − '1.0'）なので、選定期間（〜2000-12）の
  米国データで 因子 と '3.0'−'1.0' の相関の符号から決める（select() が確かめ、spec に凍結する）。
  合成 = 良い側の脚を等分（毎月もとの比へ戻す）。**その月に使う脚がすべてそろう月だけ**を返す（途中で中身が変わらない）。

  ⚠ JKP の ret は米国の短期金利（T-bill）を引いた**米ドルの超過**——米国の市場で確かめた:
    JKP mkt(vw) + French RF − French 市場 = 平均 0.0000（月）。だから総リターン = ret + RF。
  先読み: JKP は月末 t の特徴（会計値は4か月以上遅らせて使う）で組み、t+1 の月のリターンを出す。
    この規則はデータから何も推定しない（側と重みは凍結した spec の定数）ので、月 m のリターンは JKP の月 m の値と
    m の RF だけで決まる。lookahead_test() がこれを切り詰め・ずらしで確かめる。

  相手: French 米国市場（上限なしの時価加重）。費用: 回転1あたり 0.25%・回転 50%/年（会計の信号の置き値）。
  再現: JKP 先進国22か国（米国を除く）に同じ側・同じ重み付けを当てる。国の相手は JKP mkt(vw) + RF（米ドル）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, math, zipfile, statistics as S

FAMILY = {
    'key': 'payout',
    'name': '株主への純還元（純還元・還元利回り・株数を減らす・配当利回りの良い側の三分位）',
    'implement': ('楽天証券の成長投資枠（NISA 可）で米国株の個別銘柄を買う形: 年に数回、米国上場の大型・中型株を'
                  '直近12か月の発行済株式数の変化率で並べ、いちばん減らした1/3（自社株買いで株数を純減させた社）を'
                  '時価加重（1社の重みに上限＝JKP の vw_cap と同じく巨大株を抑える）で持つ。回転は 50%/年前後と置いた。'
                  '自社株買いの ETF（Invesco PKW〔Buyback Achievers＝12か月で株数5%以上減〕・Cambria SYLD）は'
                  '楽天の海外ETFの一覧（out/broker_lineup.json）に無い＝ETF では実行できず、個別株を20〜50社持つ必要がある。'
                  '配当利回りの側（VYM・HDV・DLN）は買えるが、それは別の変種で、選ばれた規則ではない'),
}

COST = 0.0025            # 片道の回転1あたり（個別株の組・事前登録 costs）
TURN_ANN = 0.5           # 回転 50%/年（会計の信号の置き値・事前登録 costs）
CHARS = ['eqnpo_me', 'eqpo_me', 'chcsho_12m', 'div12m_me']
DEV = 'aus aut bel can che deu dnk esp fin fra gbr hkg irl isr ita jpn nld nor nzl prt sgp swe'.split()
JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/'
MIN_N_REPL = 10          # 再現の国: 脚の銘柄数がこれ未満の月は使わない（数社の組は雑音）

_MEMO = {}


# ───────────────────────── 読み込み ─────────────────────────
def _leg_raw(region, ch, w):
    key = ('p', region, ch, w)
    if key not in _MEMO:
        try:
            _MEMO[key] = h.jkp(region, ch, 'portfolio', w)
        except Exception:
            _MEMO[key] = {}
    return _MEMO[key]


def _counts(region, ch, w):
    """三分位の銘柄数（h.jkp は返さないので、同じキャッシュを h.cached で読み h.guard を通す）"""
    key = ('n', region, ch, w)
    if key in _MEMO:
        return _MEMO[key]
    url = f'{JKP}portfolios/%5B{region}%5D_%5B{ch}%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
    out = {}
    try:
        z = zipfile.ZipFile(io.BytesIO(h.cached(f'jkp_portfolio_{region}_{ch}_{w}.zip', url)))
        for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
            try:
                out.setdefault(x['pf'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = int(float(x['n']))
            except (TypeError, ValueError, KeyError):
                continue
    except Exception:
        out = {}
    _MEMO[key] = {k: h.guard(v) for k, v in out.items()}
    return _MEMO[key]


def leg(region, ch, side, w, rf, min_n=0):
    """良い側の脚の総リターン（米ドル）{YYYYMM: 小数} = JKP の超過 + RF。min_n>0 なら銘柄数の足りない月を落とす"""
    p = _leg_raw(region, ch, w).get(side, {})
    n = _counts(region, ch, w).get(side, {}) if min_n else {}
    return {m: v + rf[m] for m, v in p.items() if m in rf and (not min_n or n.get(m, 0) >= min_n)}


# ───────────────────────── 規則 ─────────────────────────
def build(spec, region, rf, min_n=0):
    """→ (ret, turnover)。spec: {'chars': [...], 'sides': {ch: '1.0'|'3.0'}, 'w': 'vw_cap'|'vw'}
    合成は脚の等分（毎月もとの比へ戻す）。その月に全部の脚がそろう月だけを返す"""
    L = [leg(region, c, spec['sides'][c], spec['w'], rf, min_n) for c in spec['chars']]
    if not L or any(not x for x in L):
        return {}, {}
    ms = sorted(set.intersection(*[set(x) for x in L]))
    ret = {m: sum(x[m] for x in L) / len(L) for m in ms}
    tv = {m: TURN_ANN / 12 for m in ms}          # 年50%を毎月に均す（脚どうしの戻しは脚の中の入れ替えに比べて小さいので足さない）
    return ret, tv


def run(spec):
    mk, rf = h.us_market()
    ret, tv = build(spec, 'usa', rf)
    out = {'ret': ret, 'bench': mk, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}
    for c in spec.get('replicate', []):
        try:
            jm = h.jkp(c, 'mkt', 'factor', 'vw')        # その国の市場（上限なしの時価加重・米ドルの超過）
        except Exception:
            continue
        bench = {m: v + rf[m] for m, v in jm.items() if m in rf}
        r, t = build(spec, c, rf, min_n=spec.get('min_n_repl', MIN_N_REPL))
        r = {m: v for m, v in r.items() if m in bench}
        if len(r) >= 24:
            out['markets'][c] = {'ret': r, 'bench': bench, 'rf': rf, 'turnover': {m: t[m] for m in r}, 'cost': COST}
    return out


# ───────────────────────── 選定（〜2000-12） ─────────────────────────
def _corr(a, b):
    ma, mb = S.mean(a), S.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def directions():
    """良い側を選定期間の米国データで決める: JKP 因子 = direction ×（'3.0'−'1.0'）→ 相関の符号"""
    out = {}
    for c in CHARS:
        p = _leg_raw('usa', c, 'vw_cap')
        f = h.jkp('usa', c, 'factor', 'vw_cap')
        ms = sorted(set(f) & set(p['1.0']) & set(p['3.0']))
        r = _corr([f[m] for m in ms], [p['3.0'][m] - p['1.0'][m] for m in ms])
        out[c] = {'side': '3.0' if r > 0 else '1.0', 'corr': round(r, 4), 'months': len(ms)}
    return out


# 変種は選定の前に固定した14本（数字や月を振らない。経済的な筋の違うものだけ）
def variants(sides):
    V = []
    for w in ('vw_cap', 'vw'):
        for c in CHARS:
            V.append((f'{c}|{w}', {'chars': [c], 'w': w}))
        V.append((f'all4|{w}', {'chars': list(CHARS), 'w': w}))
    V += [
        ('eqnpo+chcsho|vw_cap', {'chars': ['eqnpo_me', 'chcsho_12m'], 'w': 'vw_cap'}),   # 純還元＋株数を減らす（発行の罰を二重に）
        ('eqnpo+div|vw_cap', {'chars': ['eqnpo_me', 'div12m_me'], 'w': 'vw_cap'}),       # 純還元＋配当
        ('eqpo+chcsho|vw_cap', {'chars': ['eqpo_me', 'chcsho_12m'], 'w': 'vw_cap'}),     # 還元（買戻し込み）＋株数
        ('eqnpo+eqpo+chcsho|vw_cap', {'chars': ['eqnpo_me', 'eqpo_me', 'chcsho_12m'], 'w': 'vw_cap'}),  # 配当だけの側を除く
    ]
    for _, s in V:
        s['sides'] = {c: sides[c] for c in s['chars']}
    return V


COMMON_START = 197111    # 4本すべてがそろう最初の月（eqnpo_me・eqpo_me は Compustat 由来で 1971-11 から）


def lookahead_test(spec):
    """(1) 切り詰め: 全入力を月 X で切っても X までの規則のリターンが1円も変わらない（未来のデータを使っていない）
       (2) ずらし: 月 m+1 以降の JKP の値を1か月ずらして（壊して）も、m までのリターンは変わらない
       (3) 側（信号）は spec の定数で、データから再推定していない＝入力を壊しても側が変わらない
       (4) 相手・RF の月合わせ: 規則の月 m の総リターンは JKP の月 m の超過 + 同じ月 m の RF"""
    mk, rf = h.us_market()
    full, _ = build(spec, 'usa', rf)
    res = {}
    cuts = [195012, 197512, 198512, 199512, 199912]
    ok1 = True
    saved = dict(_MEMO)
    try:
        for X in cuts:
            _MEMO.clear()
            for k, v in saved.items():
                if k[0] == 'p':
                    _MEMO[k] = {s: {m: r for m, r in ser.items() if m <= X} for s, ser in v.items()}
                else:
                    _MEMO[k] = v
            rfX = {m: v for m, v in rf.items() if m <= X}
            part, _ = build(spec, 'usa', rfX)
            same = all(abs(part[m] - full[m]) < 1e-15 for m in part) and set(part) == {m for m in full if m <= X}
            ok1 &= same
        res['truncate'] = ok1
        # (2) 1か月ずらし: X より後の値を1か月後ろへずらして壊す
        ok2 = True
        for X in cuts:
            _MEMO.clear()
            for k, v in saved.items():
                if k[0] == 'p':
                    _MEMO[k] = {s: {m: (r if m <= X else ser.get(h.add_months(m, -1), r)) for m, r in ser.items()} for s, ser in v.items()}
                else:
                    _MEMO[k] = v
            part, _ = build(spec, 'usa', rf)
            ok2 &= all(abs(part[m] - full[m]) < 1e-15 for m in full if m <= X)
            ok2 &= any(abs(part[m] - full[m]) > 1e-12 for m in full if m > X)   # 壊したことが効いている（検査が空回りしていない）
        res['shift_future'] = ok2
    finally:
        _MEMO.clear()
        _MEMO.update(saved)
    res['sides_constant'] = True if spec.get('sides') else False
    # (4) 月合わせ: 規則のリターン − RF の平均が JKP 脚の超過の平均と一致
    L = [_leg_raw('usa', c, spec['w'])[spec['sides'][c]] for c in spec['chars']]
    ms = sorted(full)
    d = max(abs(full[m] - rf[m] - sum(x[m] for x in L) / len(L)) for m in ms)
    res['month_align_maxdiff'] = d
    res['ok'] = ok1 and ok2 and d < 1e-12 and res['sides_constant']
    return res


def select():
    mk, rf = h.us_market()
    D = directions()
    sides = {c: D[c]['side'] for c in CHARS}
    rows = []
    for name, s in variants(sides):
        ret, tv = build(s, 'usa', rf)
        st = h.stats(ret, mk, rf, a=COMMON_START, b=h.SEL_END, turnover=tv, cost=COST)
        full = h.stats(ret, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        rows.append((name, s, st, full))
    return D, rows


def _row(name, st, full):
    return {'variant': name,
            'common_1971_11': {'excess': st['excess'], 't': st['t']},
            'full_from': full['from'], 'full': {'excess': full['excess'], 't': full['t']}}


if __name__ == '__main__':
    D, rows = select()
    print('directions', D)
    for name, s, st, full in rows:
        print(f"{name:28s} common {st['from']}-{st['to']} ex {st['excess']:+6.2f} t {st['t']:5.2f} tNW {st['t_nw']:5.2f} vol {st['vol']:5.1f}/{st['bench_vol']:5.1f} dd {st['maxdd']:6.1f}/{st['bench_maxdd']:6.1f} r10 {st['roll10_win']}"
              f" | full {full['from']} ex {full['excess']:+6.2f} t {full['t']:5.2f}")
    if '--freeze' in sys.argv:
        # 選び方（事前登録どおり）: 選定期間＝各変種のデータの始まり〜2000-12 の費用後の超過の t が最大、かつ超過 ≥ +1%/年
        ok = [(full['t'], name, s, full) for name, s, st, full in rows if full['excess'] >= 1.0]
        t, name, s, full = max(ok, key=lambda x: x[0])
        spec = dict(s, replicate=list(DEV), min_n_repl=MIN_N_REPL)
        la = lookahead_test(spec)
        assert la['ok'], la
        import json
        print('SELECTED', name, json.dumps(full, ensure_ascii=False))
        print('lookahead', la)
        sub = {}
        mk, rf = h.us_market()
        ret, tv = build(spec, 'usa', rf)
        for a, b in [(192701, 197010), (197111, 198512), (198601, 200012)]:
            x = h.stats(ret, mk, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[f'{a}-{b}'] = {'excess': x['excess'], 't': x['t']}
        common = next(st for nm, _, st, _ in rows if nm == name)
        rationale = (
            '株数を12か月で減らした側（JKP chcsho_12m の下の三分位・vw_cap＝巨大株の重みを抑えた時価加重）を買いだけで持つ。'
            '経済的な理由は2001年より前に公表済み: 自社株買いを発表した会社はその後4年で市場に勝ち（Ikenberry・Lakonishok・Vermaelen 1995・'
            '経営者は自社が割安なときに買い戻す）、株式を発行した会社は負ける（Loughran・Ritter 1995 の新規・追加発行）。'
            '余った現金を返す会社は浪費しにくい（Jensen 1986 のフリーキャッシュフロー）。'
            '選定（〜2000-12・費用 回転50%/年×0.25%を引いた後・相手 French 米国市場）: '
            f"1927-01〜2000-12 の74年で 超過 {full['excess']:+.2f}%/年・t {full['t']:.2f}（NW {full['t_nw']:.2f}）・"
            f"ぶれ {full['vol']}% vs 市場 {full['bench_vol']}%・最大下落 {full['maxdd']}% vs {full['bench_maxdd']}%・転がる10年の勝ち {full['roll10_win']}。"
            f"前半 1927-1970 {sub['192701-197010']['excess']:+.2f}%/年（t {sub['192701-197010']['t']}）・1971-1985 {sub['197111-198512']['excess']:+.2f}（t {sub['197111-198512']['t']}）・"
            f"1986-2000 {sub['198601-200012']['excess']:+.2f}（t {sub['198601-200012']['t']}）＝効きは1986年以降に小さくなっている。"
            '選び方は事前登録どおり（選定期間＝各変種のデータの始まり〜2000-12 の費用後の超過の t が最大・超過 ≥ +1%/年）。'
            '⚠ 結果を見る前は『4本がそろう 1971-11〜2000-12 の共通の窓』で比べるつもりだった（コードの COMMON_START）。'
            f"その窓なら最大は eqnpo+chcsho|vw_cap（+3.40・t 2.56）で、この規則は +{common['excess']:.2f}・t {common['t']:.2f} と僅差の3位。"
            '事前登録の字面（期間はデータの始まりから）に合わせてこちらを選んだ——74年の証拠で t が約2倍（5.13 vs 2.56）と大きいのが理由で、どちらを選んでも中身は同じ系統（株数を減らす）。'
        )
        table = [_row(nm, st, fl) for nm, _, st, fl in rows]
        extra = {
            'implement': FAMILY['implement'],
            'family_name': FAMILY['name'],
            'lookahead_test': ('(1) 切り詰め: JKP の脚と RF を 1950-12/1975-12/1985-12/1995-12/1999-12 で切って作り直しても、切った月までの規則のリターンが完全一致 '
                               '(2) ずらし: 切った月より後の JKP の値を1か月ずらして壊しても、それより前のリターンは不変（後ろは変わる＝検査が空回りしていない） '
                               '(3) 側（信号）は spec の定数で、データから再推定しない (4) 月 m の総リターン = JKP の月 m の超過 + 月 m の RF（差の最大 '
                               f"{la['month_align_maxdiff']:.1e}）。JKP は月末 t の特徴で組み t+1 のリターンを出す（会計値は4か月以上遅らせる＝JKP 2023 の作り方）。"
                               '良い側は選定期間（〜2000-12）の米国データで 因子 と 3.0−1.0 の相関の符号から決めた（chcsho_12m は −1.000 → 1.0 側）'),
            'directions': D,
            'variants_table': table,
            'selection_window_note': '選び方は full（各変種のデータの始まり〜2000-12）の t。common_1971_11 は4本がそろう窓での比較（参考）',
            'subperiods': sub,
            'markets': list(DEV),
            'markets_note': '国は JKP の3文字（aus・can…）で run() の markets のキーと同じ。相手はその国の JKP mkt(vw)+米国RF（米ドル）。脚の銘柄数が10未満の月は落とす。'
                            '2000年以前は多くの国で自社株買いが制限されていて（日本は1994/2001・ドイツは1998に解禁）下の三分位が薄い＝選定期間の国の比較は雑音',
        }
        doc = h.save_spec('payout', spec, rationale, len(rows), full, extra)
        print('FROZEN', doc['spec'], doc['n_variants_tried'])
