#!/usr/bin/env python3
"""night/nx_osap_intang_data.py — 角度 nx_osap_intang の【取得と整形だけ】（成績は計算しない・表示しない）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…
別のSessionで検証していない新たな分析を同じ内容でしてほしい」。事前登録は out/nx_osap_intang_prereg.json。

素材: Chen & Zimmermann の Open Source Asset Pricing（OSAP・2025.10 版・openassetpricing.com → Google Drive）。
  CRSP/Compustat から作った予言変数ごとのポートフォリオ。ret は CRSP の月次の総リターン（配当込み・上場廃止のリターン込み、
  欠けた業績由来の上場廃止には NYSE/AMEX −35%・NASDAQ −55% を置く）を 100 倍した % 表記（11_ProcessCRSP.R）。
  - PredictorAltPorts_QuintilesVW : 連続の変数の五分位・時価加重（重み＝前月末の時価 melag）。組 '05' が原論文の向きの良い側
                                    （01_PortfolioFunction.R: 並べる前に signal×Sign・LS＝最大の組−最小の組）
  - PredictorAltPorts_DecilesVW   : 同じ十分位（探索 X1）
  - PredictorAltPorts_LiqScreen_VWforce : 原論文の組の作り方のまま時価加重を強制。離散の変数（MS・SurpriseRD）はここでだけ時価加重
  - PredictorAltPorts_FF93style   : 大型/小型（NYSE の時価の中央値）× 変数の3分位（NYSE の 30/70%）の6組・6月の値で組み・7月〜翌6月持つ・
                                    時価加重（32_Predictor2x3Ports.R。探索 X2 と報告 R2）
  - PredictorPortsFull            : 原論文の作り方（PatentsRD・CitationsRD は小型株の中の二値・時価加重）＝訓練期間だけの報告 R1
  作り方の確認（2026-09-28 に原本のコードを読んだ・github.com/OpenSourceAP/CrossSection master）: Portfolios/Code/01_PortfolioFunction.R・
  30_PredictorAltPorts.R・32_Predictor2x3Ports.R・11_ProcessCRSP.R、Signals/pyCode/SignalMasterTable.py（shrcd 10/11/12・exchcd 1/2/3）・
  DataDownloads/CompustatAnnual.py（年次は決算期末の6か月後から使う）・CompustatQuarterly.py（四半期は期末の3か月後か公表日 rdq の月の遅いほう）・
  DataDownloads/PatentCitations.py（NBER の特許 1976〜2006 の付与年＝2007年以降は無い）・各 Predictors/*.py。

規則の台帳 RULES は事前登録と同じもの。測る道具（night/nx_osap_intang.py・これから書く）はここを import する（写さない）。
出力: out/_nx_cache/nx_osap_intang_ports.json（gitignore）
  {'sources': {ファイル: {'drive_id','sha256','bytes'}}, 'signals': {変数: {出典: {組: [[yyyymm, ret(小数), Nlong], …]}}},
   'extract_sha256': 'signals' を sort_keys・区切り詰めで直列化した sha256, 'rules_sha256': RULES の sha256}
  測る道具は最初にこの2つの sha と事前登録に書いた sha の一致を確かめ、違えば止まる。

表示するのは形だけ（始まり・終わり・月数・途中の欠け・銘柄数・評価の開始月）。リターンの平均・累積・t は出さない。
使い方: python3 night/nx_osap_intang_data.py
"""
import csv, hashlib, io, json, os, statistics as S, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as C  # noqa: E402

DRIVE = 'https://drive.usercontent.google.com/download?id={}&export=download&confirm=t'
FILES = {
    # 名前: (Google Drive の id, キャッシュの名前)。ポートフォリオのフォルダ https://drive.google.com/drive/folders/1RrKj_SjK4RGfuo6EFjCViEZ5Itv2rEFk
    'SignalDoc': ('1Sev9s6cPFUGgxp1pFiej0lGzpsMqJCI2', 'osap_SignalDoc.csv'),
    'QuintilesVW': ('1ef905SSlCDyh1KU9W1tJs5sfBFz0HPUt', 'osap_PredictorAltPorts_QuintilesVW.zip'),
    'DecilesVW': ('1_1WWZqilrt1gleeyAFwjv5aobd0QRbS3', 'osap_PredictorAltPorts_DecilesVW.zip'),
    'VWforce': ('1KZE3FgBxFPaNOyxoRw63ubZHOlkR9kZW', 'osap_PredictorAltPorts_LiqScreen_VWforce.zip'),
    'FF93style': ('1pDRMNTOvRfvooAzYOmG9sBBz74mUO80Q', 'osap_PredictorAltPorts_FF93style.zip'),
    'PortsFull': ('1g7w-yQ6Cg2qbMEkER9Q3vgns4JszXQo6', 'osap_PredictorPortsFull.csv'),
}

NMIN = 20          # 良い側の組の銘柄数の下限（事前登録）。評価はこの数に初めて届いた月から・その後に下回った月は比較から落とす（0で埋めない）
X_MEDIAN_MIN = 40  # 探索 X1・X2 に入れる変数は、その組の銘柄数の全期間の中央値がこれ以上のもの（形で決めた線）
COST_PER_UNIT = 0.003  # 片道の売買 100% あたり 0.30%（eknzbh の mw_factor_us と同じ置き値）。感度 0.10%・0.60%

# ───────────── 規則の台帳（事前登録と同じ）─────────────
# file: OSAP のファイル / port: 良い側の組（原論文の向き＝最大の組）/ turn: 片道の売買回転（年・1.0=100%）の置き値
# pub: 公表年（公表後＝翌年1月〜を報告）/ op: 原論文の標本の年（SignalDoc）
RULES = [
    # ── 主の族 P（8本・Holm はこの8本で）──
    dict(id='P1_OrgCap_q5vw', fam='P', signal='OrgCap', file='QuintilesVW', port='05', turn=0.5, pub=2013, op=(1970, 2008),
         what='組織資本（販管費を毎年15%ずつ減価して積んだもの÷総資産・FF17業種の中で標準化）の高い五分位'),
    dict(id='P2_AdExp_q5vw', fam='P', signal='AdExp', file='QuintilesVW', port='05', turn=0.8, pub=2001, op=(1975, 1996),
         what='広告費÷時価総額の高い五分位'),
    dict(id='P3_BrandInvest_q5vw', fam='P', signal='BrandInvest', file='QuintilesVW', port='05', turn=1.0, pub=2014, op=(1975, 2010),
         what='ブランド投資率（広告費÷ブランド資本〔広告費を年50%で減価して積んだもの〕）の低い五分位'),
    dict(id='P4_RDAbility_q5vw', fam='P', signal='RDAbility', file='QuintilesVW', port='05', turn=1.0, pub=2013, op=(1980, 2009),
         what='研究開発の腕（過去の研究開発費÷売上が売上の伸びに効いた傾きの平均・研究開発費÷売上が上位1/3の会社の中・株価5ドル超）の高い五分位'),
    dict(id='P5_SurpriseRD_vwf', fam='P', signal='SurpriseRD', file='VWforce', port='02', turn=1.0, pub=2004, op=(1974, 2001),
         what='研究開発費が前年から5%超増え、総資産比でも5%超増えた会社（二値の1の側）'),
    dict(id='P6_Herf_q5vw', fam='P', signal='Herf', file='QuintilesVW', port='05', turn=0.4, pub=2006, op=(1963, 2001),
         what='業界（SIC 3桁）の売上のハーフィンダール指数（3年平均）の低い五分位＝競争の激しい業界'),
    dict(id='P7_MS_vwf', fam='P', signal='MS', file='VWforce', port='06', turn=1.5, pub=2005, op=(1978, 2001),
         what='簿価時価比の最も低い五分位（成長株）の中の Mohanram の G スコア 6以上の組'),
    dict(id='P8_FR_q5vw', fam='P', signal='FR', file='QuintilesVW', port='05', turn=0.8, pub=2006, op=(1980, 2002),
         what='年金の積立状況（年金資産−予測給付債務）÷時価総額の高い五分位（NYSE の切れ目）'),
    # ── 探索 X1 十分位の端（中央値の銘柄数40以上の連続の主の変数）──
    dict(id='X1_OrgCap_d10vw', fam='X1', signal='OrgCap', file='DecilesVW', port='10', turn=0.65, pub=2013, op=(1970, 2008)),
    dict(id='X1_AdExp_d10vw', fam='X1', signal='AdExp', file='DecilesVW', port='10', turn=1.04, pub=2001, op=(1975, 1996)),
    dict(id='X1_BrandInvest_d10vw', fam='X1', signal='BrandInvest', file='DecilesVW', port='10', turn=1.3, pub=2014, op=(1975, 2010)),
    dict(id='X1_Herf_d10vw', fam='X1', signal='Herf', file='DecilesVW', port='10', turn=0.52, pub=2006, op=(1963, 2001)),
    dict(id='X1_FR_d10vw', fam='X1', signal='FR', file='DecilesVW', port='10', turn=1.04, pub=2006, op=(1980, 2002)),
    # ── 探索 X2 大型株だけ（FF93 型の BH＝NYSE 中央値より大きい × 良い側の3分位・6月に組み直し）対 French Mkt ──
    dict(id='X2_OrgCap_BH', fam='X2', signal='OrgCap', file='FF93style', port='BH', turn=0.5, pub=2013, op=(1970, 2008)),
    dict(id='X2_AdExp_BH', fam='X2', signal='AdExp', file='FF93style', port='BH', turn=0.8, pub=2001, op=(1975, 1996)),
    dict(id='X2_BrandInvest_BH', fam='X2', signal='BrandInvest', file='FF93style', port='BH', turn=1.0, pub=2014, op=(1975, 2010)),
    dict(id='X2_Herf_BH', fam='X2', signal='Herf', file='FF93style', port='BH', turn=0.4, pub=2006, op=(1963, 2001)),
    dict(id='X2_FR_BH', fam='X2', signal='FR', file='FF93style', port='BH', turn=0.8, pub=2006, op=(1980, 2002)),
    # ── 探索 X3 等分の合成（毎月もとの等分へ戻す・その月に使える脚だけ・min_legs 本以上そろう月だけ）──
    dict(id='X3a_MIX8', fam='X3', parts=['P1_OrgCap_q5vw', 'P2_AdExp_q5vw', 'P3_BrandInvest_q5vw', 'P4_RDAbility_q5vw',
                                         'P5_SurpriseRD_vwf', 'P6_Herf_q5vw', 'P7_MS_vwf', 'P8_FR_q5vw'], min_legs=3, turn_add=0.10,
         what='主の8本の良い側を等分'),
    dict(id='X3b_INTANGCAP', fam='X3', parts=['P1_OrgCap_q5vw', 'P2_AdExp_q5vw', 'P3_BrandInvest_q5vw'], min_legs=2, turn_add=0.10,
         what='無形資本（組織資本・広告・ブランド）'),
    dict(id='X3c_INNOV', fam='X3', parts=['P4_RDAbility_q5vw', 'P5_SurpriseRD_vwf'], min_legs=2, turn_add=0.10, what='革新（研究開発の腕・増加）'),
    dict(id='X3d_QUALITY', fam='X3', parts=['P7_MS_vwf', 'P8_FR_q5vw'], min_legs=2, turn_add=0.10, what='利益・財務の質（G スコア・年金）'),
    # ── 探索 X4 同じ主題の他の変数（五分位・時価加重・良い側）──
    dict(id='X4_GrAdExp_q5vw', fam='X4', signal='GrAdExp', file='QuintilesVW', port='05', turn=1.5, pub=2014, op=(1974, 2010),
         what='広告費の伸びの低い五分位（株価5ドル超・広告費0.1超・時価の最下位十分位を除く）'),
    dict(id='X4_EarningsConsistency_q5vw', fam='X4', signal='EarningsConsistency', file='QuintilesVW', port='05', turn=0.8, pub=2009, op=(1971, 2002),
         what='1株利益の伸びの5年平均（符号の反転などの例外は除外）の高い五分位'),
    dict(id='X4_RDS_q5vw', fam='X4', signal='RDS', file='QuintilesVW', port='05', turn=1.0, pub=2011, op=(1976, 2003),
         what='実質のダーティ・サープラス（株式の発行・買戻しで既存株主が得た/失った分）の高い五分位'),
    dict(id='X4_HerfBE_q5vw', fam='X4', signal='HerfBE', file='QuintilesVW', port='05', turn=0.4, pub=2006, op=(1963, 2001),
         what='業界の自己資本のハーフィンダール指数の低い五分位'),
    dict(id='X4_HerfAsset_q5vw', fam='X4', signal='HerfAsset', file='QuintilesVW', port='05', turn=0.4, pub=2006, op=(1963, 2001),
         what='業界の総資産のハーフィンダール指数の低い五分位'),
    # ── 報告のみ R（格付けしない）──
    dict(id='R1_PatentsRD_op', fam='R', signal='PatentsRD', file='PortsFull', port='02', turn=1.0, pub=2013, op=(1982, 2008), train_only=True,
         what='小型株（NYSE の時価の中央値以下）の中の 特許数÷研究開発資本 の上位1/3（時価加重）。NBER の特許は 1976〜2006 まで＝訓練期間だけ'),
    dict(id='R1_CitationsRD_op', fam='R', signal='CitationsRD', file='PortsFull', port='02', turn=1.0, pub=2013, op=(1982, 2008), train_only=True,
         what='小型株の中の 引用÷研究開発費 の上位1/3（時価加重）。訓練期間だけ'),
]
MAIN_IDS = [r['id'] for r in RULES if r['fam'] == 'P']
NEED = {}
for r in RULES:
    if 'signal' in r:
        NEED.setdefault(r['file'], set()).add(r['signal'])
# 報告 R2（大型/小型の半分）と R4（悪い側）のための追加の組
for s in ['OrgCap', 'AdExp', 'BrandInvest', 'RDAbility', 'Herf', 'FR']:
    NEED['FF93style'].add(s)
for s in ['MS', 'SurpriseRD']:
    NEED.setdefault('VWforce', set()).add(s)


def rules_sha():
    return hashlib.sha256(json.dumps(RULES, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def fetch(key, max_age_days=60):
    fid, name = FILES[key]
    return C.get(DRIVE.format(fid), name=name, max_age_days=max_age_days)


def rows_of(key, b):
    if key in ('SignalDoc', 'PortsFull'):
        return csv.DictReader(io.TextIOWrapper(io.BytesIO(b), encoding='utf-8-sig'))
    z = zipfile.ZipFile(io.BytesIO(b))
    return csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8-sig'))


def ym(d):
    return int(d[:4]) * 100 + int(d[5:7])


def gaps(months):
    ms = sorted(months)
    if not ms:
        return 0
    n, (y, m) = 0, divmod(ms[0], 100)
    have = set(ms)
    while y * 100 + m <= ms[-1]:
        if y * 100 + m not in have:
            n += 1
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return n


def eval_start(rows, nmin=NMIN):
    """評価の開始月＝良い側の組の銘柄数が初めて nmin 以上になった月（形だけで決まる）"""
    for m, _, n in rows:
        if n is not None and n >= nmin:
            return m
    return None


def main():
    out = {'generated': '2026-09-28', 'note': '取得と整形だけ。ret は小数の総リターン（OSAP の % を 1/100）', 'sources': {}, 'signals': {}}
    doc = {}
    for key in FILES:
        b = fetch(key)
        out['sources'][key] = {'drive_id': FILES[key][0], 'cache': FILES[key][1], 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
        if key == 'SignalDoc':
            for r in rows_of(key, b):
                doc[r['Acronym']] = r
            continue
        want = NEED.get(key, set())
        present = set()
        for r in rows_of(key, b):
            s = r['signalname']
            if s not in want:
                continue
            present.add(s)
            if r['ret'] in ('', 'NA', 'NaN'):
                continue
            n = int(float(r['Nlong'])) if r['Nlong'] not in ('', 'NA') else None
            out['signals'].setdefault(s, {}).setdefault(key, {}).setdefault(r['port'], []).append([ym(r['date']), float(r['ret']) / 100.0, n])
        out['sources'][key]['missing_signals'] = sorted(want - present)
    for v in out['signals'].values():
        for ports in v.values():
            for p in ports:
                ports[p].sort()
    # 相手（French）の原本の sha も残す（測る道具は同じ版かを確かめる）
    for nm in ('F-F_Research_Data_Factors', 'Portfolios_Formed_on_ME'):
        b = C.get(C.FR.format(nm), name=f'fr_{nm}.zip')
        out['sources'][f'French_{nm}'] = {'url': C.FR.format(nm), 'cache': f'fr_{nm}.zip', 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
    blob = json.dumps(out['signals'], sort_keys=True, separators=(',', ':')).encode()
    out['extract_sha256'] = hashlib.sha256(blob).hexdigest()
    out['rules_sha256'] = rules_sha()
    out['signaldoc'] = {s: {k: doc[s][k] for k in ('Authors', 'Year', 'Journal', 'Cat.Form', 'Sign', 'Stock Weight', 'LS Quantile', 'Quantile Filter',
                                                  'Portfolio Period', 'Start Month', 'Filter', 'SampleStartYear', 'SampleEndYear', 'Return', 'T-Stat')}
                        for s in sorted(set().union(*NEED.values())) if s in doc}
    p = os.path.join(C.CACHE, 'nx_osap_intang_ports.json')
    tmp = p + '.tmp'
    json.dump(out, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, p)

    # ── 形だけを表示（リターンの統計は出さない） ──
    print('出力', p)
    print('extract_sha256', out['extract_sha256'])
    print('rules_sha256  ', out['rules_sha256'])
    for key, v in out['sources'].items():
        print(f"{key:36s} bytes={v['bytes']:>10d} sha256={v['sha256']} 欠けた変数={v.get('missing_signals')}")
    print('\n規則 | 出典 組 | 全期間 | 評価の開始（Nlong≥20 の最初） | 訓練の月（開始〜2006-12・Nlong≥20） | 保有の月（2007〜） | 開始後に Nlong<20 で落ちる月 | Nlong 中央（全期間/保有）')
    for r in RULES:
        if 'signal' not in r:
            print(f"{r['id']:30s} 合成: {r['parts']} 最低 {r['min_legs']} 本")
            continue
        rows = out['signals'].get(r['signal'], {}).get(r['file'], {}).get(r['port'])
        if not rows:
            print(f"{r['id']:30s} データ無し")
            continue
        st = eval_start(rows)
        tr = [x for x in rows if st and st <= x[0] <= C.TRAIN_END and x[2] is not None and x[2] >= NMIN]
        ho = [x for x in rows if x[0] >= C.HOLD_START and x[2] is not None and x[2] >= NMIN]
        drop = [x for x in rows if st and x[0] >= st and (x[2] is None or x[2] < NMIN)]
        nall = [x[2] for x in rows if x[2] is not None]
        nho = [x[2] for x in rows if x[0] >= C.HOLD_START and x[2] is not None]
        print(f"{r['id']:30s} {r['file']:11s} {r['port']:3s} {rows[0][0]}〜{rows[-1][0]} | {st} | {len(tr)}か月（{len(tr) / 12:.1f}年） | {len(ho)} | {len(drop)}"
              f" | {int(S.median(nall))}/{int(S.median(nho)) if nho else '-'}")
    for s, mx in (('PatentsRD', 200807), ('CitationsRD', 201207)):
        pf = out['signals'].get(s, {}).get('PortsFull', {}).get('02', [])
        after = [x for x in pf if x[0] >= mx]
        print(f"確認 {s} 組02: {mx} 以降の月数 {len(after)}" + (f"（Nlong 中央 {int(S.median([x[2] for x in after]))}）" if after else ''))
    ff = C.ff_factors()
    print('\nFrench Mkt', min(ff['mkt']), '〜', max(ff['mkt']), '月数', len(ff['mkt']))


if __name__ == '__main__':
    main()
