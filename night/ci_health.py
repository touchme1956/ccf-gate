#!/usr/bin/env python3
"""night/ci_health.py — 自動化そのものの健康診断（2026-08-18新設）

【なぜ要るか — 今日の実測が理由のすべて】
  回転盤(night/ops_status.py)は**成果物ファイルの日付しか見ていない**。だから
  workflow が「走って失敗した」ことを構造的に知らない。実測(2026-08-18):
    market.yml は 8/14 と 8/17 に **走った**。株価も為替もパックへの反映も**全部成功**し、
    `[main 3e9ceb8] market prices 2026-08-17｜64社` と**コミットまで作った**。
    落ちたのは最後の `git push` だけ——`! [rejected] main -> main (fetch first)`。
    remote が進んだだけで弾かれ、**70ファイル分の成果が runner ごと捨てられた**。
  ところが回転盤の表示は **「止まっている疑い: 株価・盤データ」**。
  ＝**「動いていない」と「動いて失敗している」を同じ言葉にしていた**。
  直し方がまったく違う（前者は起動の問題／後者は push の衝突）のに、盤は区別を出せない。

【この器がやること／やらないこと】
  やる  : 各 workflow の**直近の run の結末**を GitHub API で読み、失敗していれば
          **どのステップで落ちたか**まで出す。📋今日(night/today.py)がそれを表示する。
  やらない: 判定・採点・関門にはいっさい触れない。**読むだけ**。

【絶対のルール7】鍵が無い/APIが読めないときは **「異常なし」と言わない**。
  `blind` に理由を積んで、📋今日が「測れなかった」として出す。
  ——`notify_issues.py` が out/ を全消ししても「✓ 行動が要ることは無い」と出していたのと同じ穴を作らない。

【空書き込みの検問】1本も読めなければ **out/ci_health.json を書き換えない**（exit 1）。
  採取が壊れたときに「全部 success」で上書きされると、見張りが黙って消える
  （audit_stale_bs:243 と同じ言葉）。

使い方:
  python3 night/ci_health.py            人が読む形
  python3 night/ci_health.py --write    out/ci_health.json を書く（CI用）
  ※ 認証は GITHUB_TOKEN / GH_TOKEN。公開リポジトリでも Actions API は**未認証だと403**なので、
     鍵が無ければ測れない。
     ⚠2026-09-19訂正: **「Actions では自動で入る」は誤り**だった。`GITHUB_TOKEN` は式
       `${{ github.token }}` からは読めるが、**ステップの `env:` に書かないとプロセスには渡らない**。
       ci.yml がそれを書いていなかったので、この器は新設(2026-08-18)から2026-09-19まで
       **CIで一度も書き込めていなかった**（空書き込みの検問で正しく書かずに落ち、
       `continue-on-error` がそれを緑に隠し、回転盤には `nokey`＝鍵待ちと出ていた）。
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'out' / 'ci_health.json'
REPO = os.environ.get('GITHUB_REPOSITORY', 'touchme1956/ccf-gate')
TOKEN = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN') or ''

# 見張る対象は .github/workflows/*.yml の実在から作る（列挙を書き写さない＝足したら自動で入る）
def workflows():
    d = ROOT / '.github' / 'workflows'
    return sorted(p.name for p in d.glob('*.yml')) if d.is_dir() else []

def api(path):
    req = urllib.request.Request(f'https://api.github.com{path}',
        headers={'Accept': 'application/vnd.github+json',
                 'User-Agent': 'ccf-gate ci_health',
                 **({'Authorization': f'Bearer {TOKEN}'} if TOKEN else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def build():
    rows, blind = [], []
    if not TOKEN:
        blind.append('GITHUB_TOKEN / GH_TOKEN が無い——Actions API は公開リポジトリでも未認証だと403。'
                     'CI ではステップの env: に `${{ github.token }}` を書けば渡る'
                     '（**自動では入らない**。ci.yml が書き忘れていて2026-09-19まで一度も測れていなかった）。'
                     '手元で見たいなら GH_TOKEN を渡すこと')
    for wf in workflows():
        if not TOKEN:
            continue
        try:
            d = api(f'/repos/{REPO}/actions/workflows/{wf}/runs?per_page=1')
        except Exception as e:
            blind.append(f'{wf}: run を読めなかった（{e}）')
            continue
        runs = d.get('workflow_runs') or []
        if not runs:
            rows.append({'wf': wf, 'conclusion': None, 'note': 'まだ一度も走っていない'})
            continue
        r = runs[0]
        row = {'wf': wf, 'run_id': r.get('id'), 'at': r.get('created_at'),
               'event': r.get('event'), 'status': r.get('status'),
               'conclusion': r.get('conclusion'), 'url': r.get('html_url'),
               'branch': r.get('head_branch')}
        # 失敗したときだけ、どのステップで落ちたかを取りに行く（成功時は余計なAPIを叩かない）
        if r.get('conclusion') == 'failure':
            try:
                j = api(f"/repos/{REPO}/actions/runs/{r['id']}/jobs")
                bad = [s['name'] for job in j.get('jobs', [])
                       for s in job.get('steps', []) if s.get('conclusion') == 'failure']
                row['failed_steps'] = bad
            except Exception as e:
                row['failed_steps'] = None
                blind.append(f'{wf}: 失敗したステップ名を読めなかった（{e}）')
        rows.append(row)
    return {'generated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'repo': REPO,
            'note': 'workflow の直近の run の結末。判定には一切使わない（📋今日の表示のみ）。'
                    '⚠ blind が空でないときは「異常なし」と読まないこと',
            'rows': rows, 'blind': blind,
            'failed': [r['wf'] for r in rows if r.get('conclusion') == 'failure']}

def main():
    d = build()
    write = '--write' in sys.argv
    if '--json' in sys.argv:
        print(json.dumps(d, ensure_ascii=False, indent=1)); return 0
    print(f"■ 自動化の健康診断（{d['repo']}）")
    if d['blind']:
        print(f"  ⚠ 測れなかった {len(d['blind'])}件——**「異常なし」ではない**")
        for b in d['blind'][:6]:
            print(f"     {b}")
    for r in d['rows']:
        c = r.get('conclusion')
        mark = '✓' if c == 'success' else ('✗' if c == 'failure' else '·')
        extra = ''
        if c == 'failure' and r.get('failed_steps'):
            extra = f"  ← 落ちたステップ: {' / '.join(r['failed_steps'])}"
        print(f"  {mark} {r['wf']:14s} {str(r.get('at') or r.get('note') or ''):22s} {str(c or ''):9s}{extra}")
    if d['failed']:
        print(f"\n  ★失敗 {len(d['failed'])}本: {' '.join(d['failed'])}")
        print("    ⚠『成果物が古い』と『走って失敗している』は直し方が違う。回転盤は前者しか言えない")
    if write:
        # 空書き込みの検問: 1本も読めなければ既存を潰さない
        if not d['rows']:
            print('\n⚠ 1本も読めなかったので out/ci_health.json は書き換えない（空書き込みの検問）')
            return 1
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(f'\n→ {OUT.relative_to(ROOT)}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
