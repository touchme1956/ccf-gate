#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/kessan_flags.py — **四半期点検の「要審査」を機械可読にする**（2026-08-11新設・v9.9.140）

■ なぜ要るか（実測で見つけた穴）
  `kessan_check.py` / `kessan_check_jp.py` は out/kessan/{T}_qcheck*.txt に判定を書く。
  ところが **その判定を読む機械が一つも無かった**——`night/enqueue_reaudit.py` の入力源は
  pack_stale / stale_bs / validate_fail / promotion_ready / events_watch / new_listings_irr の6本で、
  **out/kessan は入っていない**。
  実測(2026-08-11): 要審査は14社、そのうち7社が待ち行列に不在で、
  **その中に KLAC（当時の🟢投下可・判定「要審査: 警報:減損」）**がいた。
  ＝四半期点検が正しく異常を拾っているのに、**次の仕事に渡す配線が無かった**。

■ ⚠この道具は判定を作らない
  判定を下すのは `kessan_check.py`。ここがやるのは**その判定文を機械可読にするだけ**で、
  新しい線も刻みも作らない。Ω・四関門・売却規律・配分のどれにも触れない。

■ ⚠なぜ kessan_check.py に json を足さないのか
  あちらは**四半期・要ネットワーク**なので、直しても次の四半期まで出力が出ない。
  一方 out/kessan/*.txt は**既に repo にコミットされている**ので、そこから起こせば今日から効く。
  代償は「他の道具の出力テキストに依存する」こと——だから
  **判定行が読めないファイルは黙って飛ばさず `unparsed` に積む**（形が変わったら気づく）。

■ 形（kessan_check.py が書く1行目・2行目）
    {T} 点検日 YYYY-MM-DD  四半期末 YYYY-MM-DD
    判定: 要審査: 警報:減損 / 異常なし(機械判定) / 要審査: 点検不能（…）

使い方:
  python3 night/kessan_flags.py            画面に出す
  python3 night/kessan_flags.py --json     out/kessan_flags.json を書く
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
DIR = 'out/kessan'


def build():
    rows, unparsed = {}, []
    files = sorted(glob.glob(os.path.join(DIR, '*_qcheck*.txt')))
    for f in files:
        t = os.path.basename(f).split('_qcheck')[0]
        try:
            body = open(f, encoding='utf-8').read()
        except Exception as e:
            unparsed.append(dict(t=t, path=f, why=type(e).__name__))
            continue
        m = re.search(r'^判定:\s*(.+)$', body, re.M)
        if not m:
            # 形が変わった／途中で切れた。**「異常なし」と読まない**（絶対のルール7の親戚）
            unparsed.append(dict(t=t, path=f, why='「判定:」の行が無い'))
            continue
        v = m.group(1).strip()
        d = re.search(r'点検日\s*(\d{4}-\d{2}-\d{2})', body)
        q = re.search(r'四半期末\s*(\d{4}-\d{2}-\d{2})', body)
        rows[t] = dict(t=t, verdict=v, need=v.startswith('要審査'),
                       checked=d.group(1) if d else None,
                       qend=q.group(1) if q else None,
                       jp='_jp' in os.path.basename(f))
    return dict(generated=__import__('datetime').date.today().isoformat(),
                note=('kessan_check(.py/_jp.py) が out/kessan/*.txt に書いた判定を機械可読にしただけ。'
                      '**判定は作っていない**——線も刻みも kessan_check の側にある。'
                      'enqueue_reaudit と night/today.py が読む。'
                      '⚠unparsed は「判定行が読めなかった」＝**異常なしではない**。'),
                n=len(rows), n_need=sum(1 for r in rows.values() if r['need']),
                items=rows, unparsed=unparsed)


def main():
    o = build()
    need = sorted([r for r in o['items'].values() if r['need']], key=lambda r: r['t'])
    print('■ 四半期点検の旗（out/kessan/*.txt を機械可読にしただけ・判定は作っていない）')
    print('  点検済み %d社 / 要審査 %d社' % (o['n'], o['n_need']))
    for r in need:
        print('    ・%-6s %s  （点検日 %s）' % (r['t'], r['verdict'][:70], r['checked'] or '不明'))
    if o['unparsed']:
        print('\n  ⚠ 判定行が読めなかった %d件 — **「異常なし」ではない**' % len(o['unparsed']))
        for u in o['unparsed']:
            print('    ・%s（%s）… %s' % (u['t'], u['path'], u['why']))
    if AS_JSON:
        # 空書き込みの検問（audit_stale_bs:243 と同じ言葉）
        if not o['items']:
            print('\n⚠ out/kessan/*.txt が1件も読めない。**kessan_flags.json を書き換えない**'
                  '——空の旗は「点検して異常なし」ではない')
            return 1
        p = 'out/kessan_flags.json'
        json.dump(o, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('\n→ %s' % p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
