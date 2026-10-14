#!/usr/bin/env python3
"""night/longrun1990_fetch.py — 1990年〜今の長い検証（longrun1990）の Part B の【取得だけ】（成績は計算しない）

事前登録 out/longrun1990_prereg.json（4dc44296）の data.B_stock_level のとおり、
out/longrun1990_universe.json の6,026本と ^SP500TR の Yahoo 月足（1985-01-01〜2026-01-01・配当と分割つき）を
生のまま out/_mw_cache/lr1990_yh/（gitignore）へ置く。再実行は取れていない本だけを取りに行く（再開できる）。
  - 並列6本まで・404 と 400（Yahoo が記号を知らない）は「無し」と記録して再試行しない・429/5xx/通信の失敗は 2,4,8,16,32 秒あけて再試行
  - 状態は _status.json（{記号: 'ok' | 'http404' | 'http400' | 'fail:…'}）
使い方: python3 night/longrun1990_fetch.py
"""
import concurrent.futures as cf
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(BASE, 'out', '_mw_cache', 'lr1990_yh')
UA = {'User-Agent': 'Mozilla/5.0 (ccf-gate research; contact via github touchme1956/ccf-gate)'}
P1, P2 = 473385600, 1767225600          # 1985-01-01 / 2026-01-01（UTC）
BENCH = '^SP500TR'


def fname(t):
    return os.path.join(DIR, t.replace('^', 'IDX_').replace('/', '_') + '.json.gz')


def url(t):
    return (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}'
            f'?period1={P1}&period2={P2}&interval=1mo&events=div%7Csplit')


def fetch(t):
    p = fname(t)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return t, 'ok'
    err = None
    for i in range(6):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url(t), headers=UA), timeout=60).read()
            tmp = f'{p}.{os.getpid()}.tmp'
            with gzip.open(tmp, 'wb') as f:
                f.write(b)
            os.replace(tmp, p)
            return t, 'ok'
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return t, f'http{e.code}'           # 記号を知らない（再試行しても同じ）
            err = f'http{e.code}'
        except Exception as e:  # noqa
            err = type(e).__name__
        if i < 5:
            time.sleep(2 ** (i + 1))
    return t, f'fail:{err}'


def main():
    os.makedirs(DIR, exist_ok=True)
    uni = json.load(open(os.path.join(BASE, 'out', 'longrun1990_universe.json')))
    ticks = [BENCH] + [r[1] for r in uni['rows']]
    sp = os.path.join(DIR, '_status.json')
    status = json.load(open(sp)) if os.path.exists(sp) else {}
    todo = [t for t in ticks if status.get(t) not in ('ok', 'http404', 'http400')]
    print(f'全 {len(ticks)} 本・残り {len(todo)} 本', flush=True)
    done = 0
    with cf.ThreadPoolExecutor(6) as ex:
        for t, s in ex.map(fetch, todo):
            status[t] = s
            done += 1
            if done % 200 == 0:
                json.dump(status, open(sp, 'w'))
                c = {}
                for v in status.values():
                    k = v.split(':')[0]
                    c[k] = c.get(k, 0) + 1
                print(f'{done}/{len(todo)} {c}', flush=True)
    json.dump(status, open(sp, 'w'))
    c = {}
    for v in status.values():
        k = v.split(':')[0]
        c[k] = c.get(k, 0) + 1
    print('終わり', c, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
