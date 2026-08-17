/* icon.js — 銘柄アイコンと行の彩色の**単一実装**。index.html（門）と portfolio.html（Ⅶ資産）が読む。
   表示専用——Ω・採点式・関門・売却規律・配分のどれにも触れない。

   ★2026-08-17 新設（ユーザー報告「新しく入った銘柄に色がない。追加した場合でも全タブで色が
     変わるようにして」）。直したのは二つで、どちらも**色そのものではなく配線**の問題だった:

   ① **同じ3017字が両ページにコピーされていた**（実測でバイト一致）。v9.9.108 で
      「関数を同期しただけでは足りない——CSSは共有されないので二つの画面が違うものを見せていた」
      という破れを一度踏んでいる。state.js と同じ作法で JS を一本にした。
      ⚠ **CSSは各ページに残す**——.tgrad の inset と角丸が両ページで違う（行の寸法が違うため）。

   ② **目録(out/logos/index.json)の到着より前に描かれた行は、永久に色が付かなかった**。
      CCF_LOGO は fetch で非同期に届くのに、起動時に描かれるタブ（Ⅳ台帳など）は
      showPage で描き直されないので、**間に合ったタブだけ色が付く**——これが
      「タブによって色がある/ない」の正体。
      → 目録が届いたら **ccfIconRepaint() が全タブの行を塗り直す**（描画関数は呼ばない＝副作用ゼロ）。
        隠れているタブのDOMも document に在るので、**一度の呼び出しで全タブに届く**。
      そのために構造を安定させた: **色が無くても <i class="tgrad"> を必ず吐く**（空の背景＝不可視）ので、
      後から色を入れるのは style を書くだけで済む＝DOMの形をいじらない（v9.9.105 の積み重ね文脈を壊さない）。

   ロゴが無い/色が採れない銘柄は**モノグラムのまま行も染めない**——ハッシュ色（実在しない色）で
   染めると「その会社の色」という約束が嘘になる（v9.9.105）。欠測は欠測として見せる（ルール7）。
*/
let CCF_LOGO=null;

/* 顔の計算（色・地・光）——emit と repaint が**同じこの一本**を使う（v9.9.65: 二重に持たない） */
function ccfIconFace(nm){

  const t=String(nm||'').trim().split(/[\s_]/)[0].toUpperCase();
  if(!t)return '';
  let h=0; for(let i=0;i<t.length;i++)h=(h*31+t.charCodeAt(i))>>>0;   // 同じ銘柄はいつも同じ色
  const hue=h%360, mono=(t.replace(/[^A-Z0-9]/g,'').slice(0,2)||'?');
  const esc=t.replace(/[^A-Z0-9.\-]/g,'');
  const m=CCF_LOGO?CCF_LOGO[esc]:null;
  const ext=m&&!m.x&&(m.ext||m), c=(m&&m.c)||null;
  const cs=(m&&m.cs)||(c?[c]:[]);
  const PX=x=>[1,3,5].map(i=>parseInt(x.substr(i,2),16));
  const A=(x,a)=>`rgba(${PX(x).join(',')},${a})`;
  const glow=c?c:(ext?'rgba(200,190,170,.5)':`hsl(${hue} 62% 52%)`);
  // タイルの地色: 既定は「代表色を1割だけ白に混ぜた淡色」。
  //   ただし **d=1（白い線画で透過あり）は白い地に置くと消える**ので、代表色を暗い地へ1.8割混ぜる。
  let tile='#fff';
  const rgb=(c&&/^#[0-9a-f]{6}$/i.test(c))?PX(c):null;
  if(m&&m.d) tile=rgb?`rgb(${rgb.map(v=>Math.round(26+(v-26)*.18)).join(',')})`:'#20242c';
  else if(rgb) tile=`rgb(${rgb.map(v=>Math.round(255-(255-v)*.10)).join(',')})`;
  // ── v9.9.107: 行の彩色は「**色を補間しない**」のが肝 ──────────────────────
  //   v9.9.106 は複数色を1本のリニアで繋いだが、**橙→緑→青の補間は途中で必ず茶色を通る**ので
  //   行が濁って見えた（実機で撮って確認）。さらに各色を白へ35%寄せていたため彩度も落ちていた。
  //   → 各色を**別々の楕円の光**として重ねる。重なりは加算的に見えるだけで補間しないので濁らない。
  //   左端の色バーが輪郭を作り、「滲み」ではなく「意図した意匠」に見せる。
  //   不透明度は色ごとに焼き込む（要素の opacity で一律に薄めるとバーまで沈む）。
  //   v9.9.108（ユーザー「もっと色をはっきりさせて」）: 5案を実機で並べて比べ、最も強い案を採った。
  //   はっきりさせる手は3つあり、**濃さを上げるだけでは足りない**——
  //   (1)不透明度を約2倍 (2)**中間停止で芯を作る**（0%→42%まで濃さを保ってから落とす。
  //   単純な放射は中心から即座に薄まるので「色があるのにぼんやり」になる）(3)彩度1.35倍（CSS側）。
  //   v9.9.109（ユーザー「最後まで色が届くようにしてほしい」）: **光の大きさと位置を px から % へ**。
  //   px固定だと**行幅・行高に追従しない**ので、幅の広い行では右2/3が地の色のまま残り、
  //   携帯で折り返して背の高くなった行では上下の隅が染まらなかった（実機の画面写真で発覚）。
  //   → 幅80%・高さ150%の光を、色数に応じて等間隔（1色=中央 / 2色=20:75 / 3色=12:50:86）に置く。
  //   端の光は行の外まではみ出すので、**どんな幅でも左端から右端まで色が届く**。
  //   **補間しない**という v9.9.107 の肝は不変（色どうしを繋がないので濁らない）。
  let bg='';       // 行に敷く光のCSS（色が無ければ空＝何も描かれない）
  if(cs.length){
    //   濃さは二段階で下げた（ユーザー「もう少しうすく」→「もう少し薄く」）。v9.9.108比で
    //   **v9.9.110 が ×0.60**、**v9.9.111 が ×0.34**（.62/.54/.48 → .21/.18/.16）。
    //   毎回 4案を実機で並べて選んでいる（×0.60/×0.45/×0.34/×0.25。×0.25は暗いテーマで消える）。
    //   **薄くするのは光だけ**——(a)届く範囲（80%×150%・%配置）は不変＝v9.9.109で直したことを
    //   打ち消さない (b)彩度1.35も不変＝色相の純度の話で濃さとは別の軸 (c)**左端バーは .75 のまま**
    //   ＝バーまで薄めると「意匠」ではなく「滲み」に戻る（v9.9.107の教訓）。
    //   **一つの要望に一つの軸だけ動かす**——まとめて触ると次の注文で何を戻せばよいか判らなくなる。
    const L=[`linear-gradient(90deg,${A(cs[0],.75)} 0 5px,rgba(0,0,0,0) 5px)`];
    const POS={1:['50%'],2:['20%','75%'],3:['12%','50%','86%']}[Math.min(3,cs.length)];
    const AL=[.21,.18,.16];
    cs.slice(0,3).forEach((x,i)=>{const al=AL[i];
      L.push(`radial-gradient(80% 150% at ${POS[i]} 50%,${A(x,al)} 0%,${A(x,al*.45)} 42%,${A(x,0)} 100%)`);});
    bg=L.join(',');
  }
  return {t:esc,hue:hue,mono:mono,ext:ext||'',glow:glow,tile:tile,bg:bg};
}

/* 行に敷く光 <i class="tgrad"> ＋ アイコン <span class="tico">。
   data-ic にティッカーを持たせるのは、目録が後から届いたときに塗り直す錨にするため。 */
function ccfIcon(nm){
  const f=ccfIconFace(nm); if(!f)return '';
  const img=!f.ext?'':`<img loading="lazy" decoding="async" alt="" src="out/logos/${f.t}.${f.ext}" onerror="this.remove()">`;
  return `<i class="tgrad" style="background:${f.bg}"></i>`
    +`<span class="tico" data-ic="${f.t}" title="${f.t}" style="--g:${f.glow};--tile:${f.tile};background:hsl(${f.hue} 34% 24%);color:hsl(${f.hue} 68% 80%)">${f.mono}${img}</span>`;
}

/* 既に描かれている行へ、いまの目録で色を塗り直す。**全タブ**（隠れているタブも）に届く。
   描画関数を呼ばないので副作用ゼロ——盤の価格書き戻しや iframe の再読込を引き起こさない。 */
function ccfIconRepaint(root){
  let n=0;
  try{
    (root||document).querySelectorAll('.tico[data-ic]').forEach(sp=>{
      const f=ccfIconFace(sp.getAttribute('data-ic')); if(!f)return;
      sp.style.setProperty('--g',f.glow); sp.style.setProperty('--tile',f.tile);
      const g=sp.previousElementSibling;
      if(g&&g.classList&&g.classList.contains('tgrad')&&g.style.background!==f.bg)g.style.background=f.bg;
      let img=sp.querySelector('img');
      if(f.ext){
        const src='out/logos/'+f.t+'.'+f.ext;
        if(!img){ img=document.createElement('img'); img.loading='lazy'; img.decoding='async'; img.alt='';
                  img.onerror=function(){this.remove();}; sp.appendChild(img); }
        if(img.getAttribute('src')!==src)img.setAttribute('src',src);
      }else if(img){ img.remove(); }   // x=1（実質白紙）＝ロゴを見せずモノグラムへ戻す
      n++;
    });
  }catch(e){}
  return n;
}

/* 目録を読む。**読めなくても表示は壊れない**（モノグラムのまま）が、
   読めたら必ず塗り直す——「間に合ったタブだけ色が付く」を作らないため。 */
function ccfLogoLoad(){
  return fetch('out/logos/index.json',{cache:'no-cache'})
    .then(r=>r.ok?r.json():null).then(j=>{ CCF_LOGO=(j&&j.have)||{}; })
    .catch(()=>{ CCF_LOGO={}; })
    .then(()=>ccfIconRepaint());
}
ccfLogoLoad();
