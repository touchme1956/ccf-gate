#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr_reread.py — **irr=70 を裁く材料を原本から組み立てる**（2026-08-12新設）

【なぜ新しい道具が要るのか——既存の抽出器では 70 を裁けない】
  `night/irr85_extract.py` は **85 を探すために**作られている。抜く語は
  qualif / certif / design-in / sole source / installed base / lock-in ＝
  **「顧客が再認定するか」を判定するための語彙**。
  ところが 70 は「移行に摩擦はあるが、費用を払うのは当社側」という**別の主張**で、
  それを支える語（switching cost・migration・data conversion・workflow・
  multi-year contract・retraining・integration）は CORE にほとんど入っていない。
  実測: 投下可の5社に85用の抽出を当てると、**V は機構文が一つも出ず**、
  IDXX は自社のサプライヤの話、RMD は自社取得のCE/MDSAP ばかりが上位に来た。
  ＝**70 か 50 かを裁く材料は、この repo にまだ一度も組み立てられていない。**

【なぜそれが重要か（2026-08-12 の実測）】
  ・刻み別のラベル一致率は **70 が 0.706**（50 は 0.971 / 85・100 は 1.00）
  ・今日の投下可10社のうち **7社が irr 1段で落ちる**（KLAC の余裕は 0.3pt）
  ・**50→70 の誤りは今日ひとりも動かさない**＝コストは完全に一方向
  ⇒ 精度を上げるべき場所は 70 のただ一点で、そこに材料が無かった。

【この道具がすること／しないこと】
  する: 原本から **85型・70型・50型（逆向き）** の三系統で文を抜き、向きの印を付ける
  しない: **判定しない**。刻みを決めるのは原本を読む審査官の仕事（絶対のルール2）。
          この道具は「同じ材料を全員に配る」だけ（irr85_extract の立場と同じ）

使い方:
  python3 night/irr_reread.py KLAC HWM V IDXX RMD      → out/irr_reread.json
  python3 night/irr_reread.py --buy                     → 投下可の irr=70/85 を全部
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, 'night')
# **二重実装を作らない**——取得・本文化・文分割は irr85_extract のものをそのまま使う
from irr85_extract import cik_of, latest_annual, text_of, annual_text, sentences, CORE, CUST, SELF, WISH

# ── 70型（移行の摩擦。費用を払うのが当社側でも成立する）──────────────────
FRICTION = re.compile(
    r'\b(switch\w*\s+(?:cost|to|from|suppliers?|vendors?|providers?)|switching'
    r'|migrat\w*|convert\w*\s+data|data\s+conversion|re-?train\w*|retrain\w*'
    r'|integrat\w+\s+(?:into|with)|embedded\s+in|workflow\w*'
    r'|multi-?year\s+(?:contract|agreement)|long-?term\s+(?:contract|agreement)'
    r'|renewal\s+rate\w*|retention\s+rate\w*|recurring\s+revenue'
    r'|disrupt\w*\s+(?:their|customer)|costly\s+and\s+time-?consuming'
    r'|time-?consuming\s+and\s+(?:costly|expensive))\b', re.I)

# ── 50型（**逆向き**＝障壁が無い・下がる。50 を積極的に支持する語）──────────
AGAINST = re.compile(
    r'\b(low(?:er)?\s+barriers?\s+to\s+entry|limited\s+barriers?|no\s+significant\s+barriers?'
    r'|reduce\w*\s+barriers?|highly\s+competitive|intense\s+competition|price\s+competition'
    r'|price\s+erosion|readily\s+available\s+(?:alternatives?|substitutes?)'
    r'|alternative\s+suppliers?|may\s+switch\s+to|easily\s+switch'
    r'|commodit\w+|fragmented)\b', re.I)


def classify(s):
    """三系統のどれに当たるか。**判定ではなく仕分け**（複数該当しうる）"""
    return {'85型': bool(CORE.search(s)), '70型': bool(FRICTION.search(s)),
            '50型(逆向き)': bool(AGAINST.search(s))}


def grab(f, maxn=60):
    """f は latest_annual の返り値（40-F は添付の AIF・MD&A まで読む）"""
    out, seen = [], set()
    for s in sentences(annual_text(f)):
        if len(s) < 60 or len(s) > 900:
            continue
        c = classify(s)
        if not any(c.values()):
            continue
        # XBRL の断片・目次・株式の証券記述は落とす（機構の話ではない）
        if re.search(r'contextRef|Member\b|iso4217|xbrli|Exhibit\s|Table of Contents'
                     r'|Certificate of (?:Incorporation|Designations|Retirement)'
                     r'|qualified\s+(?:employee|workforce|personnel|talent)'
                     r'|Director Qualifications|VALUATION AND QUALIFYING', s):
            continue
        k = s[:90].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append({'s': s.strip(), **c,
                    'cust': bool(CUST.search(s)), 'self': bool(SELF.search(s)),
                    'wish': bool(WISH.search(s))})
        if len(out) >= maxn:
            break
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--buy' in sys.argv:
        sa = json.load(open('out/score_all.json', encoding='utf-8'))
        args = [x['t'] for x in sa if x.get('buy') and str(x.get('irr')) in ('70', '85')]
    if not args:
        raise SystemExit(__doc__)

    packs = {}
    for t in args:
        p = f'out/{t}_gate_pack.json'
        if os.path.exists(p):
            packs[t] = json.load(open(p, encoding='utf-8'))

    out = {'generated': '2026-08-12', 'tool': 'night/irr_reread.py',
           'stance': 'この道具は判定しない。刻みを決めるのは原本を読む審査官（絶対のルール2）',
           'vocab': {'85型': CORE.pattern[:120] + '…', '70型': FRICTION.pattern[:120] + '…',
                     '50型(逆向き)': AGAINST.pattern[:120] + '…'},
           'items': {}}
    for t in args:
        try:
            cik = cik_of(t)
            f = latest_annual(cik)
            rows = grab(f) if f else []
        except Exception as e:
            out['items'][t] = {'error': str(e)}
            continue
        d = packs.get(t) or {}
        m = (d.get('_meta') or {})
        cnt = {k: sum(1 for r in rows if r[k]) for k in ('85型', '70型', '50型(逆向き)')}
        out['items'][t] = {
            'nm': d.get('nm'), '台帳のirr': d.get('irr'),
            '台帳の根拠': (m.get('evidence') or {}).get('irr'),
            'form': f.get('form'), 'filed': f.get('filed'), 'url': f.get('url'),
            '抽出文': len(rows), '内訳': cnt,
            '顧客側の主語が立つ文': sum(1 for r in rows if r['cust']),
            'rows': rows}
        print(f"  {t:<6} {f.get('form')} {f.get('filed')}  抽出 {len(rows):>3}文"
              f"  85型{cnt['85型']:>3} / 70型{cnt['70型']:>3} / 逆向き{cnt['50型(逆向き)']:>3}"
              f"  顧客側の主語 {out['items'][t]['顧客側の主語が立つ文']}", file=sys.stderr)

    json.dump(out, open('out/irr_reread.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('→ out/irr_reread.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
