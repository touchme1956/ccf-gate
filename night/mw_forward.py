#!/usr/bin/env python3
"""night/mw_forward.py — 角度 forward（前向きの検証・読むだけ・門の判定・採点・配分には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまで…探し続けて」。歴史の検証は約3,500本を試し、
2007年以降の保有期間も一部は分かっている（知識の漏れは消せない）。**漏れの無い唯一の検証は、今日登録して
これから先の月で答え合わせをすること**。この道具は、事前登録 out/mw_forward_prereg.json に書いた
8本の仮説（7本の系列）を、登録月の翌月（2026-10）から毎月、いつ見ても有効な検定（e過程＝賭けの資産）で追う。

段
  design   : 設計値（μ_d・σ_d・B・λ）を登録前のデータ（≤2026-08。μ_d は ≤2006-12 の相手だけ）で計算して表示する
             ＝事前登録に書き写した数字の出どころ（再現用）。前向きのデータは使わない
  init     : 初期化＋検出力の計算（numpy を使う）→ out/mw_forward.json（前向きの月は 0）
  update   : 前向きの月（2026-10〜）を取り込み、e を更新 → out/mw_forward.json（標準ライブラリだけで回る＝CI 向け）
  form_sec Y : SEC の年次の組み直し（Y 年7月〜Y+1 年6月の保有）→ out/mw_forward_sec_formation_Y.json
             （companyfacts.zip を新しくしてから手で回す年1回の作業。2026 年分は事前登録に凍結済み）

約束（事前登録どおり）
- 比べるのは同じ通貨（米ドル）の総リターンどうし。月 m の値は m の月末が過ぎてから取り込む（未完の月は使わない）
- 一度取り込んだ月の値は固定（後のデータ改訂は反映しない・差は記録する）＝逐次検定の前提を守る
- 欠測を 0 と読まない（絶対のルール7）: 値が無い月はその系列を止めて待つ。3か月待っても出ない月は『欠測』として飛ばす
- 城（個別株）の名簿は、その月の初日より前の最後のコミットの out/score_all.json（buy）＋ gate_exceptions.json（in_castle_split）
"""
import sys, os, json, math, time, datetime, subprocess, statistics as S, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

BASE = M.BASE
PREREG = os.path.join(BASE, 'out', 'mw_forward_prereg.json')
OUT_NAME = 'mw_forward.json'
OUT = os.path.join(BASE, 'out', OUT_NAME)
FIRST_FWD = 202610
DESIGN_END = 202608
MAX_END = 204609                      # 20年で打ち切り（未決なら『証明できず』）
LN20 = math.log(20.0)
E_REJECT = 20.0                       # α=0.05（Ville の不等式）
WAIT_MONTHS = 3                       # 値が出ない月はこの月数待ってから『欠測』として飛ばす

# ───────────────────────── 系列の定義（事前登録と同じ・変えない） ─────────────────────────
HYP = {
    'H1_core_vs_SPY': {
        'ja': '投資家の ETF 側（iFreeNEXT NASDAQ100 60・SMH 20 ＝ QQQM 75% / SMH 25%・毎月の組み直し）対 SPY',
        'kind': 'mix', 'legs': {'QQQM': 0.75, 'SMH': 0.25}, 'bench': {'SPY': 1.0}, 'hist_sub': {'QQQM': 'QQQ'},
        'cost': 0.0, 'mu_rule': ('fixed', 1.0), 'real': True},
    'H2_castle_vs_SPY': {
        'ja': '城（その月の名簿を等分・毎月の組み直し）対 SPY',
        'kind': 'castle', 'bench': {'SPY': 1.0}, 'cost': 0.05, 'mu_rule': ('fixed', 3.0), 'real': True},
    'H3_castle_vs_QQQM': {
        'ja': '城（同上）対 QQQM（castle_rule の物差しと同じ相手）',
        'kind': 'castle', 'bench': {'QQQM': 1.0}, 'hist_sub': {'QQQM': 'QQQ'}, 'cost': 0.05, 'mu_rule': ('fixed', 3.0), 'real': True},
    'H4_exUS_valmom_real': {
        'ja': '米国外先進国の割安＋勢い・実在 ETF（PXF 50% / IMTM 50%・毎月の組み直し）対 VEA',
        'kind': 'mix', 'legs': {'PXF': 0.5, 'IMTM': 0.5}, 'bench': {'VEA': 1.0}, 'cost': 0.0,
        'mu_rule': ('counterpart', 'fr_dxus_valmom'), 'real': True},
    'H5_EM_multifactor_real': {
        'ja': '新興国の割安＋収益性の傾け・実在 ETF（AVEM）対 IEMG',
        'kind': 'mix', 'legs': {'AVEM': 1.0}, 'bench': {'IEMG': 1.0}, 'cost': 0.0,
        'mu_rule': ('counterpart', 'fr_em_big4'), 'real': True},
    'H6_US_quality_real': {
        'ja': '米国の質・実在 ETF（QUAL）対 SPY',
        'kind': 'mix', 'legs': {'QUAL': 1.0}, 'bench': {'SPY': 1.0}, 'cost': 0.0,
        'mu_rule': ('counterpart', 'jkp_cop_at'), 'real': True},
    'H7_SEC_cop_at_M100': {
        'ja': '紙: 時価総額上位100社のうち現金ベースの営業利益÷総資産（cop_at）の上位1/3・時価加重・毎年7月に組み直し（SEC XBRL）対 SPY',
        'kind': 'sec', 'bench': {'SPY': 1.0}, 'cost': 0.05,
        'mu_rule': ('counterpart', 'jkp_cop_at'), 'real': False},
    'H8_EM_big4_paper': {
        'ja': '紙: 新興国の大型株（French の BIG 行）で 割安・高収益・投資控えめ・勢い の良い側4本を等分 対 French の新興国市場',
        'kind': 'french_em', 'cost': 0.18,
        'mu_rule': ('counterpart', 'fr_em_big4'), 'real': False},
}
ORDER = list(HYP)
CLIP_K = 4.0                          # B = 4σ_m を 0.5% 単位で切り上げ
MU_HAIRCUT = 0.5                      # 公表後の縮み（program の実測 0.44〜0.56）
MU_LO, MU_HI = 0.5, 3.0               # μ_d の下限・上限（%/年）


# ───────────────────────── 小道具 ─────────────────────────
def nextm(k):
    y, m = divmod(k, 100)
    return (y + 1) * 100 + 1 if m == 12 else k + 1


def addm(k, n):
    y, m = divmod(k, 100)
    m0 = y * 12 + (m - 1) + n
    return (m0 // 12) * 100 + m0 % 12 + 1


def months(a, z):
    out, k = [], a
    while k <= z:
        out.append(k); k = nextm(k)
    return out


def mlen(k):
    y, m = divmod(k, 100)
    return (datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.date(y, m, 1)).days


def today_ym():
    d = datetime.datetime.utcnow().date()
    return d.year * 100 + d.month


_FRESH = {'max_age': 30}


def _fresh_get():
    """French の表を新しく取る（update 段）。mw_common.get の既定30日を1日へ。この工程の中だけ（他の道具には影響しない）"""
    orig = M.get

    def g(url, name=None, max_age_days=30, tries=5):
        if name and name.startswith('fr_'):
            name = 'fw_' + name
            max_age_days = min(max_age_days, _FRESH['max_age'])
        return orig(url, name=name, max_age_days=max_age_days, tries=tries)
    M.get = g


# ───────────────────────── Yahoo（日次の調整後終値から月末値） ─────────────────────────
_YH = {}


def yh_ticker(t):
    """城の日本株（数字だけ）は東証の .T（円建て）"""
    return f'{t}.T' if t.isdigit() else t


def yh_daily(ticker, max_age=1.0):
    if ticker in _YH:
        return _YH[ticker]
    u = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}'
         f'?period1=0&period2={int(time.time())}&interval=1d&events=div%2Csplit')
    safe = ticker.replace('^', 'IDX_').replace('=', '_')
    try:
        j = json.loads(M.get(u, name=f'fw_yh_{safe}_1d.json', max_age_days=max_age))
        r = j['chart']['result'][0]
        ts = r.get('timestamp') or []
        adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    except Exception as e:  # noqa
        _YH[ticker] = None
        return None
    rows = []
    for t_, a in zip(ts, adj):
        if a is None or a <= 0:
            continue                                   # 欠けた足は使わない（0 と読まない）
        d = datetime.datetime.utcfromtimestamp(t_)
        rows.append((d.year * 10000 + d.month * 100 + d.day, a))
    rows.sort()
    _YH[ticker] = rows
    return rows


def yh_monthly(ticker, max_age=1.0):
    """→ {yyyymm: 月次総リターン}。完了した月だけ: 当月より前 かつ 最後の足が月末の5日以内（祝日・週末の余裕）"""
    rows = yh_daily(ticker, max_age)
    if not rows:
        return {}
    last = {}
    for d, a in rows:
        last[d // 100] = (d, a)
    cur = today_ym()
    done = [m for m in sorted(last) if m < cur and (last[m][0] % 100) >= mlen(m) - 5]
    out = {}
    for a_, b_ in zip(done, done[1:]):
        if nextm(a_) == b_:
            out[b_] = last[b_][1] / last[a_][1] - 1
    return out


def usd_monthly(t, max_age=1.0):
    """城の銘柄の米ドル建て月次リターン（日本株は円→ドル: JPY=X＝1ドルあたり円）"""
    r = yh_monthly(yh_ticker(t), max_age)
    if not t.isdigit():
        return r
    fx = yh_daily('JPY=X', max_age)
    last = {}
    for d, a in fx or []:
        last[d // 100] = a
    out = {}
    for m, v in r.items():
        p = addm(m, -1)
        if m in last and p in last:
            out[m] = (1 + v) * (last[p] / last[m]) - 1
    return out


# ───────────────────────── French ─────────────────────────
def fr_col(name, col, want='Value Weight'):
    return M.french_series(name, want)[col]


def fr_mkt(region):
    """地域の市場（総リターン＝Mkt-RF + RF）"""
    name = 'Emerging_5_Factors' if region == 'Emerging' else f'{region}_3_Factors'
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly':
            i_m, i_rf = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            return {d: (row[i_m] + row[i_rf]) / 100 for d, row in v['data'].items() if row[i_m] is not None and row[i_rf] is not None}
    raise KeyError(name)


EM_GOOD = [('Emerging_Markets_6_Portfolios_ME_BE-ME', 'BIG HiBM'), ('Emerging_Markets_6_Portfolios_ME_OP', 'BIG HiOP'),
           ('Emerging_Markets_6_Portfolios_ME_INV', 'BIG LoINV'), ('Emerging_Markets_6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR')]


def em_big4():
    """→ (良い側4本の等分 {m: r}, 新興国市場 {m: r})。4本すべてある月だけ（欠けた月は作らない）"""
    legs = [fr_col(f, c) for f, c in EM_GOOD]
    mk = fr_mkt('Emerging')
    ms = sorted(set.intersection(*[set(x) for x in legs]) & set(mk))
    return {m: sum(x[m] for x in legs) / 4 for m in ms}, {m: mk[m] for m in ms}


def dxus_valmom():
    hb = fr_col('Developed_ex_US_6_Portfolios_ME_BE-ME', 'BIG HiBM')
    hp = fr_col('Developed_ex_US_6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR')
    mk = fr_mkt('Developed_ex_US')
    ms = sorted(set(hb) & set(hp) & set(mk))
    return {m: 0.5 * hb[m] + 0.5 * hp[m] for m in ms}, {m: mk[m] for m in ms}


# ───────────────────────── 城の名簿（git の履歴から・後知恵なし） ─────────────────────────
def _git_json_at(path, before_iso):
    try:
        sha = subprocess.run(['git', '-C', BASE, 'rev-list', '-1', f'--before={before_iso}', 'HEAD', '--', path],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        if not sha:
            return None, None
        txt = subprocess.run(['git', '-C', BASE, 'show', f'{sha}:{path}'], capture_output=True, text=True, timeout=60).stdout
        return json.loads(txt), sha
    except Exception:  # noqa
        return None, None


def roster_from(score_all, gex):
    out = [r['t'] for r in (score_all or []) if r.get('buy')]
    for it in (gex or {}).get('items', []):
        if it.get('in_castle_split') and it.get('t') not in out:
            out.append(it['t'])
    return out


def roster_at(m):
    """月 m の名簿＝ m の初日 00:00 UTC より前の最後のコミットの状態"""
    y, mm = divmod(m, 100)
    iso = f'{y:04d}-{mm:02d}-01T00:00:00+00:00'
    sa, s1 = _git_json_at('out/score_all.json', iso)
    ge, s2 = _git_json_at('gate_exceptions.json', iso)
    if sa is None:
        return None, None
    return roster_from(sa, ge), {'score_all': s1, 'gate_exceptions': s2}


def roster_now():
    sa = json.load(open(os.path.join(BASE, 'out', 'score_all.json')))
    ge = json.load(open(os.path.join(BASE, 'gate_exceptions.json')))
    return roster_from(sa, ge)


# ───────────────────────── SEC（cop_at 上位1/3・上位100社） ─────────────────────────
def sec_formation(year):
    """凍結された組入れ {ticker: 形成時の浮動株時価}。2026 は事前登録、以降は form_sec が書いたファイル"""
    if year == 2026:
        pr = json.load(open(PREREG))
        return pr['frozen']['sec_formation_2026']['weights_fcap']
    p = os.path.join(BASE, 'out', f'mw_forward_sec_formation_{year}.json')
    if os.path.exists(p):
        return json.load(open(p))['weights_fcap']
    return None


def sec_series(month_list, rets_of):
    """年1回7月に組み直し・年の中は買って持つ（重みは値動きで漂う）。値の無い銘柄はその月から外して残りで按分
    （mw_sec_replication.simulate と同じ規則）。→ {m: r}, {m: 外した銘柄}"""
    out, dropped = {}, {}
    by_year = {}
    for m in month_list:
        y = m // 100 if m % 100 >= 7 else m // 100 - 1
        by_year.setdefault(y, []).append(m)
    for y, ms in sorted(by_year.items()):
        w0 = sec_formation(y)
        if not w0:
            break                                       # 組み直しが無い年からは止める（0 で埋めない）
        tot = sum(w0.values())
        cur = {k: v / tot for k, v in w0.items()}
        for m in months(y * 100 + 7, max(ms)):
            av = {k: v for k, v in cur.items() if m in rets_of(k)}
            if not av:
                return out, dropped
            if len(av) < len(cur):
                dropped[m] = sorted(set(cur) - set(av))
            tv = sum(av.values())
            if m in ms:
                out[m] = sum(v * rets_of(k)[m] for k, v in av.items()) / tv
            cur = {k: v * (1 + rets_of(k)[m]) for k, v in av.items()}
    return out, dropped


# ───────────────────────── 系列を作る ─────────────────────────
_RET = {}


def R(t, sub=None, max_age=1.0):
    key = (t, max_age)
    if key not in _RET:
        _RET[key] = usd_monthly(t, max_age)
    return _RET[key]


def mix_series(legs, sub=None, max_age=1.0, hist=False):
    """毎月の組み直し。すべての足がある月だけ。hist=True なら QQQM の前は QQQ で延ばす（設計用だけ）"""
    parts = {}
    for t, w in legs.items():
        r = dict(R(t, max_age=max_age))
        if hist and sub and t in sub:
            r0 = R(sub[t], max_age=max_age)
            first = min(r) if r else 999999
            for m, v in r0.items():
                if m < first:
                    r[m] = v
        parts[t] = (w, r)
    ms = set.intersection(*[set(r) for _, r in parts.values()]) if parts else set()
    return {m: sum(w * r[m] for w, r in parts.values()) for m in sorted(ms)}


def castle_month(m, roster, max_age=1.0):
    rs = [(t, R(t, max_age=max_age).get(m)) for t in roster]
    av = [v for _, v in rs if v is not None]
    miss = [t for t, v in rs if v is None]
    if not roster or len(av) * 2 < len(roster):        # 半分以上欠けたら作らない（待つ）
        return None, miss
    return sum(av) / len(av), miss


def active_hist(h):
    """設計用の過去の追従差（月次・費用控除後）→ {m: x}（≤2026-08）"""
    d = HYP[h]
    cm = d['cost'] / 100 / 12
    if d['kind'] == 'mix':
        s = mix_series(d['legs'], d.get('hist_sub'), max_age=30, hist=True)
        b = mix_series(d['bench'], d.get('hist_sub'), max_age=30, hist=True)
    elif d['kind'] == 'castle':
        ros = json.load(open(PREREG))['frozen']['castle_roster_at_registration'] if os.path.exists(PREREG) else roster_now()
        rs = [R(t, max_age=30) for t in ros]
        ms = sorted(set.intersection(*[set(x) for x in rs]))
        s = {m: sum(x[m] for x in rs) / len(rs) for m in ms}
        b = mix_series(d['bench'], d.get('hist_sub'), max_age=30, hist=True)
    elif d['kind'] == 'sec':
        s = sec_hist_series()
        b = mix_series(d['bench'], max_age=30)
    elif d['kind'] == 'french_em':
        s, b = em_big4()
    ms = [m for m in sorted(set(s) & set(b)) if m <= DESIGN_END]
    return {m: s[m] - b[m] - cm for m in ms}, s, b


_SECH = {}


def sec_hist_series():
    """設計用: mw_sec_replication の 2010-2026 の組入れと月次リターンで cop_at_M100_T3VW を作る（≤2026-08）"""
    if 'S' in _SECH:
        return _SECH['S']
    import mw_sec_replication as X
    panel = X.build_panel()
    uni, price, diag, sic, tick = X.build_universe(panel, fetch=False, verbose=False)
    C = X.m100_cohorts(uni)
    rets = {x: v[0] for x, v in price.items() if v}
    sr, turn, drops = X.simulate(C['S'], rets)
    _SECH['S'] = sr
    _SECH['C'] = C
    _SECH['turn'] = turn
    return sr


# ───────────────────────── 設計値 ─────────────────────────
def counterpart_mu(key):
    """≤2006-12 の相手の超過の算術平均（%/年）と期間"""
    if key == 'fr_em_big4':
        s, b = em_big4()
    elif key == 'fr_dxus_valmom':
        s, b = dxus_valmom()
    elif key == 'jkp_cop_at':
        side, p = M.jkp_good_side('usa', 'cop_at', 'vw', upto=200612)
        ff = M.ff_factors()
        s, b = p[side], ff['mktrf']                    # JKP は超過・French Mkt-RF も超過（同じ基準）
    ms = [m for m in sorted(set(s) & set(b)) if m <= 200612]
    x = [s[m] - b[m] for m in ms]
    return {'mu_pre': round(S.mean(x) * 1200, 3), 'from': ms[0], 'to': ms[-1], 'n': len(ms),
            'te_pre': round(S.stdev(x) * math.sqrt(12) * 100, 3), 't_nw': M.nw_t(x)}


def design():
    out = {}
    cps = {}
    for h in ORDER:
        d = HYP[h]
        x, s, b = active_hist(h)
        ms = sorted(x)
        v = [x[m] for m in ms]
        sd = S.stdev(v) * math.sqrt(12) * 100          # σ_d（%/年）
        rule = d['mu_rule']
        if rule[0] == 'fixed':
            mu_d, cp = rule[1], None
        else:
            if rule[1] not in cps:
                cps[rule[1]] = counterpart_mu(rule[1])
            cp = cps[rule[1]]
            mu_d = min(MU_HI, max(MU_LO, MU_HAIRCUT * cp['mu_pre']))
        sm = sd / 100 / math.sqrt(12)
        B = math.ceil(CLIP_K * sm / 0.005 - 1e-12) * 0.005
        lam_k = (mu_d / 100) / (sd / 100) ** 2
        lam = min(lam_k, 1 / (2 * B))
        out[h] = {'sigma_d': round(sd, 3), 'sigma_window': [ms[0], ms[-1]], 'n_months': len(ms),
                  'mu_d': round(mu_d, 3), 'counterpart': rule[1] if rule[0] == 'counterpart' else None,
                  'B': round(B, 4), 'lambda_kelly': round(lam_k, 3), 'lambda': round(lam, 3),
                  'lambda_capped': lam < lam_k, 'mu_f': round(mu_d, 3),
                  'clipped_months_hist': sum(1 for q in v if abs(q) > B)}
    return out, cps


# ───────────────────────── e 過程 ─────────────────────────
def run_e(xs, lam, B, mu0_m=0.0, reverse=False):
    """H0: E[clip(x)] ≤ mu0（reverse=False）／ E[clip(x)] ≥ mu0（reverse=True）の賭けの資産。
    1 + λ(±(x̃−μ0)) ≥ 1 − λ(B+|μ0|) > 0 を λ ≤ 1/(2B) と |μ0| ≤ B/2 で保証"""
    e, path, first = 1.0, [], None
    for i, x in enumerate(xs):
        xc = max(-B, min(B, x))
        f = 1 + lam * ((mu0_m - xc) if reverse else (xc - mu0_m))
        e *= f
        path.append(e)
        if first is None and e >= E_REJECT:
            first = i
    return e, path, first


def cs_bounds(xs, lam, B):
    """いつ見ても有効な信頼の帯（切り詰めた平均の年率 %）: 下限＝これまでに一度でも e≥20 で退けられた μ0 の最大（片側）、
    上限＝逆向きで退けられた μ0 の最小。格子は −10〜+10%/年・0.1刻み（参考・判定には使わない）"""
    lo, hi = None, None
    for k in range(-100, 101):
        mu = k / 10
        mm = mu / 100 / 12
        if abs(mm) > B / 2:
            continue
        _, p, f = run_e(xs, lam, B, mm)
        if f is not None:
            lo = mu if lo is None else max(lo, mu)
        _, p2, f2 = run_e(xs, lam, B, mm, reverse=True)
        if f2 is not None:
            hi = mu if hi is None else min(hi, mu)
    return lo, hi


def e_bh(evals, alpha=0.05):
    """e-BH（Wang & Ramdas 2022）: e の大きい順に k 本目が K/(α k) 以上なら上位 k 本を退ける"""
    K = len(evals)
    items = sorted(evals.items(), key=lambda kv: -kv[1])
    kstar = 0
    for k, (_, e) in enumerate(items, 1):
        if e >= K / (alpha * k):
            kstar = k
    return [n for n, _ in items[:kstar]]


# ───────────────────────── 前向きの月を取り込む ─────────────────────────
def forward_x(h, m, fr_cache):
    """月 m の追従差（費用控除後）→ (x or None, 記録 dict)"""
    d = HYP[h]
    cm = d['cost'] / 100 / 12
    rec = {}
    if d['kind'] == 'mix':
        s = mix_series(d['legs']).get(m)
        b = mix_series(d['bench']).get(m)
    elif d['kind'] == 'castle':
        ros, shas = roster_at(m)
        if ros is None:
            return None, {'why': '名簿が git から取れない'}
        if not ros:                                     # 門の投下可も門外判断も0社＝城を持たない月（賭けない・待たない）
            return None, {'skip': True, 'why': '名簿が空（城を持たない月）', 'roster_commits': shas}
        s, miss = castle_month(m, ros)
        b = mix_series(d['bench']).get(m)
        rec = {'roster': ros, 'roster_commits': shas, 'missing_names': miss}
    elif d['kind'] == 'sec':
        y = m // 100 if m % 100 >= 7 else m // 100 - 1
        w0 = sec_formation(y)
        if not w0:
            return None, {'why': f'{y}年7月の組み直しが無い（form_sec {y} を回すまで止める）'}
        ser, dropped = sec_series(months(y * 100 + 7, m), lambda t: R(t))
        s = ser.get(m)
        b = mix_series(d['bench']).get(m)
        rec = {'formation_year': y, 'dropped': dropped.get(m, [])}
    elif d['kind'] == 'french_em':
        if 'em' not in fr_cache:
            fr_cache['em'] = em_big4()
        s, b = fr_cache['em'][0].get(m), fr_cache['em'][1].get(m)
    if s is None or b is None:
        return None, rec
    rec.update({'s': round(s, 6), 'b': round(b, 6)})
    return s - b - cm, rec


def update(stage='update'):
    pr = json.load(open(PREREG))
    fz = pr['frozen']['design']
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if stage == 'update':
        _fresh_get()
    last_done = addm(today_ym(), -1)
    target = [m for m in months(FIRST_FWD, min(last_done, MAX_END))]
    fr_cache = {}
    res = {}
    for h in ORDER:
        P = fz[h]
        old = ((prev.get('hypotheses') or {}).get(h) or {}).get('forward') or {}
        locked = {r['m']: r for r in old.get('months', [])}
        rows, waiting = [], []
        stopped = None
        for m in target:
            if m in locked:
                rows.append(locked[m]); continue
            if stopped:
                continue
            x, rec = (None, {})
            try:
                x, rec = forward_x(h, m, fr_cache)
            except Exception as e:  # noqa
                rec = {'why': f'取得の失敗: {e}'}
            if x is None and rec.get('skip'):
                rows.append({'m': m, 'x': None, 'skipped': True, 'note': rec.get('why'), 'locked_on': datetime.date.today().isoformat()})
                continue
            if x is None:
                age = (today_ym() // 100 * 12 + today_ym() % 100) - (m // 100 * 12 + m % 100)
                if age > WAIT_MONTHS:
                    rows.append({'m': m, 'x': None, 'missing': True, 'note': rec.get('why', '値が出ない（欠測として飛ばす）'), 'locked_on': datetime.date.today().isoformat()})
                    continue
                waiting.append(m); stopped = m           # 途中の月が未完なら先へ進まない（順番を守る）
                continue
            rows.append({'m': m, 'x': round(x, 6), 'locked_on': datetime.date.today().isoformat(), **rec})
        xs = [r['x'] for r in rows if r.get('x') is not None]
        e, path, first = run_e(xs, P['lambda'], P['B'])
        f, fpath, ffirst = run_e(xs, P['lambda'], P['B'], P['mu_f'] / 100 / 12, reverse=True)
        used = [r for r in rows if r.get('x') is not None]
        for r, ev, fv in zip(used, path, fpath):
            r['e'] = round(ev, 5); r['f'] = round(fv, 5)
        n = len(xs)
        fw = {'n_months': n, 'first_month': used[0]['m'] if used else None, 'last_month': used[-1]['m'] if used else None,
              'e_now': round(e, 5), 'e_max': round(max(path), 5) if path else 1.0,
              'rejected_at': used[first]['m'] if first is not None else None,
              'futility_now': round(f, 5), 'futility_at': used[ffirst]['m'] if ffirst is not None else None,
              'mean_active_ann_pct': round(S.mean(xs) * 1200, 3) if n else None,
              'cum_active_geo_pct': None, 'clipped_months': sum(1 for q in xs if abs(q) > P['B']),
              'waiting_for': waiting, 'months': rows}
        if n >= 12:
            lo, hi = cs_bounds(xs, P['lambda'], P['B'])
            fw['cs_trimmed_mean_ann_pct'] = {'lower': lo, 'upper': hi}
        if used:
            gs = math.prod(1 + r['s'] for r in used if 's' in r)
            gb = math.prod(1 + r['b'] for r in used if 'b' in r)
            fw['cum_active_geo_pct'] = round((gs / gb - 1) * 100, 3) if gb else None
        status = ('勝ち（e≥20・α=0.05）' if fw['rejected_at'] else
                  '見込みなし（設計の上乗せ μ_d を否定・e_f≥20）' if fw['futility_at'] else
                  '打ち切り（20年で未決）' if last_done > MAX_END else '追跡中')
        res[h] = {'definition': HYP[h]['ja'], 'real_vehicle': HYP[h]['real'], 'frozen': P, 'forward': fw, 'status': status}
    ev = {h: res[h]['forward']['e_now'] for h in ORDER}
    fam = {'K': len(ORDER), 'mean_e_now': round(sum(ev.values()) / len(ev), 5),
           'global_null_rejected': sum(ev.values()) / len(ev) >= E_REJECT,
           'e_bh_rejected_now': e_bh(ev), 'bonferroni_e_threshold': len(ORDER) / 0.05,
           'note': '個別の判定は e≥20（各 α=0.05）。8本の族では e-BH（偽発見率5%）と Bonferroni（e≥160）も併記する'}
    return res, fam


# ───────────────────────── 検出力（numpy） ─────────────────────────
def power(des, hist, n=5000, years=40, block=12, seed=20260928):
    import numpy as np
    rng = np.random.default_rng(seed)
    T = years * 12
    out = {}
    for h in ORDER:
        P = des[h]
        x = np.array([hist[h][m] for m in sorted(hist[h])])
        dmean = x - x.mean()
        nb = -(-T // block)
        st = rng.integers(0, len(dmean), size=(n, nb))
        idx = ((st[:, :, None] + np.arange(block)[None, None, :]) % len(dmean)).reshape(n, nb * block)[:, :T]
        base = dmean[idx]
        B, lam, muf = P['B'], P['lambda'], P['mu_f'] / 100 / 12
        rows = {}
        for mu in (0.0, 0.5, 1.0, 2.0, 3.0):
            xs = np.clip(base + mu / 100 / 12, -B, B)
            le = np.cumsum(np.log1p(lam * xs), axis=1)
            lf = np.cumsum(np.log1p(lam * (muf - xs)), axis=1)
            hit = le >= LN20
            fh = lf >= LN20
            first = np.where(hit.any(axis=1), hit.argmax(axis=1) + 1, 10 ** 6)
            ffirst = np.where(fh.any(axis=1), fh.argmax(axis=1) + 1, 10 ** 6)
            med = float(np.median(first)) / 12
            ir = mu / P['sigma_d'] if P['sigma_d'] else None
            rows[f'{mu:g}'] = {
                'p_cross_by': {f'{y}y': round(float((first <= y * 12).mean()), 3) for y in (3, 5, 10, 20)},
                'median_years_to_cross': round(med, 1) if med <= years else f'>{years}',
                'p_futility_by': {f'{y}y': round(float((ffirst <= y * 12).mean()), 3) for y in (3, 5, 10, 20)},
                'oracle_years_6_over_IR2': round(6 / ir ** 2, 1) if ir else None,
            }
        out[h] = {'sigma_d': P['sigma_d'], 'lambda': P['lambda'], 'B': P['B'], 'mu_d': P['mu_d'], 'by_true_edge_pct': rows}
    return out


def castle_rule_power(n=5000, years=20, block=12, seed=20260929):
    """castle_rule（portfolio.json）と代わりの規則の、真の上乗せごとの行動の確率。城=登録時の名簿の等分、相手=QQQ（QQQM の前）"""
    import numpy as np
    pr = json.load(open(PREREG))
    ros = pr['frozen']['castle_roster_at_registration']
    rs = [R(t, max_age=30) for t in ros]
    q = mix_series({'QQQM': 1.0}, {'QQQM': 'QQQ'}, max_age=30, hist=True)
    ms = [m for m in sorted(set.intersection(*[set(x) for x in rs]) & set(q)) if m <= DESIGN_END]
    c = np.array([sum(x[m] for x in rs) / len(rs) for m in ms]) - 0.05 / 100 / 12
    qq = np.array([q[m] for m in ms])
    a = c - qq
    te = float(a.std(ddof=1) * math.sqrt(12) * 100)
    rng = np.random.default_rng(seed)
    T = years * 12
    nb = -(-T // block)
    st = rng.integers(0, len(ms), size=(n, nb))
    idx = ((st[:, :, None] + np.arange(block)[None, None, :]) % len(ms)).reshape(n, nb * block)[:, :T]
    Pd = pr['frozen']['design']['H3_castle_vs_QQQM']
    lam, B, muf = Pd['lambda'], Pd['B'], Pd['mu_f'] / 100 / 12
    res = {'castle_roster': ros, 'window': [ms[0], ms[-1]], 'te_vs_qqq_pct': round(te, 2), 'by_true_edge_pct': {}}
    for mu in (-3.0, -1.0, 0.0, 1.0, 3.0, 5.0):
        cc = c[idx] - a.mean() + mu / 100 / 12            # 追従差の平均を mu に合わせる（QQQ 側はそのまま）
        qx = qq[idx]
        act = cc - qx
        lc, lq = np.log1p(cc), np.log1p(qx)

        def ann_diff(t0, t1):
            k = t1 - t0
            return (np.exp(lc[:, t0:t1].sum(1) * 12 / k) - np.exp(lq[:, t0:t1].sum(1) * 12 / k)) * 100
        # D0: 今の規則（3年: +3以上で25／5年: +3以上で30・負けで10／以降毎年 直近5年: +3以上で30・負けで一段下げ〔10→0〕）
        lvl = np.full(n, 20.0)
        track = {}
        d3 = ann_diff(0, 36)
        lvl = np.where(d3 >= 3, 25.0, lvl)
        track[3] = lvl.copy()
        for y in range(5, years + 1):
            d5 = ann_diff((y - 5) * 12, y * 12)
            alive = lvl > 0
            up = alive & (d5 >= 3)
            dn = alive & (d5 < 0)
            if y == 5:
                lvl = np.where(up, 30.0, np.where(dn, 10.0, lvl))
            else:
                lvl = np.where(up, 30.0, np.where(dn, np.where(lvl > 10, 10.0, 0.0), lvl))
            track[y] = lvl.copy()
        d0 = {f'{y}y': {'p_up(>20)': round(float((track[y] > 20).mean()), 3), 'p_down(<20)': round(float((track[y] < 20).mean()), 3),
                        'p_30': round(float((track[y] == 30).mean()), 3), 'p_0': round(float((track[y] == 0).mean()), 3)}
              for y in (3, 5, 10, 20)}
        # D1: e 過程（H3 と同じ設計）: e≥20 で 30%、e_f≥20（+3 を否定）で 10%
        xs = np.clip(act, -B, B)
        le = np.cumsum(np.log1p(lam * xs), axis=1)
        lf = np.cumsum(np.log1p(lam * (muf - xs)), axis=1)
        up1 = np.where((le >= LN20).any(1), (le >= LN20).argmax(1) + 1, 10 ** 6)
        dn1 = np.where((lf >= LN20).any(1), (lf >= LN20).argmax(1) + 1, 10 ** 6)
        d1 = {f'{y}y': {'p_up': round(float((up1 <= y * 12).mean()), 3), 'p_down': round(float(((dn1 <= y * 12) & (dn1 < up1)).mean()), 3)}
              for y in (3, 5, 10, 20)}
        # D2: 固定の見直し（5年・10年）: 起点からの t ≥ 1.65 で上げ、t ≤ −1.65 で下げ（NW でない単純 t・参考）
        d2 = {}
        for y in (5, 10, 20):
            seg = act[:, :y * 12]
            t = seg.mean(1) / (seg.std(1, ddof=1) / math.sqrt(y * 12))
            d2[f'{y}y'] = {'p_up': round(float((t >= 1.65).mean()), 3), 'p_down': round(float((t <= -1.65).mean()), 3)}
        res['by_true_edge_pct'][f'{mu:g}'] = {'D0_current_rule': d0, 'D1_eprocess': d1, 'D2_fixed_t_5_10_20y': d2}
    res['years_for_t2_at_edge3'] = round((2 * te / 3.0) ** 2, 1)
    return res


# ───────────────────────── 段 ─────────────────────────
def sanity():
    ff = M.ff_factors()
    m = ff['mkt']
    spy = R('SPY', max_age=30)
    ms = [k for k in sorted(set(spy) & set(m)) if k <= DESIGN_END]
    em_s, em_b = em_big4()
    iemg = R('IEMG', max_age=30)
    cm = [k for k in sorted(set(iemg) & set(em_b)) if k <= DESIGN_END]
    return {'french_mkt_cagr_1926_2026': round(M.cagr(m) * 100, 2), 'french_mkt_cagr_2007_': round(M.cagr(M.window(m, 200701)) * 100, 2),
            'spy_vs_french_mkt_same_months': {'from': ms[0], 'to': ms[-1], 'cagr_spy': round(M.cagr([spy[k] for k in ms]) * 100, 2),
                                              'cagr_french': round(M.cagr([m[k] for k in ms]) * 100, 2),
                                              'corr': round(M.corr([spy[k] for k in ms], [m[k] for k in ms]), 4)},
            'iemg_vs_french_em_mkt': {'from': cm[0], 'to': cm[-1], 'corr': round(M.corr([iemg[k] for k in cm], [em_b[k] for k in cm]), 4),
                                      'cagr_iemg': round(M.cagr([iemg[k] for k in cm]) * 100, 2), 'cagr_french_em': round(M.cagr([em_b[k] for k in cm]) * 100, 2)},
            'today_ym': today_ym(), 'last_complete_month_spy': max(spy)}


def sha_of(path):
    try:
        return subprocess.run(['git', '-C', BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


CI_LINE = ("ops.yml の steps に 1段足す: `- name: 前向きの検証（mw_forward・判定に不使用）` / `continue-on-error: true` / "
           "`run: timeout 900 python3 night/mw_forward.py update | tail -12`（fetch-depth: 0 は既にある＝城の名簿を git から引ける。"
           "出力 out/mw_forward.json は既存のコミット段が拾う out/ の下）")


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else 'update'
    if stage == 'design':
        des, cps = design()
        print(json.dumps({'design': des, 'counterparts': cps, 'roster_now': roster_now()}, ensure_ascii=False, indent=1))
        if _SECH.get('C'):
            w = _SECH['C']['S'][2026]
            print(json.dumps({'sec_formation_2026': w, 'turnover': _SECH.get('turn')}, ensure_ascii=False))
        return
    if stage == 'form_sec':
        form_sec(int(sys.argv[2]))
        return
    pr = json.load(open(PREREG))
    t0 = time.time()
    res, fam = update(stage)
    obj = {'angle': 'forward', 'role': '前向きの検証（登録 2026-09-28・最初の月 2026-10）。読むだけ・門の判定・採点・配分には不使用',
           'prereg': 'out/mw_forward_prereg.json', 'prereg_commit': sha_of('out/mw_forward_prereg.json'),
           'generated': datetime.date.today().isoformat(), 'first_forward_month': FIRST_FWD, 'max_end': MAX_END,
           'rule': 'e≥20 で退ける（各 α=0.05・Ville の不等式・いつ見ても有効）。逆向きの e_f≥20 で『設計の上乗せ μ_d は無い』＝見込みなし',
           'hypotheses': res, 'family': fam,
           'tested': [{'name': h, 'kind': 'forward_hypothesis', 'real_vehicle': HYP[h]['real'], 'status': res[h]['status'],
                       'forward_months': res[h]['forward']['n_months'], 'e_now': res[h]['forward']['e_now']} for h in ORDER],
           'ci_suggestion': CI_LINE}
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if stage == 'init':
        des = pr['frozen']['design']
        hist = {h: active_hist(h)[0] for h in ORDER}
        obj['power'] = power(des, hist)
        obj['castle_rule_power'] = castle_rule_power()
        obj['sanity'] = sanity()
    else:
        for k in ('power', 'castle_rule_power', 'sanity'):
            if k in old:
                obj[k] = old[k]
    obj['runtime_s'] = round(time.time() - t0, 1)
    M.save(OUT_NAME, obj)
    for h in ORDER:
        fw = res[h]['forward']
        print(f"{h:26s} 月数 {fw['n_months']:3d}  e={fw['e_now']:.3f}  e_f={fw['futility_now']:.3f}  {res[h]['status']}")
    print('族: 平均e', fam['mean_e_now'], 'e-BH', fam['e_bh_rejected_now'])


def form_sec(year):
    """Y 年7月の組み直し（事前登録の方法そのまま）。前提: out/_mw_cache/sec_companyfacts.zip を Y 年7月以降に取り直してあること"""
    import mw_sec_replication as X
    X.YEARS = list(range(2010, year + 1))
    X.END = year * 100 + 7
    X.FEAT_VERSION = f'fw{year}'                         # 他の道具のパネルのキャッシュを上書きしない
    zp = X.ZIP
    if year > 2026:
        if not os.path.exists(zp) or datetime.date.fromtimestamp(os.path.getmtime(zp)) < datetime.date(year, 7, 1):
            raise SystemExit(f'{zp} が {year}-07-01 より古い。SEC の一括 companyfacts.zip を取り直してから回す')
        X.EXTRACT = os.path.join(M.CACHE, f'sec_extract_fw{year}.jsonl.gz')
        X.extract(force=True)
    panel = X.build_panel()
    uni, price, diag, sic, tick = X.build_universe(panel, fetch=year > 2026, verbose=False)
    C = X.m100_cohorts(uni)
    w = C['S'].get(year)
    if not w:
        raise SystemExit(f'{year} の組入れが作れない')
    p = os.path.join(BASE, 'out', f'mw_forward_sec_formation_{year}.json')
    json.dump({'year': year, 'method': 'mw_sec_replication.m100_cohorts の S（cop_at 上位1/3・上位100社・浮動株時価加重）',
               'made_on': datetime.date.today().isoformat(), 'n': len(w), 'weights_fcap': w}, open(p, 'w'), ensure_ascii=False, indent=1)
    print(p, len(w))


if __name__ == '__main__':
    main()
