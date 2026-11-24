#!/usr/bin/env python3
"""
単体の ETF を多角的に採点して並べる（etf_scorecard・参考・判定なし・配分は不変）

2026-11-24 ユーザー「単体のETFで最も優秀と評価するものをランキングでだしてもちろん過去の数字だけではなく
そのETFの性質だったり多角的にあなたが評価してトップ10 までだして。」

──── 回す前に固定したこと（この頭の文と下の定数。コミットしてから回す）────
対象（26本）: best15_check の物差しの33本（unx_assets の行・2000-09〜の系列がそろう本）から、
  金（GLDM・GDX）と国債（EDV・TLT・TIP・2621）＝方針（2026-11-04「金国債はいりない」）と、
  銀（SLV）＝株ではなく事業の利益で複利しない（未来の世界と業種の基礎率は株のための物差し）を外した残り。
  測っていない本（理由は NOT_MEASURED）: VIG・VYM・RSP・GRID・SHLD・MTUM・QUAL・VNQ。
  同じ賭けの器は1本で代表する（NASDAQ100＝QQQM〔QQQ・iFreeNEXT・QNDX も同じ指数〕・S&P500＝VOO〔SPY・IVV も同じ指数〕）。

5つの軸と物差し（向きをそろえて 0〜100 点。数の物差しは26本の中の百分位〔同点は平均〕）:
 ① 未来の見込み 30%（未来の3つの世界＝B 100年の平均・C JPM・D アナリスト。π は B・C・D だけで割り直す）
    F1 期待の年率（元）30 ／ F2 期待の年率（業種の基礎率を当てる・best15r の FastBR の主の値）40
    ／ F3 年15%以上の確率（未来の世界・業種の基礎率）30
    業種の基礎率は米国の17本だけ（BR.POOL）。米国外の本は当てられないので F2・F3 は元の未来の世界の値（印を付ける）
 ② 過去の実績 15%（費用と取り戻せない外国税を引いた後・ドル）
    P1 A1＝2000-09〜 26年の年率 35 ／ P2 A2＝2011-10〜 15年の年率 15
    ／ P3 転がる20年の毎月の積立の年率の中央 30 ／ P4 同・最悪 20（five_mix_ndx の realized・74窓）
 ③ 100年の頑健さ 10%（best15 の Cent＝1966〜1996年に始めた30年の毎月の積立の米国市場との比・31窓）
    H1 中央 50 ／ H2 最悪 50。NASDAQ100 は入れ替えを数えた V1（ndx_recon_check の写し）。
    MOAT は行の代わりと同じ French の BIG HiOP（大型×高収益）を写しにする（この道具の中だけで足す）。
    写しが無い本（米国外の8本）は市場並み＝1.0 と置き、印を付ける
 ④ 下げへの耐性 20%
    D1 円の最大下落（A1 の窓）35 ／ D2 年5%未満の確率（5つの世界）20
    ／ D3 同（未来の世界・業種の基礎率。米国外は元の未来の世界）20
    ／ D4 円で高値を取り戻すまでの最長の年数（A1 の窓・終わりまで戻らなければ終わりまで・印）25
 ⑤ ETF の性質 25%（数ではなく作りを見る＝私の判断を含む。点の決め方はここに固定）
    S1 指数の自己更新（経済の主役が入れ替わっても指数の決まりで乗り換えられるか・広さ）35 ＝ 下の S1 の表
    S2 分散（上位10社の比率・低いほど良い）25: 100×clip((0.80−上位10)/0.70, 0, 1)
       出どころ: リポジトリの保有（out/etf_profiles.json・out/etf_forward_profiles.json・bestpf_ext の AV の写し・
       sp500_compare の VOO の上位10）。載っている重みの合計が95%未満の一覧は使わない（VT だけは AV の上位41社の一覧＝上位10は読める）。
       足りない本は TOP10_EXT（stockanalysis.com の保有ページ・2026-11-24 に読んだ）。TOPIX は MSCI Japan（EWJ）で代える。
       EPI は保有の72.7%が子会社1行で中身の上位10が取れない＝ほかの25本の S2 の中央値と置き、印を付ける
    S3 費用（経費率＋取り戻せない配当の外国税・unx_assets の行の値）15: 100×clip(1−費用/0.80%, 0, 1)
       ⚠ 費用はリターンの数字にも入っている＝確実に引かれる唯一の数字なので、性質の軸でもう一度数える（承知の二重）
    S4 自分の記録の長さ 15: 100×min(年数, 25)/25（OWN_START。同じ指数の古い器・同じファンドの別の口は数える／別の指数の代わりは数えない）
    S5 規模 10: 純資産 100億ドル以上 100／10〜100億 80／3〜10億 50／それ未満 20

総合＝5つの軸の重み付きの平均。順位は総合の大きい順。

確かめ（感度・回す前に固定）:
 K1 5つの軸を同じ重み（各20%）
 K2 過去寄り（過去 35・100年 10・未来 20・下げ 15・性質 20）
 K3 未来寄り（未来 45・性質 20・下げ 15・過去 10・100年 10）
 K4 守り寄り（下げ 35・性質 25・未来 20・過去 10・100年 10）
 K5 性質の軸（私の判断を含む）を外す（数の4軸だけで割り直す）
 K6 S1（自己更新の判断）だけを外す（性質の軸の中で割り直す）
 K7 100年の軸を外す（写しの無い本に 1.0 を置かない）
 K8 数の物差しを百分位でなく最小〜最大で 0〜100 にする
 K9 NASDAQ100 の100年を V0（業種を固定した写し）にする
 読み方: 主の上位10を答えにし、9つの確かめで上位10に残った回数と順位の幅を並べる（確かめで答えは変えない）。

回帰の検査（外れれば止める）:
 (a) QQQM・SMH・ITA・XLV・VBR・VOO の1本ずつの値（元の物差しの P15π・平均・5%未満・最大下落・ぶれ／基礎率の P15π・平均・5%未満／
     100年 V0 の中央・最悪／実績の割合・中央・最悪）が five_mix_ndx の ①1本ずつ と表示の桁で一致
     ⚠ 回したあとの是正（1回目の実行で外れた・採点の決まりは変えていない）: 最初は out/five_mix_ndx_check.json（2026-11-01）と比べたが、
     その後 Ken French の表を 2026-11-22 に取り直した（49業種は今 2026-09 まで）ので世界B・C が少し動き、元の物差し・基礎率の値が
     小数第2位で外れた（A1・A2・100年・実績・最大下落・ぶれは一致）。→ five_mix_ndx_check を今日のデータで一時ファイルへ回し
     （今の形の照合 check_now だけ外す＝①は今の形を使わない）、その ①と比べる形に直した。11-01 の出力とのずれは参考に残す
 (b) 未来の世界だけの π で回した Fast の平均が、行の B・C と D の世界から手で作った値と一致
 (c) QQQM の100年 V0・V1 が out/ndx_recon_check.json の NASDAQ100だけ_版ごと と一致
 (d) 業種の基礎率を当てない FastBR（a=0）が、未来の世界だけの Fast と同じ値（米国外の本を同じ道で測っている確かめ）
 (e) 対象が26本・行と系列と表の定数がそろう・点に欠けが無い
"""
import contextlib, copy, io, json, os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
OUT = os.path.join(BASE, 'out', 'etf_scorecard.json')
REF5 = os.path.join(BASE, 'out', 'five_mix_ndx_check.json')
REFN = os.path.join(BASE, 'out', 'ndx_recon_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
import best15c_check as BCc  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402
import ndx_recon_check as NR  # noqa: E402

END = 202611   # 記録の長さを数える月

EXCLUDE = {
    'GDX': '金鉱株（方針・2026-11-04「金国債はいりない」）', 'GLDM': '金（方針）',
    'EDV': '米国債（方針）', 'TLT': '米国債（方針）', 'TIP': '米国の物価連動国債（方針）', 'UST_HEDGED_2621': '円ヘッジの米国債（方針）',
    'SLV': '銀＝株ではなく事業の利益で複利しない（未来の世界と業種の基礎率は株のための物差し）',
}
NOT_MEASURED = {
    'VIG': '主の窓（2000-09〜）に自分の系列がそろわない（2006-06〜・etf_add と同じ扱い）',
    'VYM': '主の窓に自分の系列がそろわない（2006-12〜）', 'RSP': '主の窓に自分の系列がそろわない（2003-06〜）',
    'GRID': '主の窓に自分の系列がそろわない（2009-12〜）', 'SHLD': '自分の記録が3年（2023-09〜）',
    'MTUM': '楽天で買えない', 'QUAL': '楽天で買えない', 'VNQ': '楽天の一覧に無い',
}

AXES = {'未来': 0.30, '過去': 0.15, '百年': 0.10, '下げ': 0.20, '性質': 0.25}
SUB = {
    '未来': {'F1': 0.30, 'F2': 0.40, 'F3': 0.30},
    '過去': {'P1': 0.35, 'P2': 0.15, 'P3': 0.30, 'P4': 0.20},
    '百年': {'H1': 0.50, 'H2': 0.50},
    '下げ': {'D1': 0.35, 'D2': 0.20, 'D3': 0.20, 'D4': 0.25},
    '性質': {'S1': 0.35, 'S2': 0.25, 'S3': 0.15, 'S4': 0.15, 'S5': 0.10},
}
# 数の物差しの向き（+1＝大きいほど良い・−1＝小さいほど良い）。S は絶対の点（下の式）
DIR = {'F1': 1, 'F2': 1, 'F3': 1, 'P1': 1, 'P2': 1, 'P3': 1, 'P4': 1, 'H1': 1, 'H2': 1,
       'D1': 1, 'D2': -1, 'D3': -1, 'D4': -1}
SUBJA = {'F1': '期待の年率（元）', 'F2': '期待の年率（業種の基礎率）', 'F3': '年15%以上の確率（未来・基礎率）',
         'P1': 'A1 26年の年率', 'P2': 'A2 15年の年率', 'P3': '20年積立の年率の中央', 'P4': '20年積立の年率の最悪',
         'H1': '100年 30年積立の市場との比の中央', 'H2': '同・最悪',
         'D1': '円の最大下落', 'D2': '年5%未満の確率（5つの世界）', 'D3': '年5%未満の確率（未来・基礎率）', 'D4': '円で高値を取り戻すまでの最長の年数',
         'S1': '指数の自己更新', 'S2': '分散（上位10社）', 'S3': '費用', 'S4': '記録の長さ', 'S5': '規模'}

# S1 指数の自己更新（経済の主役が入れ替わっても指数の決まりで乗り換えられるか・広さ）＝私の判断
S1 = {
    'VT': (100, '全世界の時価総額（国も業種も指数が自動で入れ替える）'),
    'VOO': (90, '米国の大型株全体の時価総額（業種は自動で入れ替わる・国は米国だけ）'),
    'VEA': (85, '米国外の先進国全体（複数の国・業種は自動・米国を含まない）'),
    'VWO': (85, '新興国全体（複数の国・業種は自動）'),
    'VUG': (75, '米国の大型グロース（業種を固定しない型の決まりで入れ替わる）'),
    'VTV': (75, '米国の大型バリュー（業種を固定しない型の決まり）'),
    'VBR': (75, '米国の小型バリュー（業種を固定しない型の決まり）'),
    'IJR': (75, '米国の小型（S&P600・黒字の条件つき・業種を固定しない）'),
    'QQQM': (70, 'NASDAQ100（毎年入れ替え業種を固定しないが、金融を除き NASDAQ 上場だけ）'),
    'TOPIX': (70, '日本の市場全体（1つの国・業種は自動）'),
    'EWY': (70, '韓国の市場（1つの国）'),
    'EPI_LONG': (70, 'インドの市場（1つの国・利益で重み付け）'),
    'MOAT': (60, '広い中から決まりで選ぶ（ワイドモート＋割安・約50社）'),
    'PXF': (60, '広い中から決まりで重み付ける（米国外の先進国・売上や配当などのファンダメンタル）'),
    'DEM': (60, '広い中から決まりで選ぶ（新興国の高配当）'),
    'XLK': (45, '1つの広い業種（情報技術）'), 'XLV': (45, '1つの広い業種（ヘルスケア）'),
    'XLI': (45, '1つの広い業種（資本財）'), 'XLY': (45, '1つの広い業種（一般消費財）'),
    'XLF': (45, '1つの広い業種（金融）'), 'XLP': (45, '1つの広い業種（生活必需品）'),
    'SMH': (35, '1つの狭い業種（半導体）'), 'ITA': (35, '1つの狭い業種（航空・防衛）'),
    'FBT': (35, '1つの狭い業種（バイオテクノロジー）'), 'XLE': (35, '1つの狭い業種（エネルギー）'),
    'XLU': (35, '1つの狭い業種（公益・電力）'),
}

# S4 自分の記録の始まり（YYYYMM・同じ指数の古い器と同じファンドの別の口は数える）
OWN_START = {
    'QQQM': (199903, 'QQQ（1999-03・同じ NASDAQ-100）'), 'VOO': (199301, 'SPY（1993-01・同じ S&P500）'),
    'SMH': (201112, '今の SMH（2011-12・それより前は HOLDRS の固定の籠＝別の決まり）'),
    'ITA': (200605, 'ITA'), 'FBT': (200606, 'FBT'), 'IJR': (200005, 'IJR'), 'MOAT': (201204, 'MOAT'),
    'XLK': (199812, 'XLK'), 'XLV': (199812, 'XLV'), 'XLP': (199812, 'XLP'), 'XLU': (199812, 'XLU'),
    'XLE': (199812, 'XLE'), 'XLF': (199812, 'XLF'), 'XLI': (199812, 'XLI'), 'XLY': (199812, 'XLY'),
    'VUG': (199211, '同じファンドの投資家口 VIGRX（1992-11）'), 'VTV': (199211, '同じファンドの投資家口 VIVAX（1992-11）'),
    'VBR': (199805, '同じファンドの投資家口 VISVX（1998-05）'), 'VEA': (199909, '同じファンドの別の口 VTMGX（1999-09）'),
    'VWO': (199406, '同じファンドの投資家口 VEIEX（1994-06）'), 'VT': (200806, 'VT（2008-06）'),
    'PXF': (200706, 'PXF'), 'DEM': (200707, 'DEM'), 'EPI_LONG': (200802, 'EPI（2008-02・それより前の A1 は JKP の代わり）'),
    'EWY': (200005, 'EWY'), 'TOPIX': (200107, '東証の 1306（2001-07）'),
}

# S2 の外の出どころ（stockanalysis.com の保有ページ＝Finnhub の保有・2026-11-24 に読んだ）
SA = 'https://stockanalysis.com/etf/{}/holdings/'
TOP10_EXT = {
    'VEA': dict(top10=0.1299, top1=['Samsung Electronics', 0.0238], n=3936, asof='2026-10-31', url=SA.format('vea'), note='上位10に担保の行 1.11% を含む'),
    'VWO': dict(top10=0.2874, top1=['TSMC', 0.1533], n=5091, asof='2026-10-31', url=SA.format('vwo'), note='上位10に現金・担保の行 2.93%・0.91% を含む'),
    'EWY': dict(top10=0.5845, top1=['Samsung Electronics', 0.2204], n=81, asof='2026-11-20', url=SA.format('ewy'), note=''),
    'PXF': dict(top10=0.1351, top1=['Samsung Electronics', 0.0276], n=1043, asof='2026-11-18', url=SA.format('pxf'), note=''),
    'DEM': dict(top10=0.2296, top1=['China Construction Bank', 0.0438], n=578, asof='2026-11-20', url=SA.format('dem'), note=''),
    'VTV': dict(top10=0.2309, top1=['Micron Technology', 0.0360], n=309, asof='2026-10-31', url=SA.format('vtv'),
                note='リポジトリの一覧は重みの75%しか無い'),
    'IJR': dict(top10=0.0617, top1=['Paycom Software', 0.0057], n=613, asof='2026-11-20', url=SA.format('ijr'),
                note='上位10に現金の器 1.49% を含む・リポジトリの一覧は重みの86%しか無い'),
    'TOPIX': dict(top10=0.2973, top1=['Mitsubishi UFJ Financial Group', 0.0432], n=173, asof='2026-11-20', url=SA.format('ewj'),
                  note='TOPIX（1306）の保有は読めなかった（野村の一覧は取得を拒まれた）＝同じ日本株の MSCI Japan（EWJ・173社）で代えた。'
                       'TOPIX（約1,700社）はこれより分散している（上位10社の比率は低い側）'),
}
TOP10_NONE = {'EPI_LONG': 'EPI は保有の72.7%が子会社（WT India Investment Portfolio）1行で、中身まで見た上位10社が取れない'}
TOP10_FULL = 0.95          # リポジトリの一覧を使う線（載っている重みの合計）
TOP10_PARTIAL_OK = {'VT': 'AV の上位41社の一覧（重みの30%）＝重みの大きい順なので上位10は読める'}

AUM_EXT = {'EWY': (22.3e9, 'Alpha Vantage ETF_PROFILE（2026-11-20）')}
AUM_JPY = {'TOPIX': (3.206233e13, '1306 の純資産 320,623.3億円（nextfunds.jp・2026-11-24）')}

# 確かめ
KS = {
    'K1 5つの軸を同じ重み': dict(axes={'未来': .2, '過去': .2, '百年': .2, '下げ': .2, '性質': .2}),
    'K2 過去寄り': dict(axes={'未来': .20, '過去': .35, '百年': .10, '下げ': .15, '性質': .20}),
    'K3 未来寄り': dict(axes={'未来': .45, '過去': .10, '百年': .10, '下げ': .15, '性質': .20}),
    'K4 守り寄り': dict(axes={'未来': .20, '過去': .10, '百年': .10, '下げ': .35, '性質': .25}),
    'K5 性質の軸を外す': dict(axes={'未来': .30, '過去': .15, '百年': .10, '下げ': .20, '性質': 0.0}),
    'K6 S1（自己更新の判断）を外す': dict(sub0={'S1'}),
    'K7 100年の軸を外す': dict(axes={'未来': .30, '過去': .15, '百年': 0.0, '下げ': .20, '性質': .25}),
    'K8 最小〜最大で点にする': dict(scale='minmax'),
    'K9 NASDAQ100 の100年を V0': dict(cent='V0'),
}


def log(*a):
    print('[etf_scorecard]', *a, flush=True)


def pctile(x, d):
    """百分位（0〜100・同点は平均）。d=+1 大きいほど良い・−1 小さいほど良い"""
    x = np.asarray(x, dtype=np.float64) * d
    n = len(x)
    out = np.empty(n)
    for i in range(n):
        lt = np.sum(x < x[i] - 1e-12)
        eq = np.sum(np.abs(x - x[i]) <= 1e-12)
        out[i] = (lt + 0.5 * (eq - 1)) / (n - 1) * 100
    return out


def minmax(x, d):
    x = np.asarray(x, dtype=np.float64) * d
    lo, hi = float(x.min()), float(x.max())
    return (x - lo) / (hi - lo) * 100 if hi > lo else np.full(len(x), 50.0)


def path_yen(rets):
    """円の月次 → 最大下落・高値を取り戻すまでの最長の月数・終わりにまだ水没しているか"""
    v = np.cumprod(1 + np.asarray(rets, dtype=np.float64))
    peak = np.maximum.accumulate(np.concatenate([[1.0], v]))[1:]
    dd = v / peak - 1
    under = v < peak * (1 - 1e-12)
    best = cur = 0
    for u in under:
        cur = cur + 1 if u else 0
        best = max(best, cur)
    return float(dd.min()), best, bool(under[-1])


def months_between(a, b):
    return (b // 100 - a // 100) * 12 + (b % 100 - a % 100)


def top10_of(h):
    ws = sorted([float(w) for _, w in h if w not in (None, 'n/a') and float(w) > 0], reverse=True)
    return sum(ws[:10]), sum(ws)


def ref_five_mix_today():
    """five_mix_ndx_check を今日のデータで一時ファイルへ回し、①1本ずつを返す（正本の out/five_mix_ndx_check.json は書かない）"""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        run = os.path.join(td, 'run_f5.py')
        dst = os.path.join(td, 'five_mix_ndx_today.json')
        open(run, 'w').write(
            'import sys\n'
            f'sys.path.insert(0, {HERE!r})\n'
            'import five_mix_ndx_check as F\n'
            'F.OUT = sys.argv[1]\n'
            'F.B.check_now = lambda: None\n'
            'F.main()\n')
        p = subprocess.run([sys.executable, run, dst], capture_output=True, text=True, cwd=BASE)
        if p.returncode != 0 or not os.path.exists(dst):
            raise SystemExit(f'five_mix_ndx_check を今日のデータで回せない: {p.stdout[-800:]} {p.stderr[-800:]}')
        return json.load(open(dst))['①1本ずつ']


def main():
    t0 = time.time()
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    import sp500_compare as SPC
    import mw_common as M
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    pool33 = B.pool_list()
    P = [c for c in pool33 if c not in EXCLUDE]
    n = len(P)
    miss = [c for c in P if c not in rows or c not in chains or c not in S1 or c not in OWN_START]
    if n != 26 or miss or set(EXCLUDE) - set(pool33):
        raise SystemExit(f'対象がそろわない: n={n} miss={miss} 外す本で物差しに無い本={set(EXCLUDE) - set(pool33)}')

    # ── 100年の写し ──
    C = B.century_extend(U)
    hop = M.french_series('6_Portfolios_ME_OP_2x3', want='Average Value Weighted Returns')['BIG HiOP']
    C['parts']['MOAT'] = dict(hop)
    U.MONTHLY_OK.add('MOAT')
    qs, _ = NR.build_copies(C)
    cents = {v: BCc.CentP(U, P, {**C['parts'], 'QQQM': qs[v]}) for v in ('V0', 'V1')}

    # ── 速い評価（1本ずつ） ──
    W = np.eye(n) * 100.0
    fast = B.Fast(U, rows, chains, P)
    fastf = copy.copy(fast)
    fastf.pi = dict(fast.fwd)
    e, ef = fast.eval(W), fastf.eval(W)
    rz = realized(W, fast)
    cc = {v: cents[v].eval(W) for v in cents}

    PB = list(BR.POOL)
    fast18 = B.Fast(U, rows, chains, PB)
    fbr = BR.FastBR(fast18)
    st = BR.industry_state()
    vec, vchk = BR.industry_vectors(U, rows)
    adj = {k: BR.adj_vector(vec, st, rt, PB)[0] for k, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']
    inB = [c for c in P if c in PB]
    WB = np.array([[100.0 if x == c else 0.0 for x in PB] for c in inB])
    bs = fbr.eval(WB, a0)
    bz = fbr.eval(WB, np.zeros(len(PB)))
    bidx = {c: i for i, c in enumerate(inB)}

    # ── 円の道（A1 の窓） ──
    ch_jpy, _ = U.jpy_chains(chains)
    wa, wb = BC.WINDOWS[UC.W_CRASH]
    k1 = U.R.months(wa, wb)
    if len(k1) != fast.T1:
        raise SystemExit(f'A1 の窓の月数が Fast と違う: {len(k1)} vs {fast.T1}')
    yen = {}
    for c in P:
        lack = [m for m in k1 if m not in ch_jpy[c]]
        if lack:
            raise SystemExit(f'円の系列に欠けた月: {c} {lack[:3]}')
        mdd, uw, still = path_yen([ch_jpy[c][m] for m in k1])
        yen[c] = dict(mdd=mdd, uw_m=uw, still=still)

    # ── 中身・規模 ──
    prof = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json')))['etfs']
    fprof = json.load(open(os.path.join(BASE, 'out', 'etf_forward_profiles.json')))['etfs']
    av = U.X.av_profiles()
    fx = json.load(open(os.path.join(BASE, 'out', 'dashboard.json')))['fx']['USDJPY']
    t10, t10src, aum, aumsrc = {}, {}, {}, {}
    for c in P:
        key = 'EPI' if c == 'EPI_LONG' else c
        h = None
        if key in prof and prof[key].get('h'):
            h, src = prof[key]['h'], f'out/etf_profiles.json（{prof[key].get("asof")}）'
        elif key in fprof and fprof[key].get('holdings'):
            h, src = fprof[key]['holdings'], f'out/etf_forward_profiles.json（{fprof[key].get("last_updated")}）'
        elif key in av and av[key].get('holdings'):
            hh = av[key]['holdings']
            h = [(x[0], x[1]) if isinstance(x, (list, tuple)) else (x.get('symbol'), x.get('weight')) for x in hh]
            src = f'bestpf_ext の AV の写し（{av[key].get("last_updated")}）'
        if c in TOP10_EXT:
            x = TOP10_EXT[c]
            t10[c], t10src[c] = x['top10'], f'{x["url"]}（{x["asof"]}）' + (f'・{x["note"]}' if x['note'] else '')
        elif c == 'VOO':
            t10[c], t10src[c] = sum(SPC.VOO_TOP10.values()) / 100, f'sp500_compare.VOO_TOP10（{SPC.VOO_ASOF}）'
        elif c in TOP10_NONE:
            t10[c], t10src[c] = None, TOP10_NONE[c]
        elif h:
            tt, tot = top10_of(h)
            if tot < TOP10_FULL and c not in TOP10_PARTIAL_OK:
                raise SystemExit(f'{c}: 一覧の重みが {tot:.2f} しか無い（外の出どころを TOP10_EXT に足す）')
            t10[c], t10src[c] = tt, src + (f'・{TOP10_PARTIAL_OK[c]}' if c in TOP10_PARTIAL_OK else '')
        else:
            raise SystemExit(f'{c}: 上位10社の出どころが無い')
        if c in AUM_EXT:
            aum[c], aumsrc[c] = AUM_EXT[c]
        elif c in AUM_JPY:
            aum[c], aumsrc[c] = AUM_JPY[c][0] / fx, AUM_JPY[c][1] + f'÷ドル円 {fx}'
        elif key in prof and prof[key].get('aum'):
            aum[c], aumsrc[c] = float(prof[key]['aum']), 'out/etf_profiles.json'
        elif key in fprof and fprof[key].get('net_assets'):
            aum[c], aumsrc[c] = float(fprof[key]['net_assets']), 'out/etf_forward_profiles.json'
        elif key in av and av[key].get('net_assets'):
            aum[c], aumsrc[c] = float(av[key]['net_assets']), 'bestpf_ext の AV の写し'
        else:
            raise SystemExit(f'{c}: 純資産の出どころが無い')

    # ── 生の値 ──
    raw = {}
    for i, c in enumerate(P):
        rw = rows[c]
        hasB = c in bidx
        j = bidx.get(c)
        d = dict(
            F1=float(ef['mean_pi'][i]), F2=float(bs['mean_pi'][j]) if hasB else float(ef['mean_pi'][i]),
            F3=float(bs['P15'][j]) if hasB else float(ef['P15'][i]),
            P1=float(rw['A1']), P2=float(rw['A2']), P3=float(rz['med'][i]), P4=float(rz['worst'][i]),
            D1=yen[c]['mdd'], D2=float(e['P5'][i]), D3=float(bs['P5'][j]) if hasB else float(ef['P5'][i]),
            D4=yen[c]['uw_m'] / 12.0,
        )
        for v in ('V0', 'V1'):
            ok = bool(cents[v].has[i])
            d[f'H1_{v}'] = float(cc[v]['c30med'][i]) if ok else 1.0
            d[f'H2_{v}'] = float(cc[v]['c30min'][i]) if ok else 1.0
        cost = float(rw['er_vehicle']) + float(rw['tax_drag'])
        yrs = months_between(OWN_START[c][0], END) / 12.0
        d.update(cost=cost, years=yrs, top10=t10[c], aum=aum[c])
        raw[c] = d
        if any((isinstance(v, float) and not np.isfinite(v)) for k, v in d.items() if k != 'top10'):
            raise SystemExit(f'{c}: 測れない値がある {d}')

    # ── 性質の点（絶対の式） ──
    def s_scores():
        S = {}
        for c in P:
            r_ = raw[c]
            s2 = None if r_['top10'] is None else 100 * min(1, max(0, (0.80 - r_['top10']) / 0.70))
            s3 = 100 * min(1, max(0, 1 - r_['cost'] / 0.008))
            s4 = 100 * min(r_['years'], 25) / 25
            a_ = r_['aum']
            s5 = 100 if a_ >= 10e9 else 80 if a_ >= 1e9 else 50 if a_ >= 0.3e9 else 20
            S[c] = dict(S1=float(S1[c][0]), S2=s2, S3=s3, S4=s4, S5=float(s5))
        med2 = float(np.median([S[c]['S2'] for c in P if S[c]['S2'] is not None]))
        for c in P:
            if S[c]['S2'] is None:
                S[c]['S2'] = med2
        return S, med2
    SS, med2 = s_scores()

    def score(axes=AXES, scale='pct', cent='V1', sub0=frozenset()):
        f = pctile if scale == 'pct' else minmax
        pts = {c: {} for c in P}
        for k, dr in DIR.items():
            kk = f'{k}_{cent}' if k in ('H1', 'H2') else k
            col = f([raw[c][kk] for c in P], dr)
            for i, c in enumerate(P):
                pts[c][k] = float(col[i])
        for c in P:
            pts[c].update(SS[c])
        ax = {}
        for c in P:
            ax[c] = {}
            for a_, sw in SUB.items():
                w_ = {k: v for k, v in sw.items() if k not in sub0}
                tot = sum(w_.values())
                ax[c][a_] = sum(pts[c][k] * v for k, v in w_.items()) / tot
        atot = sum(axes.values())
        total = {c: sum(ax[c][a_] * w_ for a_, w_ in axes.items()) / atot for c in P}
        order = sorted(P, key=lambda c: (-total[c], c))
        rank = {c: i + 1 for i, c in enumerate(order)}
        return dict(pts=pts, ax=ax, total=total, order=order, rank=rank)

    main_s = score()
    ks = {}
    for nm, kw in KS.items():
        kw2 = dict(axes=kw.get('axes', AXES), scale=kw.get('scale', 'pct'), cent=kw.get('cent', 'V1'),
                   sub0=frozenset(kw.get('sub0', ())))
        ks[nm] = score(**kw2)

    # ── 回帰の検査 ──
    reg = {}
    ref, ref_old = ref_five_mix_today(), json.load(open(REF5))['①1本ずつ']
    JAM = {'QQQM': 'NASDAQ100', 'SMH': 'SMH', 'ITA': 'ITA', 'XLV': 'XLV', 'VBR': 'VBR', 'VOO': 'S&P500'}
    drift = {}
    for c, ja in JAM.items():
        for grp in ('元の物差し', '基礎率の物差し', '百年', '実績'):
            for kk, v in ref_old[ja][grp].items():
                if v != ref[ja][grp][kk]:
                    drift[f'{c}・{grp}・{kk}'] = dict(十一月一日=v, 今日=ref[ja][grp][kk])
    reg['参考_11月1日の出力とのずれ（上流の French の表の更新）'] = drift
    bad = []
    for c, ja in JAM.items():
        i, j, o = P.index(c), bidx[c], ref[ja]

        def chk(lbl, mine, theirs, dec):
            if theirs is None or round(mine, dec) != round(theirs, dec):
                bad.append((c, lbl, round(mine, dec + 1), theirs))
        chk('元P15π', 100 * e['P15'][i], o['元の物差し']['P15π'], 2)
        chk('元平均', 100 * e['mean_pi'][i], o['元の物差し']['平均'], 2)
        chk('元5%未満', 100 * e['P5'][i], o['元の物差し']['五パーセント未満'], 2)
        chk('元最大下落', 100 * e['mdd'][i], o['元の物差し']['最大下落'], 1)
        chk('元ぶれ', 100 * e['vol'][i], o['元の物差し']['ぶれ'], 1)
        chk('基礎率P15π', 100 * bs['P15'][j], o['基礎率の物差し']['P15π'], 2)
        chk('基礎率平均', 100 * bs['mean_pi'][j], o['基礎率の物差し']['平均'], 2)
        chk('基礎率5%未満', 100 * bs['P5'][j], o['基礎率の物差し']['五パーセント未満'], 2)
        chk('100年中央V0', cc['V0']['c30med'][i], o['百年']['三十年の中央'], 3)
        chk('100年最悪V0', cc['V0']['c30min'][i], o['百年']['三十年の最悪'], 3)
        chk('実績割合', 100 * rz['share'][i], o['実績']['年15パーセント以上の割合'], 1)
        chk('実績中央', 100 * rz['med'][i], o['実績']['年率の中央'], 2)
        chk('実績最悪', 100 * rz['worst'][i], o['実績']['最悪'], 2)
    reg['a_five_mix_ndx_の1本ずつ（今日のデータで回した）と一致'] = dict(一致=not bad, 外れ=bad)
    # (b) 未来の世界だけの平均＝手で作った値
    pi = fast.pi
    fw = {k: pi[k] for k in ('B', 'C', 'D')}
    dmax = 0.0
    for i, c in enumerate(P):
        hand = (fw['B'] * rows[c]['B'] + fw['C'] * rows[c]['C'] + fw['D'] * float(np.expm1(fast.lD[i]))) / sum(fw.values())
        dmax = max(dmax, abs(hand - float(ef['mean_pi'][i])))
    reg['b_未来の世界だけの平均が手の値と一致'] = dict(一致=dmax < 1e-12, 最大の差=dmax)
    # (c) QQQM の100年
    nref = json.load(open(REFN))['NASDAQ100だけ_版ごと']
    iq = P.index('QQQM')
    cbad = [(v, k, round(float(cc[v][k][iq]), 4), nref[v][lbl]) for v in ('V0', 'V1')
            for k, lbl in (('c30med', '三十年の中央'), ('c30min', '三十年の最悪')) if round(float(cc[v][k][iq]), 3) != nref[v][lbl]]
    reg['c_QQQM_の100年が_ndx_recon_と一致'] = dict(一致=not cbad, 外れ=cbad)
    # (d) a=0 の FastBR＝未来の世界だけの Fast
    dd_ = 0.0
    for c, j in bidx.items():
        i = P.index(c)
        for k in ('mean_pi', 'P15', 'P5'):
            dd_ = max(dd_, abs(float(bz[k][j]) - float(ef[k][i])))
    reg['d_基礎率なしの_FastBR_が未来の世界だけの_Fast_と一致'] = dict(一致=dd_ < 1e-9, 最大の差=dd_)
    # (e)
    holes = [(c, k) for c in P for k, v in main_s['pts'][c].items() if v is None or not np.isfinite(v)]
    reg['e_対象と欠け'] = dict(一致=(n == 26 and not holes), 対象=n, 欠け=holes)
    allok = all(v['一致'] for k, v in reg.items() if not k.startswith('参考'))
    reg['全部一致'] = allok
    log('回帰の検査', json.dumps(reg, ensure_ascii=False)[:1500])
    if not allok:
        raise SystemExit('回帰の検査が通らない')

    # ── まとめ ──
    def pr(x, k=100, dgt=2):
        return None if x is None else round(k * x, dgt)

    per = {}
    for c in P:
        rw, d, s = rows[c], raw[c], main_s
        flags = []
        if rw.get('proxy') and rw.get('proxy_until'):
            nprox = sum(1 for m in k1 if m <= rw['proxy_until'])
            if nprox:
                flags.append(f'A1 の窓の {nprox}か月は代わりの系列（{rw["proxy"]}・{rw["proxy_until"]} まで）')
        if c not in bidx:
            flags.append('業種の基礎率は当てていない（米国の業種の物差し）＝F2・F3・D3 は元の未来の世界の値')
        if not bool(cents['V1'].has[P.index(c)]):
            flags.append('100年の写しが無い＝市場並み 1.0 と置いた')
        if c == 'MOAT':
            flags.append('100年の写しは French の BIG HiOP（大型×高収益）＝MOAT の決まりそのものではない')
        if c in TOP10_NONE:
            flags.append(f'上位10社が取れない＝S2 はほかの25本の中央値 {med2:.1f} 点と置いた')
        if c == 'TOPIX':
            flags.append('上位10社は MSCI Japan（EWJ）で代えた')
        if yen[c]['still']:
            flags.append('A1 の窓の終わりでもまだ円の高値を取り戻していない（最長の年数は終わりまで）')
        per[c] = dict(
            名前=rw.get('ja'), 器=rw.get('vehicle'), データ=rw.get('data'),
            生の値={
                '未来_期待の年率（元）': pr(d['F1']), '未来_期待の年率（業種の基礎率）': pr(d['F2']),
                '未来_年15パーセント以上の確率': pr(d['F3'], dgt=1),
                '過去_A1_26年の年率': pr(d['P1']), '過去_A2_15年の年率': pr(d['P2']),
                '過去_20年積立の年率の中央': pr(d['P3']), '過去_20年積立の年率の最悪': pr(d['P4']),
                '百年_中央_V1': round(d['H1_V1'], 3), '百年_最悪_V1': round(d['H2_V1'], 3),
                '百年_中央_V0': round(d['H1_V0'], 3), '百年_最悪_V0': round(d['H2_V0'], 3),
                '下げ_円の最大下落': pr(d['D1'], dgt=1), '下げ_ドルの最大下落': pr(float(e['mdd'][P.index(c)]), dgt=1),
                '下げ_年5パーセント未満（5つの世界）': pr(d['D2'], dgt=1), '下げ_年5パーセント未満（未来・基礎率）': pr(d['D3'], dgt=1),
                '下げ_円で高値を取り戻すまでの最長の年数': round(d['D4'], 1),
                '性質_費用（経費率＋外国税）': pr(d['cost'], dgt=3), '性質_記録の年数': round(d['years'], 1),
                '性質_上位10社の比率': pr(d['top10'], dgt=1), '性質_純資産（十億ドル）': round(d['aum'] / 1e9, 1),
                '性質_A1のぶれ': pr(float(e['vol'][P.index(c)]), dgt=1),
            },
            点={SUBJA[k]: round(v, 1) for k, v in s['pts'][c].items()},
            軸の点={a_: round(v, 1) for a_, v in s['ax'][c].items()},
            総合=round(s['total'][c], 2), 順位=s['rank'][c],
            自己更新の判断=S1[c][1], 記録の始まり=OWN_START[c][1],
            出どころ=dict(上位10社=t10src[c], 純資産=aumsrc[c]), 印=flags)

    ranking = [dict(順位=main_s['rank'][c], 本=c, 名前=rows[c].get('ja'), 総合=round(main_s['total'][c], 2),
                    **{a_: round(main_s['ax'][c][a_], 1) for a_ in AXES}) for c in main_s['order']]
    top10 = main_s['order'][:10]
    kin = {c: sum(1 for k in ks.values() if k['rank'][c] <= 10) for c in P}
    rng = {c: [min(k['rank'][c] for k in [main_s, *ks.values()]), max(k['rank'][c] for k in [main_s, *ks.values()])] for c in P}
    sens = {nm: dict(上位10=k['order'][:10], 主の上位10から出た本=[c for c in top10 if k['rank'][c] > 10],
                     入った本=[c for c in k['order'][:10] if c not in top10]) for nm, k in ks.items()}
    out = dict(
        generated=time.strftime('%Y-%m-%d'), tool='night/etf_scorecard.py', kind='参考（判定なし・配分は不変・採点の決まりは道具の頭に書き回す前にコミット）',
        question='単体の ETF で最も優秀なものを、過去の数字だけでなく性質も含めて多角的に評価して上位10まで',
        対象=P, 外した本=EXCLUDE, 測っていない本=NOT_MEASURED,
        重み=dict(軸=AXES, 軸の中=SUB), 物差しの名前=SUBJA,
        自己更新の表={c: dict(点=v[0], 理由=v[1]) for c, v in S1.items()},
        未来の世界の重み=fw, 上位10=top10, 順位=ranking, 本ごと=per,
        確かめ=sens, 確かめで上位10に残った回数=dict(sorted(kin.items(), key=lambda t: (-t[1], main_s['rank'][t[0]]))),
        順位の幅={c: rng[c] for c in main_s['order']},
        確かめごとの順位={nm: {c: k['rank'][c] for c in main_s['order']} for nm, k in ks.items()},
        regression=reg, secs=round(time.time() - t0, 1))
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    log('書いた', OUT, f'{out["secs"]}s')
    for x in ranking:
        c = x['本']
        log(f"{x['順位']:2d} {c:9s} {x['総合']:6.2f}  未来{x['未来']:5.1f} 過去{x['過去']:5.1f} 百年{x['百年']:5.1f} 下げ{x['下げ']:5.1f} 性質{x['性質']:5.1f}  確かめ{kin[c]}/9 幅{rng[c]}")


if __name__ == '__main__':
    main()
