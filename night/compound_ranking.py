#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/compound_ranking.py — **「今後も高い複利を出す可能性が高い順」を、この台帳の実測だけで組む**（2026-08-09新設）

発端（ユーザー指示「今までみた銘柄で今後も高い複利を達成する可能性が高い銘柄を順番に出して」）。

**先に順位づけの規則を書く（結果を見てから重みを決めないため）。** 使うのは
この台帳が**実測で「効いた」と確認した変数だけ**で、効かないと確認した変数は使わない。

【使う】
  1. **機構(irr)** —— 歴史で継続/非継続を分けた唯一の変数。プール754件の P(継続):
     irr=50 **0.162** ／ irr=70 **0.366** ／ irr=85 **0.579**（ベース0.204）。irr=100 は 0.056 で最下位＝使わない
  2. **機構の型** —— 追試で **B設計組込は 0/2・恒久毀損100%**（CMTL −17.2%）。
     第三者/顧客が認定する型（A工程認定・C第三者・D名簿・E長期認定）は 恒久毀損 0%
  3. **本人の実績** —— 今日の14社のうち11社は2018年コホート本人で実現年率が判っている。
     ただし**売上成長の寄与と残差(利益率・株数・配当・倍率)に分解して読む**——
     LRCX +43.5% は残差 +29.4pt、CW +24.5% は +19.0pt＝大半が再評価で、20年の再現性は低い側
  4. **恒久毀損の回避** —— 20年複利では1回の毀損が全部を消す。門の関門がそのまま条件:
     nde≤4（財務キル）／dep<40（存続級依存）／事業の収縮なし／堀70+／データ健全

【使わない・理由も実測】
  ・**入口の財務の近さ**（営利率・成長・FCF転換）——2018年の財務で距離を作って同じ窓に当てると
    Q1 の P(15%+)=0.21 ＝ 全体の 0.21 で**リフトゼロ**（night/irr85_lookalike.py）
  ・**高成長** —— trailing 20-30% の前方10年は中央値 7.1%・15%維持は20%＝**逆信号(lift 0.6)**
  ・**高い営業利益率** —— 2018年コホート最悪の2社 IPGP(39.1%)・OLED(43.6%) は営利率で3位と1位
  ・**価格(PER/E[r])** —— 質・堀の中では選別力を持たないと4例で確認済み（v9.9.98で合否から外した）
  ・**Ω** —— 配分の順位に寄与ゼロ（全社一定にしても順位0/11箇所・v9.9.96）

⚠**これは予測ではなく「型の確からしさ」の順位**。n はどこも小さい（irr=85 は各ビンテージ 6〜21社）。
  歴史の窓は8〜13年で、20〜30年へ外挿したものではない。

使い方: python3 night/compound_ranking.py [--json]
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]

PCONT = {50: 0.162, 70: 0.366, 85: 0.579, 100: 0.056}
# 機構の型（2026-08-05〜07 の原本検算で確定した引用から。B=設計組込は追試で最弱）
MECH = {'ASML': 'C 顧客ファブでの受入試験・量産認定（＋EUV唯一供給）', 'VRSK': 'D 州規制当局が統計エージェントに指定',
        'CW': 'C OEM顧客自身が認証（＋FAA/DoD）', 'LRCX': 'A 工程認定（qualify し直さない）',
        'RBC': 'C OEM・DoD・FAA が用途ごとに認定', 'MKSI': 'E copy-exact の再認定',
        'ENTG': 'E 顧客による requalification', 'TDG': 'C 第三者＋顧客の認証',
        'WST': 'C 顧客がデータを作り直す必要', 'BWXT': 'D/E 海軍原子燃料の唯一供給',
        'NOVT': 'E 新規供給者の長い認定期間', 'LOAR': 'C OEMが認定をやり直さない',
        'HXL': 'C 顧客の認定が使える炭素繊維を決める', 'ST': 'B 設計組込 ← 追試で最弱（0/2）'}
# 2018→2026 の実現年率と、その内訳（売上CAGR / 残差）——本セッションで XBRL から算出
SELF = {'LRCX': (43.5, 14.1, 29.4), 'CW': (24.5, 5.5, 19.0), 'TDG': (20.7, 12.1, 8.6),
        'ENTG': (19.6, 11.3, 8.3), 'RBC': (19.2, 13.4, 5.7), 'MKSI': (17.2, 9.3, 7.9),
        'WST': (15.7, 8.4, 7.3), 'BWXT': (14.0, 8.2, 5.8), 'NOVT': (12.3, 8.1, 4.2),
        'HXL': (5.9, None, None), 'ST': (-0.7, None, None),
        # irr=70 の投下可5社も本人の実績が在庫にある。**MSFTとKLACは事業が稼いだ分が全体で最上位**
        'MSFT': (22.1, 17.5, 4.6), 'KLAC': (43.5, 18.3, 25.2), 'V': (13.9, 10.1, 3.8),
        'IDXX': (11.4, 10.1, 1.3), 'RMD': (10.7, 11.9, -1.2)}


def main():
    SA = {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}
    rows = []
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        x = json.load(open(p, encoding='utf-8'))
        x = x.get('data') or x
        irr = x.get('irr')
        if irr not in (70, 85):
            continue
        r = SA.get(t, {})
        if irr == 70 and not r.get('buy'):
            continue                     # irr=70 は「今日買える社」だけ（母集団200社超を並べても意味がない）
        s = SELF.get(t)
        rows.append(dict(t=t, irr=irr, mech=MECH.get(t, ''), s=r.get('s'), moat=r.get('moat'),
                         buy=bool(r.get('buy')), quali=bool(r.get('quali')),
                         nde=x.get('nde'), dep=x.get('dep'),
                         self_ret=s[0] if s else None, self_rev=s[1] if s else None,
                         self_res=s[2] if s else None, p=PCONT.get(irr)))

    def rank_key(r):
        # 規則: ①機構(85が先) ②B型は後ろ ③本人が15%+を出したか ④今日買えるか
        #       ⑤事業が稼いだ分（残差でなく売上成長）が大きい順 ⑥実績が無ければ最後
        b = 1 if r['mech'].startswith('B') else 0
        proven = 0 if (r['self_ret'] is not None and r['self_ret'] >= 15) else (
                 1 if r['self_ret'] is not None else 2)
        return (0 if r['irr'] == 85 else 1, b, proven, 0 if r['buy'] else 1,
                -(r['self_rev'] if r['self_rev'] is not None else -1))

    rows.sort(key=rank_key)
    print('■ 今後も高い複利を出す可能性が高い順（この台帳が「効いた」と実測した変数だけで組んだ）')
    print('  ※予測ではなく**型の確からしさ**の順位。n はどこも小さい\n')
    print(f"  {'':<4}{'':<6}{'irr':>4}{'P(継続)':>8}{'本人の実績':>10}{'うち事業':>9}{'門':>10}  機構／備考")
    for i, r in enumerate(rows, 1):
        sr = f"{r['self_ret']:+.1f}%" if r['self_ret'] is not None else '  —'
        sv = f"{r['self_rev']:.1f}%" if r['self_rev'] is not None else '  —'
        st = '🟢投下可' if r['buy'] else ('🔵次点' if r['quali'] else '⛔')
        print(f"  {i:>2}. {r['t']:<6}{r['irr']:>4}{r['p']:>8.3f}{sr:>10}{sv:>9}{st:>10}  {r['mech']}")

    print('\n■ この順位が言っていること / 言っていないこと')
    print('  ・言っている: **機構が実証され、本人が過去に複利を出し、事業が稼いだ分が大きい**社ほど上。')
    print('  ・言っていない: 「この順に儲かる」。入口の財務も価格もΩも、歴史では継続を分けなかった。')
    print('  ・**壊れない側**を重く見るなら irr=70 群も強い——歴史の恒久毀損は')
    print('    irr=70 **2%**（n=101）vs irr=85 **10%**（n=10）で、標本も10倍厚い。')
    print('    「上を狙うなら85／下を防ぐなら70」。今日の投下可10社は 85が5社・70が5社でちょうど半々')
    # ── 第二の並び: **事業が稼いだ分**（実現年率のうち売上成長の寄与）の順 ───────────────
    #   20年持つ側にとって再現性が高いのはこちら。再評価(残差)は業種と相場の運が大きい
    g = [r for r in rows if r['self_rev'] is not None]
    g.sort(key=lambda z: -z['self_rev'])
    print('\n■ 第二の並び: **事業が稼いだ分**（実現年率のうち売上成長の寄与）の順')
    print('  ——再評価(残差)は業種と相場の運。20年持つ側にとって再現性が高いのはこちら')
    print(f"  {'':<4}{'':<6}{'irr':>4}{'実現':>8}{'うち事業':>9}{'残差':>8}{'門':>10}")
    for i, r in enumerate(g, 1):
        print(f"  {i:>2}. {r['t']:<6}{r['irr']:>4}{r['self_ret']:>7.1f}%{r['self_rev']:>8.1f}%"
              f"{r['self_res']:>7.1f}p{('🟢投下可' if r['buy'] else ('🔵次点' if r['quali'] else '⛔')):>10}")

    if AS_JSON:
        p = 'out/compound_ranking.json'
        json.dump({'generated': '2026-08-09', 'rows': rows}, open(p, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
