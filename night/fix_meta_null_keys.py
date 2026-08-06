#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fix_meta_null_keys.py — **_meta.nulls の複合キーを欄ごとのキーへ展開する**（2026-08-06新設）

なぜ要るか:
  空欄の理由は `_meta.nulls` に書く決まり（絶対のルール8）。ところが**キーの付け方が揃っておらず**、
  `dom_irr_rep_dur` `gr/gcap` `gls/idx/indG` のように**複数欄を一つのキーにまとめた**パックがある。
  監査（audit_gate / ccfAudit の okKeys）は**欄名の完全一致**で「根拠あり」を判定するので、
  こういうキーは**根拠が書いてあるのに認識されない**。

  実害の出方（2026-08-06に踏んだ）: roicGap を段階減点にしたら ADP が Ω70.2→75.0 と
  判定圏(Ω72+)へ入り、**未解決警告が 0件→5件**になった。中身を見ると erosion/geopol/moatdecay の
  3件は `erosion_disrupt_moatdecay_geopol` という複合キーに
  「蝕/限/集/循セクション『ヒットなし』…証拠なし→null」と**ちゃんと書いてあった**。
  ＝**根拠が無いのではなく、監査が読める形になっていなかった**。
  91パックで kenshi が配列でなく文字列だった事故（validate_packs が検出）と同じ「_metaの型」の問題。

**何をしないか（重要）**:
  値のテキストに欄名が出てくるだけのキー（例 `市場データ`: 中身に "per/px/..." と列挙）は**展開しない**。
  そこを展開すると、たとえば「per が無くて門Xが評価不能」という**現に効いている穴**が
  ✓検算済に化けて静かに消える。**警告を消すために基準を緩めるのは逆走**（この台帳が
  「鳴りすぎる警報は鳴らないのと同じ」と書いているのと対の関係）。
  展開するのは**キー自身が欄名で構成されている**ものだけ＝機械的に曖昧さがない範囲。

使い方:
  python3 night/fix_meta_null_keys.py            対象を数えるだけ（何も書かない）
  python3 night/fix_meta_null_keys.py --write    実際に展開する
  python3 night/fix_meta_null_keys.py --t ADP    1銘柄だけ
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'out')

FIELDS = set((
    'roic roicg roicEx nde z gpa accr gm gmt roict cagr fcf ni sbc dilNet acc eq acq5 eps expiry '
    'moatdecay erosion disrupt dom irr rep dur moatW geopol nrr beta per perF evebit px shy gr gcap '
    'analysts instOwn mcap p1 p2 p3 p4 f1 f2 f3 f4 f5 roiic roiic5 sht rak idx indG gls founder fin '
    'dep erdate ddate'
).split())

WRITE = '--write' in sys.argv
ONE = None
if '--t' in sys.argv:
    ONE = sys.argv[sys.argv.index('--t') + 1]


def split_key(k):
    """キー自身が欄名で構成されているときだけ、その欄名の一覧を返す。
       ノイズ語（note/解消/日付など）は無視するが、**欄名が1つも無ければ展開しない**。"""
    parts = [p for p in re.split(r'[_/、,・\s]+', k) if p]
    hits = [p for p in parts if p in FIELDS]
    if not hits:
        return []
    # 「欄名でない部分」が意味を持つ注記（p1_note など）は、欄名が1つだけなら
    # そのままでも監査は読めない（キー全体が一致しないため）→ 展開してよい
    return hits


def main():
    files = sorted(glob.glob(os.path.join(OUT, '*_gate_pack.json')))
    if ONE:
        files = [f for f in files if os.path.basename(f).startswith(ONE + '_')]
    changed, total_keys, rows = 0, 0, []
    for f in files:
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        meta = d.get('_meta')
        if not isinstance(meta, dict):
            continue
        nulls = meta.get('nulls')
        if not isinstance(nulls, dict):
            continue
        ev = meta.get('evidence') if isinstance(meta.get('evidence'), dict) else {}
        add = {}
        for k, v in list(nulls.items()):
            if k in FIELDS:
                continue
            for fld in split_key(k):
                if fld in nulls or fld in add:
                    continue           # 既に個別キーがあるなら触らない
                # **値が入っている欄に null 理由を書かない**（2026-08-06に自分で踏んだ）。
                #   実例 ADP の `dom_irr_rep_dur` は「irr/rep/dur は充填済・dom は既存判定を維持」で、
                #   4欄とも**値がある**。ここへ nulls を足すと「空欄の理由」が
                #   埋まっている欄に付き、_meta が意味を失う（91パックの kenshi 型崩れと同じ壊し方）。
                val = d.get(fld, None)
                if val is not None and str(val).strip() != '':
                    continue
                # 既に evidence がある欄も触らない（根拠は evidence 側で足りている）
                if fld in ev:
                    continue
                add[fld] = v
        if not add:
            continue
        t = os.path.basename(f).replace('_gate_pack.json', '')
        rows.append((t, sorted(add)))
        changed += 1
        total_keys += len(add)
        if WRITE:
            nulls.update(add)
            with open(f, 'w', encoding='utf-8') as fh:
                json.dump(d, fh, ensure_ascii=False, indent=1)

    print('■ _meta.nulls の複合キーを欄ごとのキーへ展開'
          + ('（--write で実行）' if WRITE else '（数えるだけ・--write で実行）'))
    for t, ks in rows[:24]:
        print(f'   {t:<8} +{len(ks)}欄  {" ".join(ks)}')
    if len(rows) > 24:
        print(f'   …他{len(rows)-24}銘柄')
    print(f'\n   対象 {changed}パック / 追加 {total_keys}欄')
    print('   ※ 値のテキストにだけ欄名が出るキー（市場データ 等）は**意図的に展開していない**'
          '——現に効いている穴が✓検算済に化けるため')
    return 0


if __name__ == '__main__':
    sys.exit(main())
