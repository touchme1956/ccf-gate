#!/usr/bin/env python3
"""night/packs_index.py — 門の一括取込の目録 out/packs_index.json を作る（パックの指紋つき・2026-10-14）

ユーザーの問い「門の個別銘柄が入れ替わった場合はきちんと入れ替わるようになってる？」から。
端末の台帳（localStorage の g7:）は、パックが repo で新しくなっても（見直し・粗利率の充填・毎営業日の株価の反映）
「⭳ 全パック一括取込」を押すまで古いままで、それを知らせる仕組みも無かった（ccfCheckPacksFresh は台帳に無い社しか見ない）。
→ 目録にパックごとの指紋を足し、門が取り込んだときに記録へ写した指紋（pfx）と比べて、新しくなった社だけを自動で取り込み直す。

  packs: ファイル名の一覧（従来どおり・⭳一括取込と孤児レコードの関門〔v9.9.102〕の母集団）
  fp:    パックごとの指紋＝ファイルのバイト列の sha1 の先頭12桁。値の意味は「この版のパック」だけ
         （門は指紋を計算し直さない＝索引が古くても取り込みが空回りし続けることは無い。索引を作り直すと次に開いたとき取り込む）

使い方:
  python3 night/packs_index.py --write   # 書く（make_chunks.py・market.yml の株価の反映の後・ops.yml が呼ぶ）
  python3 night/packs_index.py --check   # 索引が実パックと合っているか（合っていなければ終了コード1・ci.yml は表示だけ）
"""
import glob, hashlib, json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out', 'packs_index.json')


def build():
    files = sorted(os.path.basename(f) for f in glob.glob(os.path.join(BASE, 'out', '*_gate_pack.json')))
    fp = {}
    for f in files:
        with open(os.path.join(BASE, 'out', f), 'rb') as h:
            fp[f] = hashlib.sha1(h.read()).hexdigest()[:12]
    return {'packs': files, 'fp': fp}


def write():
    idx = build()
    with open(OUT, 'w', encoding='utf-8') as h:
        json.dump(idx, h, ensure_ascii=False, indent=0)
    return idx


def check():
    try:
        cur = json.load(open(OUT, encoding='utf-8'))
    except Exception as e:
        print(f'✗ out/packs_index.json を読めない: {e}')
        return 1
    want = build()
    only_i = sorted(set(cur.get('packs') or []) - set(want['packs']))
    only_a = sorted(set(want['packs']) - set(cur.get('packs') or []))
    fp0 = cur.get('fp') or {}
    stale = sorted(f for f in want['packs'] if f in fp0 and fp0[f] != want['fp'][f])
    nofp = sorted(f for f in want['packs'] if f not in fp0)
    print(f"索引 {len(cur.get('packs') or [])}件 / 実パック {len(want['packs'])}件 / 指紋 {len(fp0)}件")
    if only_i: print('⚠ 索引にあるが実体が無い:', only_i[:20])
    if only_a: print('⚠ 実体はあるが索引に無い（一括取込で台帳へ入らない）:', only_a[:20])
    if stale: print(f'⚠ 指紋が古い {len(stale)}件（門が新しくなったパックに気づかない）:', stale[:20])
    if nofp: print(f'⚠ 指紋が無い {len(nofp)}件:', nofp[:20])
    if only_i or only_a or stale or nofp:
        print('→ python3 night/packs_index.py --write で作り直す')
        return 1
    print('✓ 一致（ファイル名と指紋）')
    return 0


if __name__ == '__main__':
    if '--check' in sys.argv:
        sys.exit(check())
    if '--write' in sys.argv:
        idx = write()
        print(f"→ out/packs_index.json 更新（{len(idx['packs'])}パック・指紋つき）")
        sys.exit(0)
    print(__doc__)
