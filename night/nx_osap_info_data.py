#!/usr/bin/env python3
"""night/nx_osap_info_data.py — 角度 nx_osap_info（情報の仲介者の信号）の取得と整形だけ（成績は計算しない・読むだけ）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…
別のSessionで検証していない新たな分析を同じ内容でしてほしい」。事前登録は out/nx_osap_info_prereg.json。

何をするか（リターンの平均・t・累積・勝率は一度も計算しない）
  fetch     OSAP（Chen-Zimmermann・openassetpricing.com 2025-10 版）のファイルを out/_nx_cache/ へ取る
  ports     規則の台帳 RULES が使うポートフォリオの月次リターン（%のまま）と組の銘柄数を切り出し、
            out/_nx_cache/nx_osap_info_ports.json へ。sha256 を刻む（測る道具はこの値と一致しなければ止まる）
  turnover  OSAP の銘柄ごとの信号（signed_predictors_dl_wide・83億バイト）から、OSAP の組み方を写して
            良い側の組の毎月の入れ替わり（片道の回転）を出す → out/_nx_cache/nx_osap_info_turnover.json。
            時価（Size）は OSAP の公開ファイルに無いので、2か月前の売買代金 DolVol を時価の代わりの重みに使う
  shape     期間・欠け・組の銘柄数だけを表示（リターンは見ない）
  all       全部

約束
- OSAP の ret は **% 表記の総リターン**（CRSP の ret に上場廃止のリターンを合成・欠けた上場廃止は NYSE/AMEX −35%・Nasdaq −55%。
  Portfolios/Code/11_ProcessCRSP.R）。無リスク金利は引いていない＝French の Mkt（総リターン）とそのまま比べられる
- 組の時価加重は前月末の時価 melag（同じファイル）。信号は1か月遅らせて使われている（01_PortfolioFunction.R の signallag）
- OSAP は信号に符号（SignalDoc の Sign）を掛けてから並べるので、**番号の大きい組（05・10・離散なら最大の値）が常に論文の予言する良い側**
"""
import argparse, array, csv, hashlib, io, json, math, os, sys, time, urllib.request, zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from nx_common import CACHE, UA  # noqa: E402

DRIVE = 'https://drive.usercontent.google.com/download?id={}&export=download&confirm=t'
FILES = {  # 鍵: (Google Drive の id, キャッシュの名前)。フォルダ https://drive.google.com/drive/folders/1qQDuTsnyvWfEJR6nPBQZ8xxlq6bkLG_y
    'doc': ('1Sev9s6cPFUGgxp1pFiej0lGzpsMqJCI2', 'osap_SignalDoc.csv'),
    'q5vw': ('1ef905SSlCDyh1KU9W1tJs5sfBFz0HPUt', 'osap_PredictorAltPorts_QuintilesVW.zip'),
    'd10vw': ('1_1WWZqilrt1gleeyAFwjv5aobd0QRbS3', 'osap_PredictorAltPorts_DecilesVW.zip'),
    'vwf': ('1KZE3FgBxFPaNOyxoRw63ubZHOlkR9kZW', 'osap_PredictorAltPorts_LiqScreen_VWforce.zip'),
    'op': ('1g7w-yQ6Cg2qbMEkER9Q3vgns4JszXQo6', 'osap_PredictorPortsFull.csv'),
    'ff93': ('1pDRMNTOvRfvooAzYOmG9sBBz74mUO80Q', 'osap_PredictorAltPorts_FF93style.zip'),  # 2×3（6月に年1回・NYSE の30/70%点と時価の中央値）
    'placebo': ('1ciopYrT7e9tzKCt8f1he6uwJFiaD1ZkE', 'osap_PlaceboPortsFull.zip'),
    'firm': ('1avFIMjz_7LoF3p3nO26eqLW5KdRTOdhW', 'osap_signed_predictors_dl_wide.zip'),
}
PORTS_OUT = os.path.join(CACHE, 'nx_osap_info_ports.json')
TURN_OUT = os.path.join(CACHE, 'nx_osap_info_turnover.json')
MIN_N = 20  # 良い側の組の銘柄数がこれを下回る月が最後に現れた月の翌月から評価する（形だけで決めた機械的な規則）

# ───────────── 規則の台帳（事前登録と同じ。測る道具はここを import する＝写さない） ─────────────
# file: q5vw=五分位・時価加重 / d10vw=十分位・時価加重 / vwf=論文の組み方のまま時価加重に強制 / op=論文の組み方（重みも論文どおり）
#       ff93=Fama-French 1993 型の2×3（毎年6月の信号だけで組み7月〜翌6月持つ・大型〔NYSE の時価の中央値超〕×良い側〔NYSE の70%点超〕＝BH）
# port: 良い側の組。start: 評価を始める月（None なら MIN_N の規則で機械的に決まる）
RULES = [
    # 主の族 P（長い歴史・criteria_long_history）
    dict(id='P1_ShortInterest_q5vw', fam='P', signal='ShortInterest', file='q5vw', port='05'),
    dict(id='P2_CredRatDG_notDG_vwf', fam='P', signal='CredRatDG', file='vwf', port='02', start=198501),
    dict(id='P3_REV6_q5vw', fam='P', signal='REV6', file='q5vw', port='05'),
    dict(id='P4_AnalystRevision_q5vw', fam='P', signal='AnalystRevision', file='q5vw', port='05'),
    dict(id='P5_ForecastDispersion_q5vw', fam='P', signal='ForecastDispersion', file='q5vw', port='05'),
    dict(id='P6_fgr5yrLag_q5vw', fam='P', signal='fgr5yrLag', file='q5vw', port='05'),
    # 主の族 Q（短い標本・criteria_short_sample）
    dict(id='Q1_ConsRecomm_strongbuy_op', fam='Q', signal='ConsRecomm', file='op', port='02'),
    dict(id='Q2_ChangeInRecommendation_q5vw', fam='Q', signal='ChangeInRecommendation', file='q5vw', port='05'),
    dict(id='Q3_skew1_q5vw', fam='Q', signal='skew1', file='q5vw', port='05'),
    # 探索 XL（長い歴史の格付けで・探索と明記）
    dict(id='XL1_ShortInterest_d10vw', fam='XL', signal='ShortInterest', file='d10vw', port='10'),
    dict(id='XL2_REV6_d10vw', fam='XL', signal='REV6', file='d10vw', port='10'),
    dict(id='XL3_AnalystRevision_d10vw', fam='XL', signal='AnalystRevision', file='d10vw', port='10'),
    dict(id='XL4_ForecastDispersion_d10vw', fam='XL', signal='ForecastDispersion', file='d10vw', port='10'),
    dict(id='XL5_fgr5yrLag_d10vw', fam='XL', signal='fgr5yrLag', file='d10vw', port='10'),
    dict(id='XL6_EarningsForecastDisparity_q5vw', fam='XL', signal='EarningsForecastDisparity', file='q5vw', port='05'),
    dict(id='XL7_sfe_q5vw', fam='XL', signal='sfe', file='q5vw', port='05'),
    dict(id='XL8_FEPS_q5vw', fam='XL', signal='FEPS', file='q5vw', port='05'),
    dict(id='XL9_AnalystValue_q5vw', fam='XL', signal='AnalystValue', file='q5vw', port='05'),
    dict(id='XL10_AOP_q5vw', fam='XL', signal='AOP', file='q5vw', port='05'),
    dict(id='XL11_PredictedFE_q5vw', fam='XL', signal='PredictedFE', file='q5vw', port='05'),
    dict(id='XL12_ExclExp_q5vw', fam='XL', signal='ExclExp', file='q5vw', port='05'),
    dict(id='XL13_ChNAnalyst_notdecl_vwf', fam='XL', signal='ChNAnalyst', file='vwf', port='02'),
    dict(id='XL14_ChForecastAccrual_vwf', fam='XL', signal='ChForecastAccrual', file='vwf', port='02'),
    dict(id='XL15_DelBreadth_q5vw', fam='XL', signal='DelBreadth', file='q5vw', port='05'),
    dict(id='XL17_ShortInterest_BH', fam='XL', signal='ShortInterest', file='ff93', port='BH'),
    dict(id='XL18_REV6_BH', fam='XL', signal='REV6', file='ff93', port='BH'),
    dict(id='XL19_AnalystRevision_BH', fam='XL', signal='AnalystRevision', file='ff93', port='BH'),
    dict(id='XL20_ForecastDispersion_BH', fam='XL', signal='ForecastDispersion', file='ff93', port='BH'),
    dict(id='XL21_fgr5yrLag_BH', fam='XL', signal='fgr5yrLag', file='ff93', port='BH'),
    dict(id='XL16_MIX6', fam='XL', signal='MIX', parts=['P1_ShortInterest_q5vw', 'P2_CredRatDG_notDG_vwf', 'P3_REV6_q5vw',
                                                       'P4_AnalystRevision_q5vw', 'P5_ForecastDispersion_q5vw', 'P6_fgr5yrLag_q5vw']),
    # 探索 XS（短い標本の格付けで・探索と明記）
    dict(id='XS1_UpRecomm_vwf', fam='XS', signal='UpRecomm', file='vwf', port='02'),
    dict(id='XS2_DownRecomm_notDG_vwf', fam='XS', signal='DownRecomm', file='vwf', port='02'),
    dict(id='XS3_Recomm_ShortInterest_vwf', fam='XS', signal='Recomm_ShortInterest', file='vwf', port='02'),
    dict(id='XS4_SmileSlope_q5vw', fam='XS', signal='SmileSlope', file='q5vw', port='05'),
    dict(id='XS5_CPVolSpread_q5vw', fam='XS', signal='CPVolSpread', file='q5vw', port='05'),
    dict(id='XS6_RIVolSpread_q5vw', fam='XS', signal='RIVolSpread', file='q5vw', port='05'),
    dict(id='XS7_dVolCall_q5vw', fam='XS', signal='dVolCall', file='q5vw', port='05'),
    dict(id='XS8_dVolPut_q5vw', fam='XS', signal='dVolPut', file='q5vw', port='05'),
    dict(id='XS9_dCPVolSpread_q5vw', fam='XS', signal='dCPVolSpread', file='q5vw', port='05'),
    dict(id='XS10_OptionVolume1_q5vw', fam='XS', signal='OptionVolume1', file='q5vw', port='05'),
    dict(id='XS11_OptionVolume2_q5vw', fam='XS', signal='OptionVolume2', file='q5vw', port='05'),
    dict(id='XS12_ChangeInRecommendation_d10vw', fam='XS', signal='ChangeInRecommendation', file='d10vw', port='10'),
    dict(id='XS13_skew1_d10vw', fam='XS', signal='skew1', file='d10vw', port='10'),
    dict(id='XS15_ChangeInRecommendation_BH', fam='XS', signal='ChangeInRecommendation', file='ff93', port='BH'),
    dict(id='XS16_skew1_BH', fam='XS', signal='skew1', file='ff93', port='BH', end=202306),  # 最後の6月の組（2022-06）を1年持った所まで（その後は古い組が引き継がれているだけ）
    dict(id='XS14_MIX3', fam='XS', signal='MIX', parts=['Q1_ConsRecomm_strongbuy_op', 'Q2_ChangeInRecommendation_q5vw', 'Q3_skew1_q5vw']),
    # 報告のみ R（格付けしない）
    dict(id='R_CredRatDG_from1970_vwf', fam='R', signal='CredRatDG', file='vwf', port='02', start=197003),
    dict(id='R_IO_ShortInterest_q5vw', fam='R', signal='IO_ShortInterest', file='q5vw', port='05', start='first'),
]
# 論文どおりの組（op）の良い側と、五分位（または離散）の買い−売り LS は報告のみ（下の REPORT_PORTS）
MAIN_SIGNALS = ['ShortInterest', 'CredRatDG', 'REV6', 'AnalystRevision', 'ForecastDispersion', 'fgr5yrLag',
                'ConsRecomm', 'ChangeInRecommendation', 'skew1']
REPORT_PORTS = {  # 報告のみで使う組（LS・論文どおりの良い側・悪い側）
    'q5vw': {s: ['01', '05', 'LS'] for s in ['ShortInterest', 'REV6', 'AnalystRevision', 'ForecastDispersion', 'fgr5yrLag',
                                             'ChangeInRecommendation', 'skew1']},
    'vwf': {'CredRatDG': ['01', '02', 'LS'], 'ConsRecomm': ['01', '02', 'LS'], 'ShortInterest': ['05']},  # ShortInterest は恒等の点検だけ
    'op': {s: None for s in MAIN_SIGNALS},  # None = すべての組
}


def rules_sha():
    return hashlib.sha256(json.dumps(RULES, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


# ───────────────────────── 取得 ─────────────────────────
def fetch_one(key, force=False):
    fid, name = FILES[key]
    p = os.path.join(CACHE, name)
    if os.path.exists(p) and os.path.getsize(p) > 0 and not force:
        return p
    os.makedirs(CACHE, exist_ok=True)
    tmp = f'{p}.{os.getpid()}.part'
    for i in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(DRIVE.format(fid), headers=UA), timeout=600) as r, open(tmp, 'wb') as f:
                while True:
                    b = r.read(1 << 22)
                    if not b:
                        break
                    f.write(b)
            head = open(tmp, 'rb').read(64)
            if head.lstrip().lower().startswith(b'<!doctype html') or head.lstrip().lower().startswith(b'<html'):
                raise RuntimeError('Google Drive が確認の画面を返した（ファイルではない）')
            os.replace(tmp, p)
            return p
        except Exception as e:  # noqa
            print(f'  {key}: 取得の失敗 {e}・再試行', file=sys.stderr)
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f'取得失敗 {key}')


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while True:
            b = f.read(1 << 24)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def cmd_fetch(args):
    out = {}
    for k in FILES:
        p = fetch_one(k, force=args.force)
        out[k] = {'file': os.path.basename(p), 'bytes': os.path.getsize(p), 'sha256': sha256_file(p)}
        print(f'{k:8s} {out[k]["bytes"]:>12,d}  {out[k]["sha256"][:16]}…  {out[k]["file"]}')
    json.dump(out, open(os.path.join(CACHE, 'nx_osap_info_files.json'), 'w'), indent=1)


# ───────────────────────── ポートフォリオの切り出し ─────────────────────────
def _rows(key):
    p = fetch_one(key)
    if p.endswith('.zip'):
        z = zipfile.ZipFile(p)
        f = io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8')
    else:
        f = open(p, encoding='utf-8')
    r = csv.reader(f)
    hdr = next(r)
    assert hdr[:7] == ['signalname', 'port', 'date', 'ret', 'signallag', 'Nlong', 'Nshort'], hdr
    for row in r:
        yield row


def _ym(d):
    return int(d[:4]) * 100 + int(d[5:7])


def cmd_ports(args):
    need = {}  # (file, signal) -> set(port) or None
    for r in RULES:
        if r['signal'] == 'MIX':
            continue
        need.setdefault((r['file'], r['signal']), set()).add(r['port'])
    for f, d in REPORT_PORTS.items():
        for s, ps in d.items():
            cur = need.setdefault((f, s), set())
            if ps is None:
                need[(f, s)] = None
            elif cur is not None:
                cur.update(ps)
    series = {}
    for f in sorted({k[0] for k in need}):
        sigs = {s for (ff, s) in need if ff == f}
        for row in _rows(f):
            s = row[0]
            if s not in sigs:
                continue
            want = need[(f, s)]
            if want is not None and row[1] not in want:
                continue
            ret = float(row[3]) if row[3] not in ('', 'NA') else None
            n = int(float(row[5])) if row[5] not in ('', 'NA') else None
            series.setdefault(f, {}).setdefault(s, {}).setdefault(row[1], {})[_ym(row[2])] = [ret, n]
        print(f'{f}: {len(series.get(f, {}))} 信号')
    # 偽物（placebo）: 各信号の最大の番号の組（OSAP の LS の買いの側）と LS
    plc = {}
    for row in _rows('placebo'):
        ret = float(row[3]) if row[3] not in ('', 'NA') else None
        n = int(float(row[5])) if row[5] not in ('', 'NA') else None
        plc.setdefault(row[0], {}).setdefault(row[1], {})[_ym(row[2])] = [ret, n]
    placebo = {}
    for s, d in plc.items():
        nums = sorted(p for p in d if p != 'LS')
        placebo[s] = {'long_port': nums[-1], 'long': d[nums[-1]], 'LS': d.get('LS', {})}
    series['placebo'] = placebo
    # 評価の開始月（形だけで決める）
    starts = {}
    for r in RULES:
        if r['signal'] == 'MIX':
            continue
        d = series[r['file']][r['signal']][r['port']]
        ms = sorted(d)
        if r.get('start') == 'first':
            starts[r['id']] = ms[0]
            continue
        thin = [m for m in ms if d[m][1] is None or d[m][1] < MIN_N]
        auto = ms[0] if not thin else next(m for m in ms if m > max(thin))
        starts[r['id']] = max(auto, r['start']) if isinstance(r.get('start'), int) else auto
    ends = {r['id']: r.get('end') or max(series[r['file']][r['signal']][r['port']]) for r in RULES if r['signal'] != 'MIX'}
    blob = {'series': series}
    sha = hashlib.sha256(json.dumps(blob, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    out = {'generated': time.strftime('%Y-%m-%d'), 'note': 'OSAP のポートフォリオの月次リターン（%・総リターン）と組の銘柄数。成績の集計は入れていない',
           'rules_sha256': rules_sha(), 'series_sha256': sha, 'starts': starts, 'ends': ends, **blob}
    json.dump(out, open(PORTS_OUT, 'w'), separators=(',', ':'))
    print('series_sha256', sha)
    print('rules_sha256 ', rules_sha())
    # 同じ定義の二つのファイルが同じ数字を持つかの恒等の点検（差の最大だけを表示・成績ではない）
    a = series['q5vw']['ShortInterest']['05']
    b = series['vwf']['ShortInterest']['05'] if '05' in series['vwf'].get('ShortInterest', {}) else None
    if b:
        diff = max(abs(a[m][0] - b[m][0]) for m in a if m in b and a[m][0] is not None and b[m][0] is not None)
        print('恒等の点検 ShortInterest 五分位VW の05 と VWforce の05: 差の最大', round(diff, 6))


# ───────────────────────── 回転（銘柄ごとの信号から） ─────────────────────────
def _quantile7(sorted_vals, p):
    """R の quantile(type=7) と同じ（OSAP の breakpoint）"""
    n = len(sorted_vals)
    h = (n - 1) * p
    lo = math.floor(h)
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (h - lo) * (sorted_vals[hi] - sorted_vals[lo])


def _settings(doc, signal, file):
    x = doc[signal]
    num = lambda v, d: d if v in ('', 'NA', 'None', 'none') else float(v)
    form = x['Cat.Form']
    if file == 'q5vw':
        q = 0.2
    elif file == 'd10vw':
        q = 0.1
    else:
        q = num(x['LS Quantile'], 0.2)
    pp = int(num(x['Portfolio Period'], 1))
    sm = int(num(x['Start Month'], 6))
    if file in ('q5vw', 'd10vw'):
        form = 'continuous'
    return form, q, pp, sm, x['Filter']


def cmd_turnover(args):
    import numpy as np
    doc = {x['Acronym']: x for x in csv.DictReader(open(fetch_one('doc'), encoding='utf-8-sig'))}
    targets = [r for r in RULES if r['signal'] != 'MIX' and r['file'] != 'ff93']  # ff93 は大型・小型の分け目に時価が要る＝公開の銘柄ごとの信号に時価が無いので計算しない
    sigs = sorted({r['signal'] for r in targets} | {'DolVol'})
    p = fetch_one('firm')
    z = zipfile.ZipFile(p)
    f = io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8', newline='')
    hdr = f.readline().rstrip('\r\n').split(',')
    idx = {s: hdr.index(s) for s in sigs}
    ip, iy = hdr.index('permno'), hdr.index('yyyymm')
    data = {s: (array.array('i'), array.array('i'), array.array('d')) for s in sigs}  # permno, yyyymm, 値
    t0 = time.time()
    nrow = 0
    for line in f:
        c = line.rstrip('\r\n').split(',')
        nrow += 1
        pm, ym = int(float(c[ip])), int(float(c[iy]))
        for s, i in idx.items():
            v = c[i]
            if v != '' and v != 'NA':
                a = data[s]
                a[0].append(pm); a[1].append(ym); a[2].append(float(v))
        if args.limit and nrow >= args.limit:
            break
        if nrow % 1_000_000 == 0:
            print(f'  {nrow:,} 行 {time.time() - t0:.0f}秒', file=sys.stderr)
    print(f'読んだ行 {nrow:,}・{time.time() - t0:.0f}秒')
    # 時価の代わりの重み: exp(−DolVol_signed)（signed は −log(2か月前の出来高×株価)）
    dv_p, dv_y, dv_v = (np.frombuffer(x, dtype=np.int32 if x.typecode == 'i' else np.float64) for x in data['DolVol'])
    print('DolVol（符号つき）の範囲', float(np.nanmin(dv_v)), float(np.nanmax(dv_v)))
    sign_dv = -1.0 if np.median(dv_v) < 0 else 1.0  # 符号つきなら負の値＝log を戻すには −1 を掛ける
    fin = np.isfinite(dv_v)  # 出来高0の月は log が −∞（符号つきで +∞）＝重みにできないので欠け扱い（0 と読まない）
    print('DolVol が有限でない行', int((~fin).sum()))
    size = {(int(a), int(b)): math.exp(sign_dv * float(v)) for a, b, v in zip(dv_p[fin], dv_y[fin], dv_v[fin])}
    res = {'generated': time.strftime('%Y-%m-%d'), 'rows_read': nrow, 'rules_sha256': rules_sha(),
           'note': '良い側の組の片道の回転（月次）。vw＝時価の代わりに2か月前の売買代金で重みづけした、組の出入りによる回転（残る銘柄の重みは同じ月の値で比べる）。'
                   'ew＝銘柄数で等分した回転（価格の変化による重みのずれは無視）。キーは保有の月（信号の月の翌月）',
           'size_proxy': 'exp(-DolVol_signed)・DolVol = log(2か月前の出来高×|株価|)（OSAP DolVol.py）', 'rules': {}}
    for r in targets:
        s = r['signal']
        form, q, pp, sm, filt = _settings(doc, s, r['file'])
        P, Y, V = (np.frombuffer(x, dtype=np.int32 if x.typecode == 'i' else np.float64) for x in data[s])
        if len(V) == 0:
            res['rules'][r['id']] = {'error': '銘柄ごとの信号が無い'}
            continue
        order = np.lexsort((P, Y))
        P, Y, V = P[order], Y[order], V[order]
        rebm = sorted({((sm + k * pp) % 12) or 12 for k in range(13)})
        # 組の番号を月ごとに決める（OSAP の single_sort / discrete を写す）
        port = np.full(len(V), -1, dtype=np.int32)
        if form == 'discrete':
            support = np.unique(V)
            port = (np.searchsorted(support, V) + 1).astype(np.int32)
            top = len(support)
        else:
            plist = [round(q * k, 10) for k in range(1, int(round(1 / q)) - 1)] + [1 - q] if q <= 1 / 3 else sorted({q, 1 - q})
            top = len(plist) + 1
            bounds = np.flatnonzero(np.diff(Y)) + 1
            for a, b in zip(np.r_[0, bounds], np.r_[bounds, len(Y)]):
                vals = np.sort(V[a:b])
                br = [_quantile7(vals, pq) for pq in plist]
                if len(plist) > 1 and not (br[-1] - br[0] > 0):
                    continue  # 退化した月（OSAP は捨てる）
                v = V[a:b]
                pt = np.full(b - a, -1, dtype=np.int32)
                pt[v <= br[0]] = 1
                for k in range(1, len(plist)):
                    pt[(pt == -1) & (v < br[k])] = k + 1
                pt[(pt == -1) & (v >= br[-1])] = len(plist) + 1
                port[a:b] = pt
        # 組替えの月以外は、その銘柄の直前の組を引き継ぐ（OSAP の fill(port)）
        if pp > 1:
            mon = Y % 100
            keep = np.isin(mon, rebm)
            port = np.where(keep, port, -1)
            o2 = np.lexsort((Y, P))
            last = {}
            for j in o2:
                pm = int(P[j])
                if port[j] != -1:
                    last[pm] = int(port[j])
                elif pm in last:
                    port[j] = last[pm]
        want = int(r['port'])
        if form != 'discrete' and want != top:
            raise SystemExit(f'{r["id"]}: 良い側の番号 {want} と組の数 {top} が合わない')
        if form == 'discrete' and want != top:
            raise SystemExit(f'{r["id"]}: 離散の良い側 {want} が最大の番号 {top} でない')
        members = {}
        sel = np.flatnonzero(port == want)
        for j in sel:
            members.setdefault(int(Y[j]), []).append(int(P[j]))
        months = sorted(members)
        vw, ew, nn = {}, {}, {}
        med_w = {}
        for m in months:
            ws = [size.get((pm, m)) for pm in members[m]]
            ok = [w for w in ws if w is not None]
            med_w[m] = float(np.median(ok)) if ok else 1.0
        prev = None
        for m in months:
            hold = m + 1 if m % 100 != 12 else (m // 100 + 1) * 100 + 1
            cur = set(members[m])
            nn[hold] = len(cur)
            if prev is not None and _next(prev) == m:
                old = set(members[prev])
                wt = lambda pm, mm=m, pv=prev: size.get((pm, mm)) or size.get((pm, pv)) or med_w[mm]
                s_new = sum(wt(pm) for pm in cur)
                s_old = sum(wt(pm) for pm in old)
                t = 0.0
                for pm in cur | old:
                    a = wt(pm) / s_new if pm in cur else 0.0
                    b = wt(pm) / s_old if pm in old else 0.0
                    t += abs(a - b)
                vw[hold] = round(t / 2, 5)
                t = sum(abs((1 / len(cur) if pm in cur else 0) - (1 / len(old) if pm in old else 0)) for pm in cur | old)
                ew[hold] = round(t / 2, 5)
            prev = m
        ann = lambda d, a=None, z_=None: (round(12 * float(np.mean([v for k, v in d.items() if (a is None or k >= a) and (z_ is None or k <= z_)])), 3)
                                          if any((a is None or k >= a) and (z_ is None or k <= z_) for k in d) else None)
        res['rules'][r['id']] = {
            'signal': s, 'file': r['file'], 'form': form, 'q': q, 'portperiod': pp, 'startmonth': sm, 'filter_in_OP': filt,
            'filter_applied': filt in ('', 'NA', 'None', 'none'),
            'annual_oneway_vw': {'all': ann(vw), 'train': ann(vw, None, 200612), 'hold': ann(vw, 200701)},
            'annual_oneway_ew': {'all': ann(ew), 'train': ann(ew, None, 200612), 'hold': ann(ew, 200701)},
            'monthly_vw': vw, 'monthly_ew': ew, 'n_names': nn}
        print(f'{r["id"]:40s} 年率の片道 vw {res["rules"][r["id"]]["annual_oneway_vw"]["all"]}  ew {res["rules"][r["id"]]["annual_oneway_ew"]["all"]}  月数 {len(vw)}')
    json.dump(res, open(TURN_OUT, 'w'), separators=(',', ':'))
    print('→', TURN_OUT)


def _next(m):
    return m + 1 if m % 100 != 12 else (m // 100 + 1) * 100 + 1


# ───────────────────────── 形だけの表示 ─────────────────────────
def cmd_shape(args):
    j = json.load(open(PORTS_OUT))
    turn = json.load(open(TURN_OUT)) if os.path.exists(TURN_OUT) else {'rules': {}}
    out = {}
    for r in RULES:
        if r['signal'] == 'MIX':
            continue
        d = j['series'][r['file']][r['signal']][r['port']]
        ms = sorted(int(m) for m in d)
        st = j['starts'][r['id']]
        en = j['ends'][r['id']]
        ev = [m for m in ms if st <= m <= en]
        exp = 0
        m = ev[0]
        while m <= ev[-1]:
            exp += 1; m = _next(m)
        ns = sorted(d[str(m)][1] for m in ev if d[str(m)][1] is not None)
        tr = sum(1 for m in ev if m <= 200612)
        t = turn['rules'].get(r['id'], {})
        # 保有の月の銘柄数（自前の組）と OSAP の Nlong の比（写しの点検）
        rep = None
        if t.get('n_names'):
            ratios = [d[str(m)][1] / t['n_names'][str(m)] for m in ev if str(m) in t['n_names'] and d[str(m)][1] and t['n_names'][str(m)]]
            rep = round(sorted(ratios)[len(ratios) // 2], 3) if ratios else None
        out[r['id']] = {'from': ev[0], 'to': ev[-1], 'months': len(ev), 'gaps': exp - len(ev), 'train_months': tr, 'train_years': round(tr / 12, 1),
                        'nlong_min': ns[0], 'nlong_median': ns[len(ns) // 2], 'turnover_vw_all': (t.get('annual_oneway_vw') or {}).get('all'),
                        'turnover_ew_all': (t.get('annual_oneway_ew') or {}).get('all'), 'osap_nlong_over_own_n_median': rep}
        print(r['id'], out[r['id']])
    json.dump(out, open(os.path.join(CACHE, 'nx_osap_info_shape.json'), 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['fetch', 'ports', 'turnover', 'shape', 'all'])
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--limit', type=int, default=0, help='turnover: 読む行数の上限（試し）')
    a = ap.parse_args()
    if a.cmd in ('fetch', 'all'):
        cmd_fetch(a)
    if a.cmd in ('ports', 'all'):
        cmd_ports(a)
    if a.cmd in ('turnover', 'all'):
        cmd_turnover(a)
    if a.cmd in ('shape', 'all'):
        cmd_shape(a)
