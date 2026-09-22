#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/pack_fields.py — **パックが持つ採点欄を数え、門が「台帳の取り残し」を自力で検出できるようにする**
                        （2026-09-22新設・ユーザー指示「入れて」）

■ なぜ要るか（実害から作った）
  2026-09-22、ユーザーの画面から **LRCX が投下可に出てこなかった**。配信は正しく更新されていて
  （curl で v9.9.186・CCF_SEATS=5・新しい堀の重みを確認）、原因は
  **ブラウザの台帳(g7:)が v9.9.181 より前のパックのまま**だったこと——
  その版で新設した `acqS5` を台帳が1件も持っていなかった。
  再現: `node night/score_all.js --set acqS5=` で**まったく同じ画面**が出る
  （投下可 CW/MSFT/V/MCO/IDXX・LRCX は 81.2 で IDXX と同点になり6位へ落ちる）。

  ⚠ **「↻全再採点」では直らない**——あれは保存済み data に現行 compute() を通すだけで
  パックを読み直さないので、**欄そのものが無い**記録には何も足せない。
  必要なのは Ⅵの「⭳ 全パック一括取込」だが、**どの変更でどれを押すのかは人が覚えているしかなかった**。
  ＝手順書に書いてあるのに、押し忘れが**外から見えない**（回転盤を作った理由とまったく同じ型）。

■ 何を出すか
  out/pack_fields.json = {asof, n_packs, fields:{欄名: 持っているパック数}, tickers:[...]}
  門の `ccfLedgerStale()` がこれを読み、**台帳の全記録を走査して**
  「パックは広く持っているのに、台帳では1件も持っていない欄」を名指しする。

■ ★欄の一覧は index.html の `const map={...}` から読む（二重に持たない・v9.9.65の掟）
  ここに欄名を書き写すと、門に欄が増えたとき**この検査だけが古い一覧で黙る**
  ——「検査が回ったつもりで回っていない」型をこの道具自身で再演することになる。

■ ルール7（欠測をゼロと読むな）
  パックに欄が無いことと、値が空であることを分けて数える。**値がある件数**だけを count する
  （空欄は「測っていない」であって「持っている」ではない）。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def gate_fields():
    """門の applyFields が受け取る欄名（index.html の const map が正本）"""
    h = open('index.html', encoding='utf-8').read()
    m = re.search(r'const map=\{(.*?)\};', h, re.S)
    if not m:
        sys.exit('index.html の const map={...} が読めない——門の構造が変わった可能性がある。'
                 'ここで黙って既定の一覧へ倒すと、この検査が古い欄で回り続ける（ルール7の親戚）ので止める。')
    return [k for k, _ in re.findall(r"(\w+)\s*:\s*'(\w+)'", m.group(1))]


def main():
    fields = gate_fields()
    # 採点に関わらない欄は数えない（名前・市場データの一部は取込のたびに変わる）
    SKIP = {'nm'}
    fields = [f for f in fields if f not in SKIP]

    packs = sorted(x for x in os.listdir('out') if x.endswith('_gate_pack.json'))
    cnt = {f: 0 for f in fields}
    tick = []
    for fn in packs:
        try:
            d = json.load(open(os.path.join('out', fn), encoding='utf-8'))
        except Exception:
            continue
        dd = d.get('data', d)
        t = fn[:-len('_gate_pack.json')]
        tick.append(t)
        for f in fields:
            v = dd.get(f)
            if v is not None and v != '':
                cnt[f] += 1

    out = {
        'asof': __import__('datetime').date.today().isoformat(),
        'tool': 'night/pack_fields.py',
        'role': '門の ccfLedgerStale() が「台帳が古くて欄を持っていない」を自力で検出するための材料。'
                '判定にも採点にも使わない（表示だけ）',
        'n_packs': len(tick),
        'fields': cnt,
        'tickers': tick,
        'note': '欄の一覧は index.html の const map から読んでいる（写していない）。'
                'count は**値が入っているパックの数**＝空欄は数えない（ルール7）',
    }
    json.dump(out, open('out/pack_fields.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('■ パックが持つ採点欄（night/pack_fields.py）')
    print('  パック %d件 ／ 門が受け取る欄 %d本' % (len(tick), len(fields)))
    top = sorted(cnt.items(), key=lambda kv: -kv[1])
    print('  よく埋まっている欄: ' + ', '.join('%s %d' % (k, v) for k, v in top[:6]))
    thin = [k for k, v in top if v == 0]
    if thin:
        print('  ⚠ どのパックにも値が無い欄 %d本: %s' % (len(thin), ', '.join(thin)))
    print('→ out/pack_fields.json')


if __name__ == '__main__':
    main()
