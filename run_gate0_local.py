# run_gate0_local.py — Claude Code / ローカル環境用の起動器（Colab不要）
# 実行: python run_gate0_local.py
# ①companyfacts.zip(検証母集団=全上場)が45日超なら削除→gate0が最新版を自動DL(母集団が毎年更新)
# ②holdings.json があれば gate0の HOLDINGS/WATCH を実行時に自動差し替え(本体無編集)
import os, json, re, time
BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
ZIPP = os.path.join(BASE, 'companyfacts.zip')
MAX_AGE_DAYS = 45
if os.path.exists(ZIPP):
    age = (time.time() - os.path.getmtime(ZIPP)) / 86400
    if age > MAX_AGE_DAYS:
        os.remove(ZIPP)
        print('■ companyfacts.zip は%d日前と古い → 削除。gate0が最新版を自動DL(母集団=全上場が更新される)' % int(age))
    else:
        print('■ companyfacts.zip は%d日前 → 再利用(十分新しい)' % int(age))
else:
    print('■ companyfacts.zip なし → gate0が最新版を自動DL(約1.4GB)')
p = os.path.join(BASE, 'gate0_v8_5.py')  # v8.5: 膜の開放(優先病名はpt不問で待ち行列)。v8.4=病名分類 v8.3=棚 v8.2=負資本+のれん椅子
src = open(p, encoding='utf-8').read()
hj = os.path.join(BASE, 'holdings.json')
if os.path.exists(hj):
    cfg = json.load(open(hj, encoding='utf-8'))
    H = [t.strip().upper() for t in (cfg.get('holdings') or []) if t.strip()]
    W = [t.strip().upper() for t in (cfg.get('watch') or []) if t.strip()]
    newH = 'HOLDINGS = ' + (repr(set(H)) if H else 'set()')
    newW = 'WATCH = HOLDINGS | ' + (repr(set(W)) if W else 'set()')
    src, n1 = re.subn(r'HOLDINGS\s*=\s*\{[^}]*\}', lambda m: newH, src, count=1)
    src, n2 = re.subn(r'WATCH\s*=\s*HOLDINGS\s*\|\s*\{[^}]*\}', lambda m: newW, src, count=1)
    if n1 and n2:
        print('■ holdings.json 適用: 保有%d件 / 追加WATCH %d件(本体は無編集)' % (len(H), len(W)))
    else:
        print('▲ 差し替え位置が見つからない(n1=%d,n2=%d) → 本体の値のまま実行' % (n1, n2))
else:
    print('■ holdings.json なし → gate0本体の HOLDINGS/WATCH をそのまま使用')
print('■ 実行:', p)
exec(compile(src, p, 'exec'))

# ⚠2026-08-10新設: **実行印**。回転盤(night/ops_status.py)の gate0 は
#   `git_date('gate1_queue.json')` で最終実行を測っていたが、実測ではその直近コミットが
#   門0とまったく無関係の作業だった（予実台帳の基準印・acq5の裏取り）。
#   **年次作業ほど止まったことを検出したいのに、年次作業ほど測り方が弱い**という倒錯。
#   ここで実行日そのものを残せば histval/profiles と同じ強さになる。
import datetime as _dt, json as _json
try:
    _q = _json.load(open(os.path.join(BASE, 'gate1_queue.json'), encoding='utf-8'))
    _n = len(_q if isinstance(_q, list) else (_q.get('queue') or []))
except Exception:
    _n = None
_json.dump({'generated': _dt.date.today().isoformat(), 'queue_n': _n,
            'note': '米国門0発掘の実行印。gate1_queue.json のコミット日ではなく**実行日**を残す'},
           open(os.path.join(BASE, 'out', 'gate0_run.json'), 'w', encoding='utf-8'),
           ensure_ascii=False, indent=1)
print('■ 実行印: out/gate0_run.json')
