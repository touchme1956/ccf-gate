#!/usr/bin/env python3
"""night/past_winners.py — 今の組み合わせ以外で、過去に高いリターンを出した ETF・投資信託（10年・20年・30年・50年）
（2026-11-22・ユーザー「この組み合わせ以外で過去高いリターンを出してきたETFを10年20年30年50年」「投資信託も。」・参考・判定なし・配分は変えない）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。結果がどう出ても配分は変えない（入れるかはユーザーの明示指示のときだけ）。
★母集団・窓・物差し・外すもの・並べ方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットしてから回す。
  （書く前に見たのは材料の形だけ＝一覧の欄・本数・設定日・記録が何月から何月まであるか。成績の並びは見ていない）

今の組み合わせ: NASDAQ100（iFreeNEXT NASDAQ100・QQQ/QQQM/QNDX）・SMH・ITA・FBT・VBR。
窓（月次・最後の完全な月 2026-10 まで）:
  10年＝2016-11〜2026-10（120か月）／20年＝2006-12〜2026-10（239か月）／30年＝1996-11〜2026-10（360か月）
  ★20年が1か月短いのは、投資信託の基準価額の記録（投信総合検索ライブラリーの CSV）が直近20年ぶん（2006-11-24〜）しか無いため。
    ETF と投資信託を同じ窓で並べるので、ETF も同じ239か月で測る（回し直すときは窓を後ろへずらす）。
  長い記録（③）: 30年＝1996-10〜2026-09／50年＝1976-10〜2026-09（Ken French の表の最後の月が 2026-09 のため1か月前へずらす）
物差し: 年率（円・配当や分配金を再投資・税の前）。窓の月が全部そろう記録だけ。添える数字＝年率（ドル・米国上場とドルの系列だけ）・
  最大下落（円・月次）・同じ窓の S&P500 との差（円の年率の差）。
  円への直し方: 米国上場とドルの系列は FRED DEXJPUS の月末の比を掛ける（bestfund_data.fx）。東証の本・日本の投資信託は円のまま。
  ※ 米国上場 ETF の配当にかかる米国の源泉税（NISA で戻らない・年0.1〜0.3%前後）は引かない＝配当込みの値段そのまま。
    投資信託の基準価額は信託報酬と中の源泉税を引いた後の値＝同じ指数なら投資信託のほうが少し低く出る。

①ETF の実物の記録（10年・20年・30年）
  母集団: 楽天証券の ETF 一覧 ETFD.csv（2026-11-22 の写し・sha256 は etf_more_check と同じ）の米国上場と東証・名証
    （香港・シンガポール上場は母集団の外＝etf_more_check と同じ）。
  外すもの（etf_more_check.why_out のまま）: X1 レバレッジ・インバース／X2 通貨・ボラティリティ／
    X4 今の本と同じ指数（QQQ・QQQM・QNDX・SMH・ITA・FBT・VBR）＝並びに入れず『比べる相手』として出す／
    X5 方針で外す（金・国債＝2026-11-04「金国債はいりない」）＝並びに入れず、窓ごとに年率の上位を名前つきで別に出す
  値段: Yahoo の配当込み月次（mw_common.yahoo）。壊れた値＝窓の中に月次 −60% 以下か +100% 以上の月があれば、その窓は使わない。
    東証・名証の本で並びの上位に入ったものは日次も見て、水準がずれたままの塊（etf_more_check.daily_shift）がある窓は使わない。
②日本の投資信託の実物の記録（10年・20年）
  母集団: 投信総合検索ライブラリー（資産運用業協会）の全件（2026-11-22 取得・基準日 2026-11-20・5,874本）。
  外すもの: F1 単位型／F2 ETF（①で測る）／F3 確定拠出年金・ラップ専用（nx_jpfunds_data.flags の dc_only・wrap_only）／
    X1 レバレッジ・インバース（名前に ブル・ベア〔前後がカタカナでないもの＝サステナブル等は外さない〕・レバレッジ・インバース・N倍・ブースト・
       トリプル・ダブル〔ダブルラインを除く〕。nx_jpfunds_data の special_regex のレバレッジの語を狭めたもの）＝外した本のうち
       ライブラリーの10年の騰落率の上位は名前だけ出す（測らない）／
    X4 今の本と同じ指数（名前に NASDAQ100・ナスダック100）／X5 方針（金＝etf_more_check.GOLD／国債＝etf_more_check.GOV と「ソブリン」）
  値段: ライブラリーの基準価額の CSV（基準価額と分配金）。分配金は落ちた日の基準価額で再投資。口数の併合・分割
    （1日の 〔基準価額＋分配金〕÷前日の基準価額 が 2・3・4・5・10・20・50・100 倍かその逆数の±5%以内）は比で戻し、戻した本は名前つきで出す。
    31日を超える空きのある月は使わない。壊れた値の決まりは①と同じ。
  測る本: 20年＝設定日が 2006-11-30 以前の本を全部。10年＝設定日が 2016-10-31 以前の本のうち、ライブラリーの10年の騰落率
    （基準日 2026-11-20＝窓と約20日ずれる・ふるいにだけ使う）の上位300本と、楽天証券で買える本の中の上位200本（＋20年で測る本は全部）。
    方針で外す本（X5）は、外さない本と合わせた同じ騰落率の上位300に入るものだけ測って、名前つきで別に出す。
  楽天で買える＝ライブラリーの販売会社の欄に「楽天証券」がある。NISA＝ nisaFlg（つみたて投資枠）・nisaGrowthFlg（成長投資枠）。
  並びは①の ETF と「楽天証券で買える投資信託」を合わせて1本にする。楽天で買えない投資信託は上位10本だけ別に出す。
③長い記録（30年・50年）＝指数・分野の記録をつないだもの（実物の ETF・投資信託の記録ではない・費用と税の前）
  (a) bestfund_data の39の賭けのつなぎ（実物〔経費率を足し戻す〕← 指数 ← French・Shiller の代わり）から方針の金を外した38本と、
      バイオ（FBT ← French の Drugs）。今の組み合わせの賭け（NASDAQ100・半導体〔SMH の指数〕・航空防衛・小型バリュー・バイオ）は
      並びに入れず『比べる相手』として出す。窓の月のうち実物・指数の月の割合と、何をつないだかを添える。
  (b) Ken French の49業種（時価加重）。窓の最初の月に市場の0.25%以上で、窓の月が全部そろう業種だけ（industry_century と同じ線）。
      今買える本（industry_century.VEHICLE のうち楽天の ETF 一覧にある本）を添える。今の組み合わせに当たる業種
      （半導体・電子部品＝SMH／航空機・防衛＝ITA／医薬品＝FBT）と NASDAQ100 の中心の業種（ソフトウェア・コンピュータ機器）は印を付ける。
  30年は①の実物（当時からある ETF）と別の表で出す（窓が1か月違うので同じ表に混ぜない）。50年は③だけ
  （50年前から続く ETF は無い。日本の投資信託は設定が1976年以前の本があるが、協会の記録は直近20年ぶんで測れない＝名前だけ出す）。
同じ賭けの印（①②の並びの上位だけ）: 2016-11〜2026-10 の円のリターンで、今の5本（QQQ・SMH・ITA・FBT・VBR）のどれかとの相関が0.95以上
  （米国上場どうしは月次・東証や投資信託と米国上場の組は重ならない四半期＝etf_more_check.xcorr と同じ）。③(a) は窓の最後の120か月の月次。
家族（並びを読みやすくするため）: ①②を合わせた並びの上位80本を年率の高い順に見て、その窓の相関（上と同じ測り方）が0.95以上の
  上の本（家族の代表）があればその家族に入れる。並びは家族ごとに1本（代表＝年率が最も高い本・家族の本の数と名前を添える）・上位30家族。
  30家族に満たなければ上位を40本ずつ足す（400本まで）。
比べる相手（どの窓にも）: S&P500（①② は実物の SPY・③ は S&P500 のつなぎ）・今の5本（①② は実物・③ はつなぎ）・
  5本の組み合わせ（ETF 側 45:20:10:15:10＝main／40:30:15:10:5＝枝の案・毎月組み直し）。
出すもの: 窓ごとに 並びの上位30家族・楽天で買えない投資信託の上位10・方針で外した本の上位10・測れた本の数と S&P500 を上回った本の数／
  30年・50年の長い記録（賭け・業種）の全部／30年・50年の記録がある日本の投資信託の本数と名前（測れない理由つき）。
回帰の検査: (a) 基準価額の読み手が nx_jpfunds_data.monthly_tr（併合・分割なしの本）・bestfund_data.jita_monthly（1321）と一致
  (b) 投資信託の10年の累積がライブラリーの10年の騰落率と大きくずれない（基準日が約20日違うので目安・順位相関を出す）
  (c) SPY の30年の年率（ドル）と S&P500 のつなぎの差が小さい。(a) が通らなければ止まる。
⚠ 限界: 過去の成績で予想ではない（過去10年の1位の業種は次の10年に市場に負けやすい＝tech_persist）／今も残っている本だけ
  （消えた本は入らない＝生き残りの偏り）／10年・20年の窓は米国のテックが勝った一つの時代／③は紙の上の指数（費用・税の前）／
  円の年率は為替を含む（1976-10 は1ドル294円・2026-10 は157円）／Yahoo の値の誤り／投資信託の10年はふるいの上位からだけ測る／
  楽天で買える＝ NISA の対象とは限らない（投資信託は印あり・ETF は印なし）／同じ賭けの線0.95は目安
★回したあとの是正（2026-11-23・1回目の結果を見た後・決まりの当て方の穴＝どちらも「外すもの」の趣旨どおりに当て直しただけ）:
  是正1 X1（投資信託）: 名前の語だけでは、協会の分類が「特殊型」（ブル・ベア型など）なのに名前に語が無い本を外せなかった
    （1回目は日経平均の約2.5倍で動く『ハイパー・ウェイブ（日本トレンド・セレクト）』が10年の4位・20年の21位に入り、逆向きの
    『リバース・トレンド・オープン』も測る候補に入っていた）→ 協会の分類が特殊型（supplementKindCd=2＝nx_jpfunds_data の special_kind）も X1 にする。
    名前の語は固定のまま（愛称に「ダブル」「トリプル」がある普通の本を外す向きの誤りは残る＝外した本の上位は名前で出す）。
  是正2 X4（ETF）: etf_more_check.why_out は米国上場の7本だけを「今の本と同じ指数」にしていて、東証の NASDAQ100 連動 ETF
    （指数名が NASDAQ 100 TR／同 JPYH＝1545・2568・2569・2631・2632・2840・2841・2845・2087・534A）が並びの母数に入っていた → X4 にする。
  1回目の出力との違いは書庫の節に書く。ほかの決まり（窓・物差し・ふるい・家族・印）は変えていない。
  注の追加（並びは変えない）: 楽天の一覧の設定日が窓の始まりより後の米国 ETF には「前身の本の記録を含む」と書く
    （BBH・RTH・PPH は 2011-12 に今の形になり、それより前の Yahoo の値段は前身の HOLDRS＝固定の籠）。
使い方: python3 night/past_winners.py → out/past_winners.json（投資信託の CSV を約1,000本取るので初回は約20分）
"""
import json, math, os, re, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etfcand as E                        # noqa: E402
import etfcand_short as ES                 # noqa: E402
import etf_more_check as EM                # noqa: E402
import mw_common as M                      # noqa: E402
import bestfund_data as B                  # noqa: E402
import nx_jpfunds_data as D                # noqa: E402
import industry_century as IC              # noqa: E402
from industry_trends import JA as IND_JA   # noqa: E402

OUT = os.path.join(BASE, 'out', 'past_winners.json')
CDIR = os.path.join(BASE, 'out', '_nx_cache', 'horizons')
LIST = os.path.join(CDIR, 'jita_full_20261122.json')
NAVDIR = os.path.join(CDIR, 'nav')
END = 202610
WIN = {'10年': (201611, 202610), '20年': (200612, 202610), '30年': (199611, 202610)}
WINL = {'30年': (199610, 202609), '50年': (197610, 202609)}
W10 = WIN['10年']
FIVE = ['QQQ', 'SMH', 'ITA', 'FBT', 'VBR']
MIXES = {'5本の組み合わせ（main の比 45:20:10:15:10）': [45, 20, 10, 15, 10], '5本の組み合わせ（枝の案 40:30:15:10:5）': [40, 30, 15, 10, 5]}
FIVE_BET = ['NDX', 'SEMI_MV', 'DEFENSE', 'BIOTECH', 'SMALLV']
SAME = 0.95
TOPN, SHOW = 80, 30
PRE10, PRE10R = 300, 200
EST20, EST10 = 20061130, 20161031
SLEEP = 1.0
MIN_SHARE = IC.MIN_SHARE
LEVF = re.compile(r'((?<![ァ-ヶー])ブル(?![ァ-ヶー])|(?<![ァ-ヶー])ベア(?![ァ-ヶー])|レバレッジ|インバース|[2-9]倍|ブースト|トリプル|ダブル(?!ライン))')
NDXF = re.compile(r'(?i)(NASDAQ|ナスダック)\s*[-‐・]?\s*100')
GOVF = re.compile(r'ソブリン')
SPLITK = (2, 3, 4, 5, 10, 20, 50, 100)
IND_NOW = {'Chips': '今の組み合わせ（SMH）', 'Aero': '今の組み合わせ（ITA）', 'Guns': '今の組み合わせ（ITA）', 'Drugs': '今の組み合わせ（FBT）',
           'Softw': 'NASDAQ100 の中心の業種', 'Hardw': 'NASDAQ100 の中心の業種'}


def log(*a):
    print('[past_winners]', *a, file=sys.stderr, flush=True)


def r2(x, d=2):
    return None if x is None else round(100 * x, d)


# ───────────────────────── 投資信託 ─────────────────────────
def load_list():
    if not os.path.exists(LIST):
        os.makedirs(CDIR, exist_ok=True)
        rows, total, std = D.Lib().search_all()
        json.dump(dict(rows=rows, total=total, std=std, fetched=time.strftime('%Y-%m-%d %H:%M')), open(LIST, 'w'), ensure_ascii=False)
    return json.load(open(LIST))


def est(r):
    return int((r.get('establishedDate') or '9999-99-99')[:10].replace('-', ''))


def rak(r):
    return any('楽天証券' in (x.get('instName') or '') for x in (r.get('institutionInfo') or []))


def ra10(r):
    try:
        return float(r.get('standardPriceRa10y'))
    except (TypeError, ValueError):
        return None


def fund_out(r):
    f = D.flags(r)
    nm = D.name_of(r)
    if not f['open_end']:
        return 'F1 単位型'
    if f['etf']:
        return 'F2 ETF（①で測る）'
    if f['dc_only'] or f['wrap_only']:
        return 'F3 確定拠出年金・ラップ専用'
    if LEVF.search(nm):
        return 'X1 レバレッジ・インバース'
    if r.get('supplementKindCd') == '2':
        return 'X1 レバレッジ・インバース（協会の分類が特殊型）'
    if NDXF.search(nm):
        return 'X4 今の本と同じ指数（NASDAQ100）'
    if EM.GOLD.search(nm):
        return 'X5 方針で外す（金）'
    if EM.GOV.search(nm) or GOVF.search(nm):
        return 'X5 方針で外す（国債）'
    return None


def nav_rows(b):
    rows = []
    for line in b.decode('cp932', errors='replace').splitlines()[1:]:
        x = line.split(',')
        m = re.match(r'(\d{4})年(\d{2})月(\d{2})日', x[0].strip())
        if not m:
            continue
        d = int(m.group(1) + m.group(2) + m.group(3))
        if d > END * 100 + 31:
            continue
        try:
            nav = float(x[1])
        except (ValueError, IndexError):
            continue
        if nav <= 0:
            continue
        dv = 0.0
        if len(x) > 3 and x[3].strip():
            try:
                dv = float(x[3])
            except ValueError:
                dv = 0.0
        rows.append((d, nav, dv))
    rows.sort()
    return rows


def fund_monthly(rows):
    """日次の基準価額＋分配金 → ({yyyymm: 月次の総リターン}, 併合・分割を戻した日の表)。最初の日の月・31日を超える空きの月は使わない"""
    if len(rows) < 2:
        return {}, []
    out, acc, cur, bad, splits = {}, 1.0, None, set(), []
    for (d0, n0, _), (d1, n1, v1) in zip(rows, rows[1:]):
        ym = d1 // 100
        if (D._ymd(d1) - D._ymd(d0)).days > 31:
            k = (d0 // 10000) * 12 + d0 // 100 % 100 - 1
            while k <= (ym // 100) * 12 + ym % 100 - 1:
                bad.add((k // 12) * 100 + k % 12 + 1)
                k += 1
        if cur is not None and ym != cur:
            out[cur] = acc - 1
            acc = 1.0
        cur = ym
        g = (n1 + v1) / n0
        for k in SPLITK:
            if abs(g / k - 1) < 0.05:
                splits.append((d1, f'{k}口→1口'))
                g /= k
                break
            if abs(g * k - 1) < 0.05:
                splits.append((d1, f'1口→{k}口'))
                g *= k
                break
        acc *= g
    if cur is not None:
        out[cur] = acc - 1
    out.pop(rows[0][0] // 100, None)
    if rows[-1][0] % 100 < 25:
        out.pop(rows[-1][0] // 100, None)
    for k in bad:
        out.pop(k, None)
    return {k: v for k, v in out.items() if k <= END}, splits


def fetch_navs(need):
    os.makedirs(NAVDIR, exist_ok=True)
    lib, miss, done = None, [], 0
    for i, (assoc, r) in enumerate(sorted(need.items())):
        p = os.path.join(NAVDIR, f'{assoc}.csv')
        if os.path.exists(p) and os.path.getsize(p) > 0:
            continue
        if os.path.exists(p + '.missing'):
            miss.append(assoc)
            continue
        if lib is None:
            lib = D.Lib()
        try:
            b = lib.csv(r['isinCd'], assoc)
        except Exception as e:  # noqa
            log('CSV 失敗（今回だけ飛ばす）', assoc, str(e)[:100])
            lib = None
            miss.append(assoc)
            time.sleep(SLEEP)
            continue
        if b is None:
            miss.append(assoc)
            open(p + '.missing', 'w').write('HTTP 500')
        else:
            open(p + '.tmp', 'wb').write(b)
            os.replace(p + '.tmp', p)
        done += 1
        if done % 100 == 0:
            log(f'基準価額 {done} 本取得（{i + 1}/{len(need)}）')
        time.sleep(SLEEP)
    return miss


def nisa_of(r):
    a = '1' == str(r.get('nisaFlg'))
    g = '1' == str(r.get('nisaGrowthFlg'))
    return 'つみたて・成長' if a and g else 'つみたて' if a else '成長' if g else '対象外'


# ───────────────────────── 物差し ─────────────────────────
def stat(it, ks, spy=None):
    s = E.stats(it['yen'], ks)
    o = {'年率（円）': r2(s['cagr']), '最大下落（円）': r2(s['mdd'], 1)}
    if it.get('usd') is not None and all(m in it['usd'] for m in ks):
        o['年率（ドル）'] = r2(E.stats(it['usd'], ks)['cagr'])
    if spy is not None:
        o['S&P500 との差'] = round(o['年率（円）'] - spy, 2)
    return o


def xc(a, b, ks):
    if a['us'] != b['us']:
        return M.corr(ES.qret(a['yen'], ks), ES.qret(b['yen'], ks))
    return E.corr(a['yen'], b['yen'], ks)


def same_bet(it, five, ks):
    best = max(((xc(it, f, ks), t) for t, f in five.items()), key=lambda x: x[0])
    return f'{best[1]} {best[0]:.2f}' if best[0] >= SAME else None


def mix_series(parts, w, ks):
    tot = float(sum(w))
    return {m: sum(x / tot * p[m] for p, x in zip(parts, w)) for m in ks}


def seg_in(s, a, b):
    lo, hi = max(s['frm'], a), min(s['to'], b)
    return len(E.months(lo, hi)) if lo <= hi else 0


def share_at(c, m):
    """業種 c の月 m の市場に占める割合（bestfund_data.ind_share と同じ式・その月だけ）"""
    _, nf, sz = B.ind49()
    tot = sum(nf[n][m] * sz[n][m] for n in nf if nf[n].get(m) and sz[n].get(m) and nf[n][m] > 0 and sz[n][m] > 0)
    k, z = nf[c].get(m), sz[c].get(m)
    return k * z / tot if tot and k and z and k > 0 and z > 0 else 0.0


def label(it):
    return f"{it['key']} {it['nm']}"


def pre_note(it, a):
    """楽天の一覧の設定日が窓の始まりより後なら、それより前の値段は前身の本の記録（例: BBH・RTH・PPH の2011-12 より前は HOLDRS＝固定の籠）"""
    s = it.get('設定')
    if it.get('kind') == '米国ETF' and s and int(s[:4]) * 100 + int(s[5:7]) > a:
        return f'設定（{s}）より前の値段を含む＝前身の本の記録'
    return None


def row_of(it, st, extra=None):
    o = {'名札': it['key'], '名前': it['nm'], '種類': it['kind']}
    o.update(st)
    for k in ('設定', '費用（年・%）', '指数', '運用会社', '楽天で買える', 'NISA', '協会の10年の騰落率（%）'):
        if it.get(k) is not None:
            o[k] = it[k]
    if extra:
        o.update(extra)
    return o


# ───────────────────────── 本体 ─────────────────────────
def main():
    t0 = time.time()
    B.END = END
    g0 = M.get
    M.get = lambda url, name=None, max_age_days=30, tries=3: g0(url, name=name, max_age_days=max_age_days, tries=min(tries, 3))
    lv, fxc = B.fx()
    if max(lv) < END:
        raise SystemExit(f'為替が {max(lv)} までしか無い')
    res = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/past_winners.py',
           '注意': '参考・判定なし・配分は変えない。過去の成績で予想ではない。測り方はこの道具の頭の文（回す前にコミット f8bb851）',
           '回したあとの是正': '是正1 協会の分類が特殊型の投資信託を X1 に／是正2 東証の NASDAQ100 連動 ETF を X4 に（道具の頭の文）',
           '窓': {**{k: f'{a}〜{b}（{len(E.months(a, b))}か月）' for k, (a, b) in WIN.items()},
                 **{f'{k}（長い記録）': f'{a}〜{b}（{len(E.months(a, b))}か月）' for k, (a, b) in WINL.items()}},
           '為替（円/ドル・月末）': {str(k): lv[k] for k in (197610, 199610, 200611, 201610, 202609, 202610)}}

    # ── ① ETF
    uni, nrows, sha = EM.load(EM.ETFD, EM.ETFD_SHA)
    why = {d['t']: EM.why_out(d) for d in uni}
    for d in uni:
        if not why[d['t']] and not d['us'] and (d['idx'] or '').startswith('NASDAQ 100 TR'):
            why[d['t']] = 'X4 今の本と同じ指数（東証の NASDAQ100 連動）'
    need = [d for d in uni if not why[d['t']] or why[d['t']][:2] in ('X4', 'X5')]
    log(f'ETFD {nrows} 行 → 米国上場・東証 {len(uni)} 本・値段を取る {len(need)} 本')
    raw, err = EM.fetch([d['y'] for d in need])
    etf = {}
    for d in need:
        r = raw.get(d['y'])
        if not r:
            continue
        if d['us']:
            usd = {m: v for m, v in r.items() if m <= END}
            yen = {m: (1 + v) * (1 + fxc[m]) - 1 for m, v in usd.items() if m in fxc}
        else:
            usd, yen = None, {m: v for m, v in r.items() if m <= END}
        etf[d['t']] = {'key': d['t'], 'nm': d['ja'] or d['nm'], 'kind': '米国ETF' if d['us'] else '東証ETF', 'us': d['us'], 'yen': yen, 'usd': usd,
                       'y': d['y'], '設定': d['inception'], '費用（年・%）': d['er'], '指数': d['idx'], 'why': why[d['t']]}
    cnt = {}
    for d in uni:
        cnt[why[d['t']] or '測る'] = cnt.get(why[d['t']] or '測る', 0) + 1
    res['母集団'] = {'ETF': {'ETFD の行': nrows, 'sha256': sha[:16], '米国上場・東証': len(uni), '内訳': cnt, '値段が取れなかった本': len(err),
                           '値段が取れなかった本の名札': sorted(err)[:60]}}
    for t in FIVE + ['SPY']:
        if t not in etf or not EM.usable(etf[t]['yen'], E.months(*W10)):
            raise SystemExit(f'{t} の値段がそろわない')
    five = {t: etf[t] for t in FIVE}

    # ── ② 投資信託
    L = load_list()
    rows = L['rows']
    fo = {r['associFundCd']: fund_out(r) for r in rows}
    fcnt = {}
    for r in rows:
        k = fo[r['associFundCd']] or '測る候補'
        fcnt[k] = fcnt.get(k, 0) + 1
    elig = [r for r in rows if fo[r['associFundCd']] is None]
    pol = [r for r in rows if (fo[r['associFundCd']] or '').startswith('X5')]
    c20 = [r for r in elig if est(r) <= EST20]
    c10 = sorted([r for r in elig if est(r) <= EST10 and ra10(r) is not None], key=lambda r: -ra10(r))
    c10all = sorted([r for r in elig + pol if est(r) <= EST10 and ra10(r) is not None], key=lambda r: -ra10(r))
    polm = [r for r in c10all[:PRE10] if fo[r['associFundCd']]]
    need_f = {}
    for r in c20 + c10[:PRE10] + [r for r in c10 if rak(r)][:PRE10R] + polm:
        need_f[r['associFundCd']] = r
    log(f'投資信託 {len(rows)} 本 → 測る候補 {len(elig)}・20年で測る {len(c20)}・10年のふるい {len(c10)}・基準価額を取る {len(need_f)} 本')
    miss = fetch_navs(need_f)
    fund, split_log, chk_a, chk_set = {}, [], [], 0
    keep_cut = D.CUTOFF
    D.CUTOFF = END * 100 + 31
    for assoc, r in sorted(need_f.items()):
        p = os.path.join(NAVDIR, f'{assoc}.csv')
        if not os.path.exists(p):
            continue
        b = open(p, 'rb').read()
        nr = nav_rows(b)
        mon, sp = fund_monthly(nr)
        if not mon:
            continue
        nm = D.nfkc(r.get('fundNm'))
        if sp:
            split_log.append({'名前': nm, '協会コード': assoc, '戻した日': [f'{d} {s}' for d, s in sp][:6]})
        elif len(chk_a) < 400:
            ref = D.monthly_tr(D.parse_csv(b)[0])
            ks = sorted(set(ref) & set(mon))
            chk_a.append(max((abs(ref[k] - mon[k]) for k in ks), default=0.0))
            chk_set += set(ref) != set(mon)
        fund[assoc] = {'key': assoc, 'nm': nm + (f"（{D.nfkc(r.get('fundNkNm'))}）" if r.get('fundNkNm') else ''), 'kind': '投資信託', 'us': False,
                       'yen': mon, 'usd': None, '設定': (r.get('establishedDate') or '')[:10], '運用会社': D.nfkc(r.get('entrustCmpNm')),
                       '費用（年・%）': round(float(r['trustReward']) * 1.1, 4) if r.get('trustReward') not in (None, '') else None,
                       '楽天で買える': rak(r), 'NISA': nisa_of(r), '協会の10年の騰落率（%）': ra10(r), 'why': fo[assoc], 'isin': r.get('isinCd')}
    D.CUTOFF = keep_cut
    # 回帰の検査 (a)
    j1321 = B.jita_monthly('JP3027650005', '01311017')
    lib = D.Lib()
    b1321 = lib.csv('JP3027650005', '01311017')
    m1321, sp1321 = fund_monthly(nav_rows(b1321))
    k1321 = sorted(set(j1321) & set(m1321))
    d1321 = max(abs(j1321[k] - m1321[k]) for k in k1321)
    chk = {'(a) 基準価額の読み手': {'併合・分割なしの本の数': len(chk_a), 'nx_jpfunds_data.monthly_tr との差の最大': max(chk_a) if chk_a else None,
                                 '月の集合が違った本（最後の月が途中の本など）': chk_set,
                                 '1321（併合あり）で bestfund_data.jita_monthly との差の最大': d1321, '1321 で戻した日': [f'{d} {s}' for d, s in sp1321],
                                 '月の数（1321）': len(k1321)}}
    if (chk_a and max(chk_a) > 1e-9) or d1321 > 1e-9 or len(k1321) < 200:
        res['回帰の検査'] = chk
        json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
        raise SystemExit(f'回帰の検査 (a) が通らない: {chk}')
    log('回帰の検査 (a) ok', chk['(a) 基準価額の読み手'])
    res['母集団']['投資信託'] = {'全件': len(rows), '基準日': L.get('std'), '取得': L.get('fetched'), '内訳': fcnt,
                             '楽天証券で買える本（全件のうち）': sum(1 for r in rows if rak(r)),
                             '20年で測る本（設定 2006-11-30 以前）': len(c20), '10年のふるいの母数（設定 2016-10-31 以前・騰落率あり）': len(c10),
                             '基準価額を取った本': len(need_f) - len(miss), '基準価額が取れなかった本': len(miss),
                             '口数の併合・分割を戻した本': split_log,
                             'レバレッジ型として外した本のうち協会の10年の騰落率の上位20（名前だけ・測らない）': [
                                 f"{D.nfkc(r.get('fundNm'))}（{ra10(r)}%）" for r in sorted(
                                     [r for r in rows if (fo[r['associFundCd']] or '').startswith('X1') and ra10(r) is not None], key=lambda r: -ra10(r))[:20]],
                             '今の本と同じ指数として外した本（NASDAQ100）の数': sum(1 for r in rows if (fo[r['associFundCd']] or '').startswith('X4'))}

    # ── 窓ごとの並び（①②）
    daily_bad = {}
    for h, (a, b) in WIN.items():
        ks = E.months(a, b)
        spy = r2(E.stats(etf['SPY']['yen'], ks)['cagr']) if EM.usable(etf['SPY']['yen'], ks) else None
        pool = [it for it in list(etf.values()) + list(fund.values()) if EM.usable(it['yen'], ks)]
        broken = [label(it) for it in list(etf.values()) + list(fund.values())
                  if all(m in it['yen'] for m in ks) and not EM.usable(it['yen'], ks)]
        for it in pool:
            it['_st'] = stat(it, ks, spy)
        pool.sort(key=lambda it: -it['_st']['年率（円）'])
        main_l = [it for it in pool if not it['why'] and (it['kind'] != '投資信託' or it['楽天で買える'])]
        n = TOPN
        while True:
            top = main_l[:n]
            for it in top:
                if it['kind'] == '東証ETF' and (h, it['key']) not in daily_bad:
                    try:
                        daily_bad[(h, it['key'])] = EM.daily_shift(it['y'], a, b)
                    except Exception as e:  # noqa
                        daily_bad[(h, it['key'])] = {'取得失敗': str(e)[:80]}
            if any(daily_bad.get((h, it['key'])) for it in top):
                main_l = [it for it in main_l if not daily_bad.get((h, it['key']))]
                continue
            fams = []
            for it in top:
                for f in fams:
                    if xc(it, f[0], ks) >= SAME:
                        f.append(it)
                        break
                else:
                    fams.append([it])
            if len(fams) >= SHOW or n >= min(400, len(main_l)):
                break
            n += 40
        ks10 = E.months(*W10)
        show = []
        for i, f in enumerate(fams[:SHOW]):
            rep = f[0]
            show.append(row_of(rep, rep['_st'], {'順位': i + 1, '同じ賭け': same_bet(rep, five, ks10), '注': pre_note(rep, a), '家族の本の数': len(f),
                                                '家族のほかの本': [f"{label(x)}（{x['kind']}・{x['_st']['年率（円）']}%）" for x in f[1:7]]}))
        ref = []
        for t in ['SPY'] + FIVE:
            if EM.usable(etf[t]['yen'], ks):
                ref.append(row_of(etf[t], stat(etf[t], ks, spy)))
            else:
                ref.append({'名札': t, '名前': etf[t]['nm'], '測れない': 'この窓の月がそろわない'})
        if all(EM.usable(etf[t]['yen'], ks) for t in FIVE):
            for nmx, w in MIXES.items():
                mx = {'yen': mix_series([etf[t]['yen'] for t in FIVE], w, ks), 'usd': mix_series([etf[t]['usd'] for t in FIVE], w, ks)}
                ref.append({'名札': '—', '名前': nmx, **stat(mx, ks, spy)})
        ok_main = [it for it in pool if not it['why']]
        n_etf = [it for it in ok_main if it['kind'] != '投資信託']
        n_fund = [it for it in ok_main if it['kind'] == '投資信託']
        res[h] = {
            '窓': f'{a}〜{b}', 'S&P500（SPY・円の年率）': spy,
            '測れた本': {'ETF': len(n_etf), 'ETF のうち S&P500 を上回った本': sum(1 for it in n_etf if spy is not None and it['_st']['年率（円）'] > spy),
                      '投資信託': len(n_fund), '投資信託のうち楽天で買える本': sum(1 for it in n_fund if it['楽天で買える']),
                      '投資信託のうち S&P500 を上回った本': sum(1 for it in n_fund if spy is not None and it['_st']['年率（円）'] > spy)},
            '比べる相手': ref,
            '並び（ETF と楽天で買える投資信託・家族ごと・上位30）': show,
            '家族にまとめる前の上位の本数と内訳': {'本数': len(top), **{k: sum(1 for it in top if it['kind'] == k) for k in ('米国ETF', '東証ETF', '投資信託')}},
            '楽天で買えない投資信託の上位10': [row_of(it, it['_st']) for it in pool if not it['why'] and it['kind'] == '投資信託' and not it['楽天で買える']][:10],
            '方針で外した本の上位10（金・国債）': [row_of(it, it['_st'], {'外した理由': it['why']}) for it in pool if (it['why'] or '').startswith('X5')][:10],
            '壊れた値で使わなかった本': broken[:40],
            '日次の点検で外した東証の本': {k[1]: v for k, v in daily_bad.items() if k[0] == h and v},
        }
        log(f'{h}: 測れた ETF {len(n_etf)}・投資信託 {len(n_fund)}・S&P500 {spy}')

    # 回帰の検査 (b)
    ks = E.months(*W10)
    pairs = [(100 * (math.exp(sum(math.log1p(it['yen'][m]) for m in ks)) - 1), it['協会の10年の騰落率（%）'], it['nm'])
             for it in fund.values() if EM.usable(it['yen'], ks) and it.get('協会の10年の騰落率（%）') is not None]
    if pairs:
        def rank(xs):
            o = sorted(range(len(xs)), key=lambda i: xs[i])
            rk = [0] * len(xs)
            for p_, i in enumerate(o):
                rk[i] = p_
            return rk
        ra, rb = rank([p[0] for p in pairs]), rank([p[1] for p in pairs])
        dev = sorted(pairs, key=lambda p: -abs(math.log((100 + p[0]) / (100 + p[1]))))[:5]
        chk['(b) 投資信託の10年の累積と協会の騰落率'] = {'本数': len(pairs), '順位相関': round(M.corr(ra, rb), 4),
                                               'ずれの大きい5本（この道具・協会・名前）': [[round(p[0], 1), p[1], p[2]] for p in dev]}

    # ── ③ 長い記録
    fbt_er = (etf['FBT']['費用（年・%）'] or 0.54) / 100
    B.CHAINS['BIOTECH'] = [('actual', ('yahoo', 'FBT'), 'FBT'), ('proxy', ('french_ind', ['Drugs']), '代わり: French の Drugs（医薬品）')]
    B.JA['BIOTECH'] = 'バイオ（FBT）'
    B.ACTUAL_ER.setdefault('FBT', fbt_er)
    ch, fail = {}, {}
    for bet in B.CHAINS:
        try:
            r, segs, _ = B.build_chain(bet)
        except Exception as e:  # noqa
            fail[bet] = str(e)[:160]
            continue
        usd, jpy = (B.to_usd(r), r) if bet in B.JPY_NATIVE else (r, B.to_jpy(r))
        ch[bet] = {'key': bet, 'nm': B.JA.get(bet, bet), 'us': True, 'usd': usd, 'yen': jpy, 'segs': [s for s in segs if s.get('months')]}
    have = {d['t'] for d in uni}
    ret49 = B.ind49()[0]
    for h, (a, b) in WINL.items():
        ks = E.months(a, b)
        ksc = ks[-120:]
        sp = ch.get('SP500')
        spy = r2(E.stats(sp['yen'], ks)['cagr']) if sp and all(m in sp['yen'] for m in ks) else None
        fiveb = {t: ch[t] for t in FIVE_BET if t in ch and all(m in ch[t]['yen'] for m in ks)}
        rows_a, ref, no = [], [], []
        for bet, it in ch.items():
            if not all(m in it['yen'] for m in ks):
                no.append(f"{it['nm']}（{min(it['yen']) if it['yen'] else '—'}〜）")
                continue
            real = sum(seg_in(s, a, b) for s in it['segs'] if s['kind'] in ('actual', 'index'))
            o = {'賭け': it['nm'], **stat(it, ks, spy), '実物・指数の月の割合': round(real / len(ks), 2),
                 'つないだもの': '／'.join(f"{s['label']}（{max(s['frm'], a)}〜{min(s['to'], b)}）" for s in it['segs'] if s['to'] >= a and s['frm'] <= b)}
            v = B.VEH.get(bet) or {}
            names = [x[0] for x in (v.get('tsumitate'), v.get('growth')) if x] + [x[0] for x in (v.get('alt') or [])]
            o['今買える本（bestfund の表）'] = list(dict.fromkeys(names))[:4]
            if bet == 'GOLD':
                o['外した理由'] = 'X5 方針で外す（金）'
                ref.append(o)
            elif bet in FIVE_BET or bet == 'SP500':
                o['印'] = '比べる相手（S&P500）' if bet == 'SP500' else '今の組み合わせ'
                ref.append(o)
            else:
                if fiveb:
                    best = max(((E.corr(it['yen'], f['yen'], ksc), t) for t, f in fiveb.items()), key=lambda x: x[0])
                    o['同じ賭け'] = f'{B.JA.get(best[1], best[1])} {best[0]:.2f}' if best[0] >= SAME else None
                rows_a.append(o)
        if len(fiveb) == len(FIVE_BET):
            for nmx, w in MIXES.items():
                mx = {'yen': mix_series([ch[t]['yen'] for t in FIVE_BET], w, ks), 'usd': mix_series([ch[t]['usd'] for t in FIVE_BET], w, ks)}
                ref.append({'賭け': nmx + '・つなぎ', **stat(mx, ks, spy)})
        rows_a.sort(key=lambda o: -o['年率（円）'])
        rows_b, no_b = [], []
        for c in ret49:
            s = B.french_ind([c])
            sh0 = share_at(c, a)
            if sh0 < MIN_SHARE or not all(m in s for m in ks):
                no_b.append(f"{IND_JA.get(c, c)}（{'窓の最初の月に市場の0.25%未満' if sh0 < MIN_SHARE else '月がそろわない'}）")
                continue
            it = {'usd': s, 'yen': B.to_jpy(s)}
            o = {'業種': IND_JA.get(c, c), '名札': c, **stat(it, ks, spy), '窓の最初の月の市場に占める割合（%）': r2(sh0),
                 '今買える本（楽天の ETF 一覧にある本・中身は複数の業種の混ぜ物）': [t for t in IC.VEHICLE.get(c, []) if t in have]}
            if c in IND_NOW:
                o['印'] = IND_NOW[c]
            rows_b.append(o)
        rows_b.sort(key=lambda o: -o['年率（円）'])
        cut = {'30年': 19961031, '50年': 19761031}[h]
        old = [r for r in rows if est(r) <= cut and fo[r['associFundCd']] in (None,) ]
        oldr = [r for r in old if rak(r)]
        res[f'{h}（長い記録）'] = {
            '窓': f'{a}〜{b}', 'S&P500（つなぎ・円の年率）': spy, '比べる相手': ref,
            '賭けのつなぎ（年率の高い順）': rows_a, '窓がそろわない賭け': no,
            'French の49業種（年率の高い順）': rows_b, '測れない業種': no_b,
            '日本の投資信託': {'この窓より前に設定された本（外すものを除く）': len(old), 'うち楽天で買える本': len(oldr),
                          '測れない理由': '投信総合検索ライブラリーの基準価額の記録は直近20年ぶん（2006-11-24〜）しか無い',
                          '楽天で買える本の名前（設定の古い順・40本まで）': [f"{(r.get('establishedDate') or '')[:10]} {D.nfkc(r.get('fundNm'))}（{D.nfkc(r.get('entrustCmpNm'))}）"
                                                               for r in sorted(oldr, key=est)[:40]]},
        }
        log(f'{h}（長い記録）: 賭け {len(rows_a)}・業種 {len(rows_b)}・S&P500 {spy}')
    res['つなぎが作れなかった賭け'] = fail
    # 回帰の検査 (c)
    ks30 = E.months(*WIN['30年'])
    sp = ch.get('SP500')
    if sp and all(m in sp['usd'] for m in ks30) and EM.usable(etf['SPY']['yen'], ks30):
        chk['(c) SPY の30年（ドル）と S&P500 のつなぎ'] = {'SPY': r2(E.stats(etf['SPY']['usd'], ks30)['cagr']), 'つなぎ': r2(E.stats(sp['usd'], ks30)['cagr'])}
    res['回帰の検査'] = chk
    res['秒'] = round(time.time() - t0)
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)

    # ── 画面
    for h in WIN:
        o = res[h]
        print(f"\n■ {h}（{o['窓']}）S&P500 {o['S&P500（SPY・円の年率）']}%/年・測れた {o['測れた本']}")
        for x in o['比べる相手']:
            print('   相手', x.get('名札'), str(x.get('名前'))[:34], x.get('年率（円）'), x.get('年率（ドル）'), x.get('最大下落（円）'), x.get('測れない', ''))
        for x in o['並び（ETF と楽天で買える投資信託・家族ごと・上位30）']:
            print(f"  {x['順位']:>2} {x['名札']:<9} {x['名前'][:30]:<30} {x['種類']:<5} 円{x['年率（円）']:>6} ドル{str(x.get('年率（ドル）', '—')):>6} 下落{x['最大下落（円）']:>6}"
                  f" 差{x.get('S&P500 との差', 0):+6.2f} 家族{x['家族の本の数']:>2} {x.get('同じ賭け') or ''} {x.get('注') or ''}")
        print('  楽天で買えない投資信託:', [(x['名前'][:24], x['年率（円）']) for x in o['楽天で買えない投資信託の上位10']][:6])
        print('  方針で外した本:', [(x['名札'], x['名前'][:20], x['年率（円）']) for x in o['方針で外した本の上位10（金・国債）']][:6])
    for h in WINL:
        o = res[f'{h}（長い記録）']
        print(f"\n■ {h}（長い記録 {o['窓']}）S&P500 {o['S&P500（つなぎ・円の年率）']}%/年")
        for x in o['比べる相手']:
            print('   相手', x['賭け'][:30], x.get('年率（円）'), x.get('年率（ドル）'), x.get('実物・指数の月の割合'))
        for x in o['賭けのつなぎ（年率の高い順）'][:20]:
            print(f"  賭け {x['賭け'][:22]:<22} 円{x['年率（円）']:>6} ドル{str(x.get('年率（ドル）', '—')):>6} 下落{x['最大下落（円）']:>6} 実物{x['実物・指数の月の割合']} {x.get('同じ賭け') or ''}")
        for x in o['French の49業種（年率の高い順）'][:20]:
            print(f"  業種 {x['業種'][:14]:<14} 円{x['年率（円）']:>6} ドル{str(x.get('年率（ドル）', '—')):>6} 下落{x['最大下落（円）']:>6} {x.get('印', '')} {x['今買える本（楽天の ETF 一覧にある本・中身は複数の業種の混ぜ物）']}")
    print('\n回帰の検査', json.dumps(chk, ensure_ascii=False)[:900])
    print('秒', res['秒'], '→', os.path.relpath(OUT, BASE))


if __name__ == '__main__':
    main()
