#!/usr/bin/env python3
"""night/nx_summary.py — 『市場に勝てる歴史検証・新しい角度』(nx_*) の全体のまとめ（読むだけ・門の判定には不使用）

使い方: python3 night/nx_summary.py → out/nx_summary.json

各角度の out/nx_<角度>.json の tested から格付けを数え（数字は各 JSON が正本）、
下の HEADLINE に書いた『勝った規則と、その弱いところ』を並べる。HEADLINE の数字は、各角度の検査（3レンズ）と是正の後の値を
各 JSON から写したもの（写しがずれたら JSON が正しい）。
"""
import collections, datetime, glob, json, math, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out')
SKIP = ('prereg', 'nx_scout.json', 'nx_brand_av_delisted.json', 'nx_summary.json', 'nx_regrade.json')

ANGLES = ['nx_stack', 'nx_jst', 'nx_brand', 'nx_activist', 'nx_leadlag', 'nx_osap_intang', 'nx_osap_info', 'nx_osap_zoo',
          'nx_sentcond', 'nx_govparty', 'nx_pre1926x', 'nx_regime_ind', 'nx_jpfunds', 'nx_gpr', 'nx_lazy', 'nx_indmom_real']

# 勝った規則（S/A）と、その弱いところ。各角度の JSON の検査後の値。★ implementable は日本の個人（楽天・NISA）で持てるか
HEADLINE = {
    'nx_stack': {
        'question': '市場100%の上に、株以外の資産の因子（AQR）を先物で重ねると勝つか',
        'winner': 'P6: AQR 時系列の勢い（58先物・訓練のぶれで10%）を市場の上に重ねる＝S',
        'numbers': '訓練 1985-2006 +15.6%/年 t9.2・保有 2007-2026-05 +5.1 t2.16・費用1.3%後 +4.0・20年窓 21/21・シャープ 0.81 対 0.65・最大下落 −37 対 −50・全期間 t6.4（プログラム全体の多重検定の線も越える）',
        'weakness': '族の中の Holm 0.25（保有期間だけでは弱い）／保有の勝ちの52%は国債の勢い・2008/2022/2026前半を抜くと +1.1／暦年の揃う2017-2025は同じぶれの市場に −0.3／転がる10年窓は +15→−1 と単調に縮んだ',
        'implementable': '日本の個人は NISA で持てない。楽天の海外ETFに多資産の買い−売り型は無い。日本の同種の投信4本（2019〜）は円の現金に −0.9%/年（nx_jpfunds Q1）',
        'overlap': 'eknzbh の mw_overlay（同日後発）と TSMOM は重なる。マクロの割安・キャリー・守り・商品1877〜・信用はここだけ',
    },
    'nx_jst': {
        'question': '1870年からの18か国（JST）で国・資産の選び方は勝つか',
        'winner': 'P1: 年末の配当利回りが高い国の上位1/3を翌年に持つ＝S（副の相手〔GDP 加重・ドル建て〕でも S）',
        'numbers': '訓練 1871-1949 +2.9%/年 t3.5・保有 1950-2020 +3.0 t4.0・費用後 +2.4・全期間 t5.3・1年遅らせても +2.6 t3.3・どの国を抜いても残る',
        'weakness': '2007-2020 は −1.9%/年（t −2.4）・公表後 −1.2・20年窓の直近10本はすべて負け・実在の国別ETF（1997-2025）−0.7',
        'implementable': '楽天の器では16か国の国選びは組めない（EWJ・EWG・SPY 程度）',
        'overlap': 'eknzbh の mw_deep_history（国の割安＋勢い 1872〜）と同じ向き＝独立の再現',
    },
    'nx_brand': {
        'question': 'Interbrand のブランド価値の一覧に載った会社を公開後に買うと勝つか（2007-2026）',
        'winner': 'P2: 米国の親会社をブランド価値で加重＝S／P3: 全体版を等分（相手 French Developed）＝S',
        'numbers': 'P2 は SPY に +3.10%/年 t2.48 Holm 0.026・前半後半とも正・AAPL を抜いて正・費用後・下限版も正。P3 +2.07 t2.30',
        'weakness': '中身は巨大テック6社への集中（重み 14%→66%）: P2−『6社のまね』−0.48 t−0.64・因子に QQQ−SPY を足すと切片 0.46 t0.62・QQQ に −1.93・2022年の一覧の年を外すと Holm 0.137',
        'implementable': '米国版は楽天の米国株で全銘柄買えるが、価値加重の全部を持つには約8,600万円。実際にはユーザーの iFreeNEXT NASDAQ100 で大半が取れている',
        'overlap': 'なし（他セッションは一覧を使っていない）',
    },
    'nx_indmom_real': {
        'question': '楽天で買える米国の業種ETF 20本で業種の勢いを回すと SPY に勝つか（2001-2026）',
        'winner': 'P2（12か月の上位5本を毎月等分）A・P3（6か月の上位・6か月の重ね持ち）A・P4（1/3/6/12の平均）A',
        'numbers': 'P2 は SPY に +3.37%/年 t2.16・前半 +5.2/後半 +1.5・費用後 +3.1・SMH を抜いて +2.3・2007〜 +2.3 t1.4・シャープ 0.77 対 0.58・最大下落 −41 対 −51。紙（French 49）との差は −0.8',
        'weakness': 'Holm 後 0.077〜0.13 で S に届かない・2009〜2021 はほぼ0・後半の勝ちは SMH と2022年のエネルギー・翌月最初の営業日の約定では A の条件が崩れる・課税口座の税引後 +0.9〜+1.5・QQQ には 2009-04〜 −3.4%/年・実在の業種回転ETF（FV・XLSR・SECT）は SPY に −1.8〜−2.7',
        'implementable': '形の上では可能（成長投資枠でも借入なし）。ただし毎月の入れ替えで枠を食う（回せるのは約60〜110万円）・課税口座では税で大半が消える',
        'overlap': 'eknzbh の etf_tactical 第7族（楽天の業種・テーマ101本）と一部重なり、向きは同じ',
        'independent_support': '業種の勢いは、紙の French 49（eknzbh A）・Fidelity Select の実物（eknzbh A）・1889-1926 の Cowles の業種（nx_pre1926x A）でも勝ち＝全セッションで最も繰り返し現れた勝ち',
    },
    'nx_pre1926x': {
        'question': '他セッションで生き残った規則を 1871〜1926（誰も見ていない時代）に当てる',
        'winner': '業種の勢い G3（12か月・上位5業種）A・G4（上位10）A＝『再現』',
        'numbers': 'Cowles 69業種 1889-1926: G3 +5.1%/年 t2.01・G4 +5.1 t2.37・20年窓 17/17',
        'weakness': 'G3 の t は線の上ぎりぎり・第一次大戦の数年を抜くと t≈1・相手を業種の等分にすると B。業種ごとの10か月線は再現せず。LSE の株・業種は事前登録の止まる条件（相関 0.48<0.6）で保留',
        'implementable': '—（歴史の答え合わせ）',
        'overlap': 'q07leu 第9回（1871-1925 の dip_lever・trend）と規則は重ならない',
    },
    'nx_jpfunds': {
        'question': '日本の公募投信で過去の成績の上位1/4を毎年選ぶと指数型に勝つか（Carhart の日本版・2007-2026）',
        'winner': '探索 X1（過去1年の上位1/4）＝S（主の P1・P2〔3年・5年〕は B）',
        'numbers': 'X1 は指数型に +2.29%/年 t2.46 Holm 0.028・前半後半とも正・費用後 +1.47・下限 +0.43',
        'weakness': '探索の族（主の結論に使わない）・勝ちは国内株式の分類だけ（外国4分類 +0.1）・小型成長の型の勢いで3〜5割説明・過去の購入時手数料（上限）なら −0.13・償還ファンドまで含めた三菱UFJ の比較で −2.1',
        'implementable': '可能（NISA 成長投資枠で能動の投信）。ただし毎年7割入れ替え',
        'overlap': 'なし（eknzbh の jp_nisa_bridge は日本の投信を器として使っただけ）',
    },
}
NO_WIN = {
    'nx_activist': '物言う株主の13Dの後に買う: 2007年以降 SPY に −4〜−10%/年。B の勝ちは2001-06 の生き残りの偏り',
    'nx_leadlag': '取引先の業種の値動きで業種を選ぶ（Menzly-Ozbas・Rapach の LASSO）: 26本すべて C。訓練では一部効いたが2007年以降は費用後に0本',
    'nx_osap_intang': 'OSAP の無形資産（組織資本・広告・研究開発ほか）: 最良 B（組織資本・訓練 t4.6 だが保有 t0.5・公表後 −2.1）。eknzbh の mw_oap_signals と重なる',
    'nx_osap_info': 'OSAP の空売り・格下げ・予想修正・推奨・オプション: 主の族に A 以上なし。探索のオプションの形2本が A（短い標本）だが勝ちの半分は1999-2002・保有の費用後 +0.3。eknzbh と重なる',
    'nx_osap_zoo': 'OSAP の残り29信号の大型株版（FF93 BH）: 長い歴史の線で A/S 0。短い標本の A（前受収益の増加）はテックの傾きで説明',
    'nx_sentcond': '投資家の心理指数（拡大窓で作り直し）で堅い株と市場を切替: 19本すべて C（訓練の t が最大1.76）',
    'nx_govparty': '大統領の党×政府への依存度の業種: 主の最良 B。党で切り替える上乗せは訓練 +2.0 t2.4 → 保有 −0.5・公表後 −1.1',
    'nx_regime_ind': 'インフレ・逆イールド・Sahm・SPF の局面で業種を替える: 24本すべて C（インフレ→実物 +1.7 t0.9 は2021-22の石油だけ）',
    'nx_gpr': '地政学リスクが跳ねた後に厚く持つ: 16本すべて C（勝ちは平均の倍率＝β・C8 のシャープで落ちる）',
    'nx_lazy': '10-K の本文の変化（Lazy Prices・793社・17,914件）: 50本 B 10・C 40。eknzbh の mw_lazy_prices（22本すべて C）と独立に同じ結論',
}


def find_grade(e):
    if not isinstance(e, dict):
        return None
    for k in ('grade', 'grade_main', 'grade_final'):
        if k in e and isinstance(e[k], str):
            return e[k]
    for k in ('grading', 'result', 'views', 'main'):
        v = e.get(k)
        if isinstance(v, dict):
            g = find_grade(v)
            if g:
                return g
    return None


def main():
    per = {}
    total = collections.Counter()
    for a in ANGLES:
        p = os.path.join(OUT, f'{a}.json')
        if not os.path.exists(p):
            per[a] = {'missing': True}
            continue
        d = json.load(open(p))
        c = collections.Counter()
        for e in d.get('tested', []):
            g = find_grade(e)
            key = g if g in ('S', 'A', 'B', 'C') else ('PENDING' if g and 'PENDING' in g else ('graded_other' if g else 'not_graded'))
            c[key] += 1
        per[a] = {'grades': dict(c), 'graded': sum(v for k, v in c.items() if k in 'SABC'),
                  'prereg': f'out/{a}_prereg.json', 'result': f'out/{a}.json'}
        for k in 'SABC':
            total[k] += c.get(k, 0)
    n = sum(total.values())
    # 両側 5% の Bonferroni の線（プログラム全体・格付けした本数）
    from statistics import NormalDist
    tstar = NormalDist().inv_cdf(1 - 0.025 / n) if n else None
    out = {
        'generated': datetime.date.today().isoformat(),
        'program': 'nx（next angles）＝並走セッションが使っていない角度で『市場に勝てる歴史検証』を探した（2026-09-28〜29）',
        'prereg': 'out/nx_prereg.json（線は eknzbh の mw_prereg と同一の C1〜C8・S/A/B/C。短い標本は hbm38n の ev5 と同じ形）',
        'method': '角度ごとに 設計（データの形だけ見る）→ 事前登録をコミット → 実装して一度走らせる → 反証の検査3レンズ（事前登録との一致と先読み・独立の再計算・悪魔の代弁者）→ 見つかった誤りを是正して走らせ直す。規則は結果を見て変えていない',
        'graded_rules_total': n, 'grades_total': dict(total),
        'bonferroni_t_program_wide': round(tstar, 2) if tstar else None,
        'per_angle': per,
        'winners': HEADLINE,
        'no_win': NO_WIN,
        'pattern': [
            '長い歴史（〜2006 や 1870〜1949・1889〜1926）では勝つ規則が多い（時系列の勢いの重ね・国の配当利回り・業種の勢い・組織資本・Hou の大型→小型など）が、2007年以降の米国の大型株の市場（上限なしの時価加重＝S&P500）に対しては縮むか負ける',
            '2007年以降に勝った規則の中身は、(a) 危機の年（2008・2022）の上乗せ（時系列の勢い）か、(b) 巨大テック・成長株への傾き（ブランド価値・前受収益・研究開発）か、(c) 半導体とエネルギーの業種の勢い、のどれか',
            'ユーザーの ETF 側の主力（NASDAQ-100）には、2009年以降どの規則も勝っていない（業種ETFの勢い −3.4%/年・ブランド価値 −1.9）',
            '他セッションと同時に同じデータに行き着いた角度（TSMOM の重ね・JST・OSAP・Lazy Prices）は、結論の向きが一致した＝独立の再現',
        ],
        'rounding_fix_2026_09_29': 'nx_common.rolling/dca の勝ちの数え方を是正（丸める前の差で数える）。影響する7角度を走らせ直し、格付けの変化は regrade 欄を見よ',
    }
    rg = os.path.join(OUT, 'nx_regrade.json')
    if os.path.exists(rg):
        out['regrade'] = json.load(open(rg))
    p = os.path.join(OUT, 'nx_summary.json')
    json.dump(out, open(p, 'w'), ensure_ascii=False, indent=1)
    print(p, n, dict(total), out['bonferroni_t_program_wide'])


if __name__ == '__main__':
    main()
