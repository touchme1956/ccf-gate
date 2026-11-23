#!/usr/bin/env python3
"""night/field_exposure.py — いまの目標の形は「伸びると言われる分野」をどれだけ持っているか（読むだけ・参考・判定なし）

ユーザー（2026-11-23）「将来20年投資する想定で今後伸びる分野は？」への答えの材料。
伸びる分野の一覧そのもの（需要の予想・今の値段・過去の成績）は out/bestpf_themes.json・out/future30.json と書庫にある。
この道具が足すのは一つだけ: **いまの目標の形が、その分野をもう何%持っているか**（ETF の中身まで分解・資産全体の%）。
配分・採点・注文書は変えない。「変えたらどうなるか」は測らない（今ある形を数えるだけ）。

数え方（道具の頭に固定）
  - ETF の中身の業種は best15r_check.industry_vectors をそのまま使う（R・X・unx と同じ保有と SEC の SIC → French 49業種。
    rows の top_industries と一致を自己検問）。米国の市場は best15r_check.industry_state の最新月の比重（French・社数×平均時価総額）。
  - 個別株10%は今の席（out/score_all.json の buy・Ω の降順）を等分（beat_ret_check ほかと同じ置き方）。業種は同じ SIC の表から。
  - 資産全体＝ETF 側 ×(1−個別株%) ＋ 個別株%。
  - 分野の束ね方は下の FIELDS（49業種を10の束へ・重なりなし・合計100%を自己検問）。
  - ★ITA（防衛・航空宇宙の ETF）は、分野の表では**全部を防衛・航空宇宙に数える**。SEC の SIC では中身の GE Aerospace が
    電気機器（ElcEq）・Howmet が鉄鋼（Steel）に入り、そのまま束ねると「電力・電化の設備」に航空機エンジンの会社が混ざるため。
    業種ごとの一覧（業種の上位）は SIC の分類のまま出す。
    ⚠ この扱いは、試しに回した結果（ITA の ElcEq 23.6%）を見てから決めた＝事後。判定の無い記述の道具なので結果は選んでいない。
  - 米国の市場の列は French の分類のまま（GE Aerospace などは市場の側でも電気機器に入る＝市場の防衛・航空宇宙は少し小さく出る）。

比べる形（ETF 側の比・個別株10%）
  今の形（main）＝ beat_ret_check.NOWF（origin/main の portfolio.json と照合・違えば止まる）
  枝の案       ＝ beat_ret_check.RF（この枝の portfolio.json と照合・違えば止まる）
  最終結論     ＝ NASDAQ100 25 / SMH 35 / ITA 15 / FBT 15 / VBR 10（書庫:21777・事後の判断の形）

使い方: python3 night/field_exposure.py → out/field_exposure.json（約40秒）
"""
import contextlib, io, json, os, subprocess, sys, time, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import beat_ret_check as BT   # noqa: E402
import best15r_check as BR    # noqa: E402

OUT = os.path.join(BASE, 'out', 'field_exposure.json')
CASTLE_PCT = 10.0
FINAL = {'QQQM': 25, 'SMH': 35, 'ITA': 15, 'FBT': 15, 'VBR': 10}
K_NOW, K_FIN, K_R, K_MKT = '今の形（main）45/20/10/15/10', '最終結論 25/35/15/15/10', '枝の案 40/30/15/10/5', '米国の市場'
AS_DEFENSE = ('ITA',)          # 分野の表では全部を防衛・航空宇宙に数える本
FIELDS = [
    ('AI・半導体・ソフト', ['Chips', 'Softw', 'Hardw']),
    ('機械・計測（半導体の製造装置を含む）', ['Mach', 'LabEq']),
    ('防衛・航空宇宙', ['Aero', 'Guns', 'Ships']),
    ('電力・電化の設備', ['Util', 'ElcEq']),
    ('ヘルスケア（医薬品・医療機器・医療サービス）', ['Drugs', 'MedEq', 'Hlth']),
    ('金融・不動産', ['Banks', 'Insur', 'Fin', 'RlEst']),
    ('エネルギー・資源', ['Oil', 'Coal', 'Mines', 'Gold']),
    ('生活必需・消費', ['Food', 'Soda', 'Beer', 'Smoke', 'Hshld', 'Rtail', 'Meals', 'Clths', 'Toys', 'Fun', 'PerSv', 'Agric', 'Books']),
    ('企業向けサービス・通信', ['BusSv', 'Telcm']),
]
REST = 'その他（素材・運輸・建設・自動車ほか）'


def log(*a):
    print(*a, flush=True)


def main():
    t0 = time.time()
    live = json.loads(subprocess.run(['git', 'show', 'origin/main:portfolio.json'], capture_output=True, text=True,
                                     cwd=BASE, check=True).stdout)['target']
    brt = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    for k, t, f in [(K_NOW, live, BT.NOWF), (K_R, brt, BT.RF)]:
        w, cp = BT.etf_side(t)
        if not BT.same(w, f) or cp != CASTLE_PCT:
            raise SystemExit(f'{k} が正本と違う: {w} 個別株 {cp}（beat_ret_check の NOWF・RF を直してから回す）')
    forms = {K_NOW: dict(BT.NOWF), K_FIN: dict(FINAL), K_R: dict(BT.RF)}

    import unx_assets as U
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows = res['rows']
    st = BR.industry_state()
    with contextlib.redirect_stdout(io.StringIO()):
        vec, chk = BR.industry_vectors(U, rows)
    funds = sorted({c for f in forms.values() for c in f})
    bad = [c for c in funds if c not in vec or not chk.get(c)]
    if bad:
        raise SystemExit(f'中身の業種が rows の top_industries と一致しない／無い: {bad}')
    mkt = dict(st['mkt'])

    sa = json.load(open(os.path.join(BASE, 'out', 'score_all.json')))
    seats = [r['t'] for r in sorted((r for r in sa if r.get('buy')), key=lambda r: -float(r.get('s') or 0))]
    if not seats:
        raise SystemExit('席が0社（out/score_all.json の buy が無い）')
    with contextlib.redirect_stdout(io.StringIO()):
        ind_of, _ = U.mapper(set(seats))
    seat_ind = {t: ind_of(t) for t in seats}
    if any(v is None for v in seat_ind.values()):
        raise SystemExit(f'席の業種が決まらない: {seat_ind}')

    used = [k for _, ks in FIELDS for k in ks]
    assert len(used) == len(set(used)), '分野の束に重なりがある'
    unknown = [k for k in used if k not in mkt]
    assert not unknown, unknown

    def industries(etf, as_defense):
        d = {}
        for c, w in etf.items():
            v = {'Aero': 1.0} if (as_defense and c in AS_DEFENSE) else vec[c]
            for k, x in v.items():
                d[k] = d.get(k, 0.0) + (1 - CASTLE_PCT / 100) * w / 100 * x
        for t in seats:
            d[seat_ind[t]] = d.get(seat_ind[t], 0.0) + CASTLE_PCT / 100 / len(seats)
        return d

    def fields(d):
        o = {lab: round(100 * sum(d.get(k, 0.0) for k in ks), 1) for lab, ks in FIELDS}
        o[REST] = round(100 * sum(v for k, v in d.items() if k not in used), 1)
        return o

    tab, top, sums = {}, {}, {}
    tab[K_MKT] = fields(mkt)
    top[K_MKT] = {k: round(100 * v, 1) for k, v in sorted(mkt.items(), key=lambda kv: -kv[1])[:12]}
    sums[K_MKT] = round(sum(mkt.values()), 6)
    for nm, f in forms.items():
        if abs(sum(f.values()) - 100) > 1e-9:
            raise SystemExit(f'{nm} の ETF 側の比が100でない')
        d = industries(f, True)
        tab[nm] = fields(d)
        sums[nm] = round(sum(d.values()), 6)
        raw = industries(f, False)
        top[nm] = {k: round(100 * v, 1) for k, v in sorted(raw.items(), key=lambda kv: -kv[1])[:12]}
    chk_sum = {k: abs(v - 1) < 1e-6 for k, v in sums.items()}
    if not all(chk_sum.values()):
        raise SystemExit(f'合計が100%にならない: {sums}')

    per_fund = {c: {k: round(100 * v, 1) for k, v in sorted(vec[c].items(), key=lambda kv: -kv[1])[:8]} for c in funds}
    doc = {
        'generated': datetime.date.today().isoformat(), 'tool': 'night/field_exposure.py',
        'kind': '参考・判定なし・読むだけ（配分・採点・注文書は変えない。変えたらどうなるかは測らない）',
        'question': 'いまの目標の形は、伸びると言われる分野をどれだけ持っているか（ETF の中身まで・資産全体の%）',
        '読み方': ['ETF の中身の業種＝SEC の SIC → French 49業種（best15r_check.industry_vectors）・米国の市場＝French の最新月の比重',
                '個別株10%は今の席を等分・資産全体＝ETF 側×0.9＋個別株10%',
                'ITA は分野の表では全部を防衛・航空宇宙に数える（SIC では GE Aerospace が電気機器・Howmet が鉄鋼に入るため・結果を見てから決めた＝事後）',
                '米国の市場の列は French の分類のまま（市場の防衛・航空宇宙は少し小さく・電力・電化の設備は少し大きく出る）',
                'NASDAQ100 は QQQM の中身（iFreeNEXT も同じ指数）・中身は out/etf_profiles.json ほかの日付の写真'],
        '市場の比重の月': st['mkt_month'], '個別株の席（等分）': seats, '席の業種': seat_ind,
        '形（ETF 側の比）': forms, '個別株(%)': CASTLE_PCT,
        '分野（資産全体の%）': tab,
        '業種の上位（SIC の分類のまま・資産全体の%）': top,
        '本ごとの中身の業種の上位(%)': per_fund,
        'self_checks': {'中身の業種が rows の top_industries と一致': {c: bool(chk.get(c)) for c in funds},
                        '合計が100%': chk_sum,
                        '今の形＝origin/main・枝の案＝この枝の portfolio.json': True},
        '⚠': ['分野の束ね方はこの道具が決めた（49業種を10の束へ）。束ね方を変えれば数字は動く',
              'SIC は会社の登録上の業種で、事業の中身と合わないことがある（GE Aerospace・Howmet・Apple〔French寄せで半導体・電子部品〕）',
              '目標の姿であって今の実際の保有ではない（実際の保有は個別株と XLK が多く、AI・半導体・ソフトにもっと寄っている）',
              '「分野を持っている」ことと「その分野で儲かる」ことは別（書庫の future30・bestpf_themes・tech_persist・industry_peak）'],
        'secs': round(time.time() - t0, 1)}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    log('→', OUT, f'（{doc["secs"]}秒）市場の比重の月', st['mkt_month'], '席', seats)
    labs = [lab for lab, _ in FIELDS] + [REST]
    cols = [K_NOW, K_FIN, K_R, K_MKT]
    log('%-22s' % '分野', ' | '.join(c[:14] for c in cols))
    for lab in labs:
        log('%-22s' % lab[:22], ' | '.join('%6.1f' % tab[c][lab] for c in cols))
    for c in funds:
        log(c, per_fund[c])


if __name__ == '__main__':
    main()
