#!/usr/bin/env python3
"""night/hidiv_funds.py — 高配当の投資信託を全部洗って分析する（2026-10-27・参考・判定なし）

ユーザーの問い「高配当はもっと投資信託があるから探して分析して」。配分は変えない。並べ方は結果を見る前にこのファイルで固定し、回す前にコミットする。

① 投資信託協会の全件の写し（out/_nx_cache/newfunds/jita_full.json・基準日 2026-10-09・night/newfunds.py が作る）から、
  名前に 高配当／配当貴族／増配／配当成長／好配当／ディビデンド／インカム株／SCHD／シュワブ を含む株式の本。
  外す: リート・債券・バランス・ブル／ベア・通貨選択・カバードコール（名前で）。
  地域（名前で）: 米国／日本／全世界・グローバル／先進国／新興国・アジア／欧州／その他。指数型＝名前に「インデックス」か ETF の名（SPDR・バンガード 等）。
  騰落率（協会の値・同じ基準日）を年率に（3年・5年・10年）。比べる相手は同じ一覧の eMAXIS Slim 米国株式（S&P500）・国内株式（TOPIX）・
  全世界株式（オール・カントリー）・iFreeNEXT NASDAQ100（同じ基準日の騰落率＝費用も連動のずれも入った手取りの比べ）。
  並べ方（固定）: 地域の中で 5年の年率の大きい順（無ければ3年）。楽天証券で買えるか（販売会社の一覧）・つみたて／成長投資枠の印・信託報酬（税抜）・純資産。
② 元の ETF の値動き（Yahoo・配当込み・ドル建て・月次）: VYM・SPYD・SCHD・HDV・DVY・VIG・DGRW・NOBL と比べ相手 SPY・QQQ。
  共通の窓（SPYD がそろう 2015-11〜）と各本の設定来の年率・ぶれ・最大下落・2022年・QQQ との相関。
③ 今の形に入れたら（NASDAQ100 の5を X へ）: 物差しの行がある VYM・VIG だけ。tsumitate_cand と同じ物差し（VYM の 2006-11 以前は French の配当利回り上位30%でつなぐ）。
⚠ 協会の騰落率は分配金を再投資したとして計算した値（毎月分配の本も比べられる）・直近の窓は米国の大型テックが勝った時期・名前の分類は機械で誤りうる。
使い方: python3 night/hidiv_funds.py → out/hidiv_funds.json
"""
import datetime, json, math, os, re, sys, time, unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'hidiv_funds.json')
SRC = os.path.join(BASE, 'out', '_nx_cache', 'newfunds', 'jita_full.json')
HIT = re.compile('高配当|配当貴族|増配|配当成長|好配当|ディビデンド|インカム株|SCHD|シュワブ|配当利回り|配当株')
EXC = re.compile('リート|REIT|債券|バランス|ブル|ベア|通貨選択|カバード|コール|プレミアム|ヘッジ付|分配型.*債')
IDX = re.compile('インデックス|SPDR|バンガード|Vanguard|S&P|ダウ|FTSE|MSCI|配当貴族|iシェアーズ|ETF')
REG = [('米国', '米国|アメリカ|全米|ＵＳ|US'), ('日本', '日本|国内|ジャパン|日経|TOPIX|JPX'), ('先進国', '先進国'),
       ('新興国・アジア', '新興国|アジア|インド|中国|ASEAN'), ('欧州', '欧州|ヨーロッパ'), ('全世界', '全世界|グローバル|世界|オール・カントリー')]
BENCH = {'S&P500': 'eMAXISSlim米国株式(S&P500)', 'TOPIX': 'eMAXISSlim国内株式(TOPIX)',
         '全世界': 'eMAXISSlim全世界株式(オール・カントリー)', 'NASDAQ100': 'iFreeNEXTNASDAQ100インデックス'}
ETFS = ['VYM', 'SPYD', 'SCHD', 'HDV', 'DVY', 'VIG', 'DGRW', 'NOBL', 'SPY', 'QQQ']


def nk(s):
    return unicodedata.normalize('NFKC', s or '').replace(' ', '').replace('　', '')


def ann(cum, y):
    if cum in (None, '', '-'):
        return None
    try:
        c = float(cum)
    except ValueError:
        return None
    return round(100 * ((1 + c / 100) ** (1 / y) - 1), 2)


def part1():
    d = json.load(open(SRC))
    rows, std = d['rows'], d['std']
    bench = {}
    for k, nm in BENCH.items():
        r = next((r for r in rows if nk(r['fundNm']) == nk(nm)), None)
        bench[k] = None if r is None else {y: ann(r.get(f'standardPriceRa{y}y'), y) for y in (3, 5, 10)}
    out = []
    for r in rows:
        nm = nk(r['fundNm'])
        if not HIT.search(nm) or EXC.search(nm) or r.get('investAssetKindCd') not in ('1', None):
            continue
        reg = next((g for g, p in REG if re.search(p, nm)), 'その他')
        sellers = [nk(x.get('instName')) for x in (r.get('institutionInfo') or [])]
        out.append(dict(名前=r['fundNm'], 運用会社=r.get('entrustCmpNm'), 地域=reg, 指数型=bool(IDX.search(nm)) and 'アクティブ' not in nm,
                        信託報酬_税抜=float(r['trustReward']) if r.get('trustReward') else None,
                        純資産_億円=round(float(r['totalNetAssets']) / 100, 1) if r.get('totalNetAssets') else None,
                        設定日=(r.get('establishedDate') or '')[:10], 決算の回数=r.get('setlFqcy'),
                        年率_3年=ann(r.get('standardPriceRa3y'), 3), 年率_5年=ann(r.get('standardPriceRa5y'), 5), 年率_10年=ann(r.get('standardPriceRa10y'), 10),
                        楽天証券=any('楽天証券' in s for s in sellers), つみたて投資枠=r.get('nisaFlg') == '1', 成長投資枠=r.get('nisaGrowthFlg') == '1'))
    groups = {}
    for x in out:
        groups.setdefault(x['地域'], []).append(x)
    for g in groups.values():
        g.sort(key=lambda x: -(x['年率_5年'] if x['年率_5年'] is not None else (x['年率_3年'] if x['年率_3年'] is not None else -99) - 100))
    return std, bench, groups, len(out)


def stats(s, ms):
    xs = [s[m] for m in ms]
    g = math.exp(sum(math.log1p(x) for x in xs) * 12 / len(xs)) - 1
    mu = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs)) * math.sqrt(12)
    v = pk = 1.0; mdd = 0.0
    for x in xs:
        v *= 1 + x; pk = max(pk, v); mdd = min(mdd, v / pk - 1)
    return dict(年率=round(100 * g, 2), ぶれ=round(100 * sd, 1), 最大下落=round(100 * mdd, 1), 月数=len(xs), 起点=ms[0], 終点=ms[-1])


def corr(a, b, ms):
    xa = [a[m] for m in ms]; xb = [b[m] for m in ms]
    ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
    c = sum((p - ma) * (q - mb) for p, q in zip(xa, xb))
    return round(c / math.sqrt(sum((p - ma) ** 2 for p in xa) * sum((q - mb) ** 2 for q in xb)), 2)


def part2():
    import mw_common as M
    S = {t: M.yahoo(t) for t in ETFS}
    common = sorted(set.intersection(*[set(S[t]) for t in ETFS]))
    res = {}
    for t in ETFS:
        own = sorted(S[t])
        y22 = [m for m in own if 202201 <= m <= 202212]
        ms_q = sorted(set(own) & set(S['QQQ']))
        res[t] = dict(設定来=stats(S[t], own), 共通の窓=stats(S[t], common),
                      **{'2022年': round(100 * (math.prod(1 + S[t][m] for m in y22) - 1), 1) if len(y22) == 12 else None},
                      QQQとの相関=corr(S[t], S['QQQ'], ms_q), SPYとの相関=corr(S[t], S['SPY'], sorted(set(own) & set(S['SPY']))))
    return res, (common[0], common[-1])


def part3():
    import unx_assets as U
    import upside_check as UC
    import mw_common as M
    BASEF = {'QQQM': 40, 'SMH': 30, 'ITA': 15, 'SHLD': 5, 'XLV': 5, 'FBT': 5}
    F = {'今': dict(BASEF)}
    for x in ('VYM', 'VIG'):
        f = dict(BASEF); f['QQQM'] -= 5; f[x] = 5; F[f'NASDAQ100→{x}'] = f
    res = U.build()
    rows, chains = res['rows'], res['chains']
    hd = M.french_series('Portfolios_Formed_on_D-P', want='Value Weight Returns')['Hi 30']
    for t, er in (('VYM', 0.0006),):
        v0 = min(chains[t])
        for m in sorted(m for m in hd if 199001 <= m < v0):
            chains[t][m] = hd[m] - er / 12
    late = {a: min(chains[a]) for f in F.values() for a in f if min(chains[a]) > UC.FIRST}
    if late:
        for a in late:                        # 主の窓にそろわない本は物差しから外す（名指し）
            F = {k: v for k, v in F.items() if a not in v}
    mega = U.mega_map(rows, sorted({a for f in F.values() for a in f} | {'VOO'}))
    tab = U.measure(F, rows, chains, mega=mega)[UC.W_CRASH]
    C = U.century_parts(); C['parts']['VYM'] = hd; U.MONTHLY_OK.add('VYM')
    out = {}
    for nm in F:
        r = tab[nm]; c = U.strip_century(U.century_monthly(F[nm])) or {}
        c30 = next((v for k, v in c.items() if k.startswith('30年')), {})
        out[nm] = {k: r[k] for k in ('π加重の平均の年率', 'P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', '過去の転がる20年で15%以上')}
        out[nm]['100年_30年_中央'] = c30.get('中央値'); out[nm]['100年_30年_最悪'] = c30.get('最悪')
    return out, late


def main():
    t0 = time.time()
    std, bench, groups, n = part1()
    etf, win = part2()
    port, late = part3()
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/hidiv_funds.py', kind='参考・判定なし（配分は変えない）',
               question='高配当はもっと投資信託があるから探して分析して', 基準日=std, 本数=n, 比べる相手_年率=bench, 地域ごと=groups,
               元のETF=dict(共通の窓=win, 本=etf), 今の形に入れたら=port, 物差しから外した本=late,
               caveats=['協会の騰落率は分配金再投資の値・同じ基準日', '名前の分類は機械（誤りうる）', '直近10年は米国の大型テックが勝った時期'],
               secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    print('本数', n, '基準日', std, '相手', bench)
    for g, xs in groups.items():
        print(f'== {g} {len(xs)}本')
        for x in xs[:12]:
            print(f"  {x['年率_3年']} {x['年率_5年']} {x['年率_10年']} 報酬{x['信託報酬_税抜']} 純資産{x['純資産_億円']}億 楽天{int(x['楽天証券'])} つみ{int(x['つみたて投資枠'])} 成長{int(x['成長投資枠'])} 指数{int(x['指数型'])} {x['名前']}")
    print('元の ETF', win)
    for t, v in etf.items():
        print(' ', t, v)
    for k, v in port.items():
        print(' ', k, v)


if __name__ == '__main__':
    main()
