/* One deliberate step at a time; every generation boundary remains explicit. */
const journey = { view: 'home', setup: {}, session: null, sourceKey: '', busy: false, styleSuppressClick: false, styleDragX: 0 };
const journeyRoot = uiNode('main'); journeyRoot.id = 'journey'; document.body.prepend(journeyRoot);
const journeyRail = uiNode('nav', undefined, workspaceShell); journeyRail.id = 'journeyRail'; journeyRail.setAttribute('aria-label', '创作流程');
const journeyNames = {drama:'短剧', 'product-ad':'广告', automotive:'汽车', 'live-commerce':'电商'};
const journeyStyles = [['cinema','写实电影','自然光线 · 克制色彩','https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=900&q=82'],['photoreal','超写实摄影','真实皮肤 · 光学景深 · 细节优先','https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?auto=format&fit=crop&w=900&q=82'],['cinematic','电影质感','宽银幕构图 · 胶片颗粒 · 戏剧光线','https://images.unsplash.com/photo-1485846234645-a62644f84728?auto=format&fit=crop&w=900&q=82'],['cg3d','三维 CG','体积光 · PBR 材质 · 精确空间','https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?auto=format&fit=crop&w=900&q=82'],['anime','日漫','清晰线稿 · 平涂色彩 · 夸张动作','https://images.unsplash.com/photo-1578632292335-df3abbb0d586?auto=format&fit=crop&w=900&q=82'],['illustration','插画绘本','笔触可见 · 造型概括 · 统一配色','https://images.unsplash.com/photo-1513364776144-60967b0f800f?auto=format&fit=crop&w=900&q=82'],['watercolor','水彩手绘','透明叠色 · 纸张肌理 · 柔和边缘','https://images.unsplash.com/photo-1549490349-8643362247b5?auto=format&fit=crop&w=900&q=82'],['noir','黑色电影','高反差 · 阴影叙事 · 冷峻气氛','https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=900&q=82'],['retro','复古胶片','褪色色彩 · 灰尘划痕 · 怀旧光晕','https://images.unsplash.com/photo-1514525253161-7a46d19cd819?auto=format&fit=crop&w=900&q=82'],['cyberpunk','赛博朋克','霓虹反射 · 湿润街景 · 科技密度','https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=900&q=82'],['minimal','极简设计','留白 · 几何秩序 · 克制色彩','https://images.unsplash.com/photo-1494438639946-1ebd1d20bf85?auto=format&fit=crop&w=900&q=82'],['commercial','商业广告','产品主角 · 清洁灯光 · 高识别度','https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=900&q=82'],['documentary','纪实手持','现场光 · 呼吸感 · 观察距离','https://images.unsplash.com/photo-1495020689067-958852a7765e?auto=format&fit=crop&w=900&q=82'],['music-video','音乐 MV','节奏剪辑 · 强色彩 · 舞台能量','https://images.unsplash.com/photo-1506157786151-b8491531f063?auto=format&fit=crop&w=900&q=82'],['reference','跟随参考','提取已启用参考的视觉规则','https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=900&q=82'],['custom','自定义','用你自己的描述定义画面','https://images.unsplash.com/photo-1497366811353-6870744d04b2?auto=format&fit=crop&w=900&q=82']];
function jNode(tag, text, parent, cls) { const n = uiNode(tag,text,parent); if (cls) n.className=cls; return n; }
function jButton(text, action, parent, cls='') {
  const b=jNode('button',text,parent,cls); b.type='button';
  b.onclick=async()=>{ b.disabled=true; journey.busy=true;
    try { await action(); } catch(e) { jError(e.message); }
    finally { journey.busy=false; if(b.isConnected) b.disabled=false; }
  }; return b;
}
function jError(text) { let n=document.getElementById('journeyError'); if(!n) n=jNode('p','',journeyRoot,'journey-error'); n.id='journeyError'; n.textContent=text; showBanner(text); }
function jLayout(view) {
  journey.view=view; document.body.dataset.journey=view;
  journeyRoot.hidden=!['home','input','director'].includes(view);
  workspaceShell.hidden=!journeyRoot.hidden;
  workspaceShell.classList.toggle('discussion-mode',view==='discussion');
  if(view==='discussion') {
    workspaceShell.classList.remove('chat-collapsed');
    intelligentUI.tab='创作概要';
    if(journey.session) renderIntelligenceSession(journey.session,'创作概要');
  }
  jRail();
}
function jHeader(step) {
  journeyRoot.replaceChildren();
  const nav=jNode('header',undefined,journeyRoot,'journey-header');
  jButton('急急如漫令',()=>goFolders(),nav,'journey-brand');
  jNode('span',step,nav,'journey-caption');
  jButton('我的项目',()=>goFolders(),nav,'quiet');
}
function jCard(parent, title, detail, action, icon, cls='') {
  const b=jButton('',action,parent,'journey-card '+cls);
  if(icon) jNode('span',icon,b,'journey-icon');
  jNode('h2',title,b); jNode('p',detail,b); jNode('span','↗',b,'journey-arrow'); return b;
}
function jHome(data={projects:state.projectList}) {
  state.browsing=true; state.projectList=data.projects || state.projectList; rememberView();
  jLayout('home'); jHeader('把想法变成画面');
  const hero=jNode('section',undefined,journeyRoot,'journey-hero');
  jNode('span','从一个想法开始',hero,'eyebrow');
  jNode('h1','你想做什么视频？',hero); jNode('p','选一个方向，让导演陪你把它拍出来。',hero);
  const cards=jNode('div',undefined,hero,'journey-cards');
  jCard(cards,'短剧','故事、人物与一场好戏',()=>jCreate('drama','idea'),'01','genre-drama');
  jCard(cards,'广告','让产品被看见、被记住',()=>jCreate('product-ad','idea'),'02','genre-ad');
  jCard(cards,'汽车','车身质感与运动的力量',()=>jCreate('automotive','idea'),'03','genre-auto');
  jCard(cards,'参考视频','上传一支片子，找到创作方向',()=>jCreate('drama','video'),'↥','genre-reference');
  const foot=jNode('div',undefined,hero,'journey-home-foot');
  jButton('创作电商视频',()=>jCreate('live-commerce','idea'),foot,'quiet');
  jNode('span','先聊清楚，再开始生成。',foot);
  const recent=jNode('section',undefined,journeyRoot,'journey-recent');
  jNode('h2','继续创作',recent); const rows=jNode('div',undefined,recent,'recent-grid');
  if(!state.projectList.length) jNode('p','你的第一个作品，从上方开始。',rows,'muted');
  state.projectList.forEach(p=>{
    const row=jNode('article',undefined,rows,'recent-project');
    const open=jButton('',()=>openProject(p.id),row,'recent-open');
    if(p.cover) { const img=jNode('img',undefined,open); img.src=p.cover; img.alt=''; }
    else jNode('span','◧',open,'project-symbol');
    jNode('strong',p.name || '未命名项目',open); jNode('span','继续 →',open,'muted');
    jButton('删除',()=>removeProject(p),row,'recent-delete');
  });
}
async function jCreate(genre,source) {
  const result=await intelligentAPI('/api/projects',{name:journeyNames[genre]+' · '+new Date().toLocaleDateString('zh-CN')});
  state.projectId=result.project?.id || result.current; state.projectList=result.projects || state.projectList;
  state.messages=[];state.scenes=[];state.assets=[];state.refs=[];state.videoModel='seedance';state.resolution='720p';state.browsing=false;
  clearThread(); intelligentUI.session=null; workspaceProjectId=state.projectId;
  journey.setup={genre,source_mode:source,brief:'',visual_style:'cinema',custom_style:'',stage:'input',ready:false};
  await jSave('input'); jInput();
}
async function jSave(stage, ready=false) {
  const result=await intelligentAPI('/api/creation',{...journey.setup,stage,ready,engine:state.videoModel});
  journey.session=result; journey.setup={...result.intelligence.creation};
  state.directorId=result.director_id;state.directorName=result.director_name;state.videoModel=result.video_model;state.browsing=false;
  intelligentUI.session=result; return result;
}
function jSetupHeading(parent, eyebrow, title, detail) { jNode('span',eyebrow,parent,'eyebrow');jNode('h1',title,parent);jNode('p',detail,parent,'lead'); }
function jInput() {
  jLayout('input');jHeader('01 / 内容');
  const body=jNode('section',undefined,journeyRoot,'journey-setup');
  jButton('← 返回首页',()=>goFolders(),body,'quiet back-link');
  jSetupHeading(body,journeyNames[journey.setup.genre]+'创作','先把你的想法告诉我。','上传剧本或分镜表格，或描述你想拍的内容。不需要先写提示词。');
  const genre=jNode('select',undefined,body,'genre-select');genre.setAttribute('aria-label','视频类型');
  Object.entries(journeyNames).forEach(([id,name])=>{const o=jNode('option',name,genre);o.value=id;o.selected=id===journey.setup.genre;});
  genre.onchange=()=>{journey.setup.genre=genre.value;};
  const tabs=jNode('div',undefined,body,'input-tabs');
  [['idea','对话想法'],['script','上传剧本'],['table','上传表格'],['video','视频参考']].forEach(([value,label])=>{
    const b=jButton(label,async()=>{journey.setup.source_mode=value;await jSave('input');jInput();},tabs,'tab '+(journey.setup.source_mode===value?'selected':''));b.setAttribute('aria-pressed',String(journey.setup.source_mode===value));
  });
  if(['script','table'].includes(journey.setup.source_mode)) {
    const isTable=journey.setup.source_mode==='table';
    const box=jNode('div',undefined,body,'script-drop');
    jNode('span','↥',box,'upload-symbol');jNode('h2',journey.session?.script_name || (isTable?'把分镜表格带进来':'把剧本带进来'),box);
    jNode('p',isTable?'支持 Excel（.xlsx）、CSV、TSV；旧版 .xls 请另存为 .xlsx。':'支持 Word、TXT、Markdown、Excel（.xlsx）、CSV、TSV',box);
    if(isTable) jNode('p','可以包含镜头、画面、台词、时长、产品卖点等列，导演会按工作表和行列读取。',box);
    const label=jNode('label',isTable?'选择表格文件':'选择剧本文件',box,'upload-button');
    const file=jNode('input',undefined,label);file.type='file';file.accept=isTable?'.xlsx,.csv,.tsv':'.docx,.txt,.md,.xlsx,.csv,.tsv';
    file.onchange=async()=>{
      if(!file.files[0])return;file.disabled=true;journey.uploading=true;
      const projectId=state.projectId;
      try {
        const f=file.files[0];if(f.size>40*1024*1024)throw new Error('文件不能超过40MB，请拆分后上传。');
        const encoded=await fileToBase64(f);
        if(state.projectId!==projectId)throw new Error('项目已切换，请在目标项目重新上传。');
        const saved=await intelligentAPI('/api/script',{name:f.name,data_base64:encoded});
        if(state.projectId!==projectId)return;
        journey.session=await reloadIntelligence();jInput();
        if(saved.clipped)jError('文件内容超过4万字，仅导入前4万字；请拆分文件后使用。');
      }catch(e){jError(e.message);}finally{journey.uploading=false;file.disabled=false;}
    };
    if(journey.session?.script_preview){const preview=jNode('details',undefined,box,'script-preview');jNode('summary','查看已读取内容',preview);jNode('pre',journey.session.script_preview,preview);}
    if(state.scenes.length || state.assets.length) { file.disabled=true;jNode('p','此项目已有分镜或素材。请在对话中提出修改，避免替换原剧本。',box); }
  }
  if(journey.setup.source_mode==='video') {
    const source=jNode('div',undefined,body,'journey-source smart-content'); source.id='journeySource';
    jRenderSources();
  }
  const label=jNode('label',journey.setup.source_mode==='idea'?'你的创意':'补充想法（可选）',body,'brief-label');
  const brief=jNode('textarea',undefined,label);brief.id='journeyBrief';brief.value=journey.setup.brief || '';brief.rows=6;
  brief.placeholder=journey.setup.genre==='drama'?'例如：一场雨夜重逢。两个人都没有说出真相，最后用一个动作揭开关系。想拍成30秒写实短剧。':'想让谁看到什么？产品或主角、时长、你希望的感觉，都可以告诉导演。';
  brief.oninput=()=>{journey.setup.brief=brief.value;};
  const actions=jNode('footer',undefined,body,'setup-actions');jNode('small','内容会保存在当前项目',actions);
  jButton('下一步：选择导演 →',async()=>{
    if(journey.uploading)throw new Error('文件正在上传，请稍候。');
    if(!journey.setup.brief.trim() && !journey.session?.script_chars && !journey.session?.intelligence.source_videos.length)throw new Error('先写一个想法，或上传剧本 / 表格 / 视频。');
    await jSave('director');jDirector();
  },actions,'j-primary');
}
function jRenderSources() {
  const source=document.getElementById('journeySource');if(!source || !journey.session)return;
  source.replaceChildren(); renderSourceVideos(source,journey.session);
  journey.sourceKey=JSON.stringify(journey.session.intelligence.source_videos);
}
function jDirector() {
  jLayout('director');jHeader('02 / 导演');
  const body=jNode('section',undefined,journeyRoot,'journey-setup');
  jButton('← 返回内容',async()=>{await jSave('input');jInput();},body,'quiet back-link');
  jSetupHeading(body,'选择你的创作搭档','同一个故事，不同的拍法。','导演将按你选择的最终视频模型，分析故事、准备资产和编写提示词。');
  const models=jNode('div',undefined,body,'model-cards');
  [['seedance','Seedance 2.5','素材职责、分段节拍与声音编排','支持图片与音频参考 · 推理等级：极高'],['h3','H3','连续动作、空间关系与物理细节','本地生成 · 图片参考 · 推理等级：极高']].forEach(([id,name,detail,note])=>{
    const b=jCard(models,name,detail,()=>{state.videoModel=id;jDirector();},id==='h3'?'H':'S',state.videoModel===id?'selected':'');
    b.setAttribute('aria-pressed',String(state.videoModel===id));jNode('small',note,b);
  });
  jNode('h2','你希望画面是什么感觉？',body,'style-heading');
  jNode('p','按住鼠标左键左右拖动浏览全部风格，点击卡片确认导演的视觉倾向。',body,'style-hint');
  const styles=jNode('div',undefined,body,'style-cards');
  journeyStyles.forEach(([id,title,note,image])=>{
    const b=jButton('',()=>{if(journey.styleSuppressClick)return;journey.setup.visual_style=id;jDirector();},styles,'style-card '+(journey.setup.visual_style===id?'selected':''));
    const img=jNode('img',undefined,b,'style-image');img.src=image;img.alt=title;img.loading='lazy';
    const meta=jNode('span',undefined,b,'style-meta');jNode('strong',title,meta);jNode('small',note,meta);
    b.setAttribute('aria-pressed',String(journey.setup.visual_style===id));
  });
  styles.addEventListener('pointerdown',()=>{journey.styleSuppressClick=false;journey.styleDragX=0;});
  styles.addEventListener('pointermove',(e)=>{if(e.buttons!==1)return;journey.styleDragX=(journey.styleDragX||0)+Math.abs(e.movementX||0);if(journey.styleDragX>6){journey.styleSuppressClick=true;styles.scrollLeft-=e.movementX;}});
  styles.addEventListener('pointerup',()=>{if(journey.styleSuppressClick)setTimeout(()=>{journey.styleSuppressClick=false;},80);});
  styles.addEventListener('pointercancel',()=>{journey.styleSuppressClick=false;});
  if(journey.setup.visual_style==='custom') { const l=jNode('label','描述你想要的画面',body,'brief-label');const t=jNode('textarea',undefined,l);t.value=journey.setup.custom_style || '';t.placeholder='例如：低饱和、柔和侧光、固定机位，人物动作克制。';t.oninput=()=>{journey.setup.custom_style=t.value;}; }
  const actions=jNode('footer',undefined,body,'setup-actions');jNode('small','进入对话后，可随时调整创作方向',actions);
  jButton('进入导演对话 →',async()=>{
    const session=await jSave('discussion',true);clearThread();restore(session);jLayout('discussion');
  },actions,'j-primary');
}
function jWelcome() {
  document.getElementById('thread').querySelectorAll('.actions,.cards,.discussion-welcome').forEach(n=>n.remove());
  const n=jNode('section',undefined,document.getElementById('thread'),'discussion-welcome');
  jNode('span',state.videoModel==='h3'?'H3 导演':'Seedance 2.5 导演',n,'eyebrow');
  jNode('h1','让我们把它拍出来。',n);jNode('p','我已收到你的内容与风格选择。先一起分析故事、节奏和需要的素材。',n);
  const brief=journey.setup.brief || (journey.session?.script_name?'剧本：'+journey.session.script_name:'已上传参考视频');jNode('blockquote',brief,n);
  jButton('开始分析',async()=>{n.remove();await onUserText('请根据我的创作内容、已选择风格以及已启用参考，先分析核心内容、建议的镜头节奏与需要的素材。用对话讨论，未确认的创意标明为建议，不自动生成。');},n,'j-primary');
}
function jRail() {
  journeyRail.replaceChildren();if(!journeyRoot.hidden)return;
  const stage=journey.view;const steps=[['input','内容'],['director','导演'],['discussion','分析'],['assets','资产'],['prompts','视频提示词'],['film','成片']];
  steps.forEach(([key,label],i)=>{
    const b=jButton((i+1)+'  '+label,async()=>{
      if(intelligentUI.dirty && !await confirmLeaveWorkspace()) return;
      if(['input','director'].includes(key)) { journey.setup={...journey.session?.intelligence.creation,...journey.setup};if(key==='input')jInput();else jDirector();return; }
      if(key==='discussion') {jLayout(key);return;}
      jLayout(key);workspaceShell.classList.remove('chat-collapsed');await openIntelligence(key==='assets'?'素材':key==='prompts'?'分镜':'成片');
    },journeyRail,key===stage?'current':'');
    if(key===stage)b.setAttribute('aria-current','step');
  });
  jButton('调整方向',()=>jDirector(),journeyRail,'quiet');
}
const jSyncOriginal=syncIntelligence;
syncIntelligence=function(session) {
  jSyncOriginal(session);if(session.project_id!==state.projectId)return;
  journey.session=session;
  const notice=document.getElementById('intelligenceNotice');
  if(notice) notice.querySelectorAll('span').forEach(n=>n.remove());
  if(journey.view==='input' && JSON.stringify(session.intelligence.source_videos)!==journey.sourceKey)jRenderSources();
};
const jRenderOriginal=renderIntelligenceSession;
renderIntelligenceSession=function(session,tab) {
  if(tab!=='创作概要') return jRenderOriginal(session,tab);
  if(session.project_id!==state.projectId || state.browsing)return;
  const body=document.getElementById('workspaceBody');body.replaceChildren();
  const card=jNode('section',undefined,body,'creation-summary');
  const setup=session.intelligence.creation || {};
  const list=jNode('dl',undefined,card);
  const fields=[['类型',journeyNames[setup.genre || session.director_id] || '自由创作'],['导演',session.video_model==='h3'?'H3':'Seedance 2.5'],['画面',journeyStyles.find(s=>s[0]===(setup.visual_style || 'cinema'))?.[1] || '自定义']];
  fields.forEach(([key,value])=>{jNode('dt',key,list);jNode('dd',value,list);});
  jNode('h3','这次想拍',card);
  jNode('p',setup.brief || (session.script_name?'剧本：'+session.script_name:'从参考视频找到创作方向'),card,'summary-brief');
  if(setup.custom_style)jNode('p',setup.custom_style,card,'summary-style');
  const sources=session.intelligence.source_videos || [];
  if(sources.length) {
    jNode('h3','视频参考',card);
    sources.forEach(v=>jNode('p',v.name+' · '+(v.use_for_creation?'已用于创作':v.status==='analyzed'?'已解析，待启用':'待解析'),card,'summary-source'));
    jButton('查看参考 →',()=>openIntelligence('参考视频'),card,'quiet');
  }
  if(session.intelligence.memory.length) {
    jNode('h3','已确认的要求',card);
    session.intelligence.memory.slice(-5).forEach(m=>jNode('p',m.fact,card,'summary-fact'));
  }
  jButton('调整方向',()=>jDirector(),card,'summary-edit');
  updateWorkspaceHeader();
};
const jRestoreOriginal=restore;
restore=function(session) {
  journey.session=session;journey.setup={genre:session.director_id,visual_style:'cinema',source_mode:'idea',...session.intelligence?.creation};
  jRestoreOriginal(session);
  if(journey.setup.genre && !journey.setup.ready && Object.keys(session.intelligence?.creation || {}).length) {
    if(journey.setup.stage==='director')jDirector();else jInput();
  } else {
    jLayout(state.scenes.length?(isFilmCurrent(session)?'film':state.scenes.some(s=>s.prompt)?'prompts':'assets'):'discussion');
    if(journey.view==='discussion' && !state.messages.length)jWelcome();
  }
};
showProjectFolders=function(data) { jHome(data); };
showFresh=function() { journey.setup={genre:'drama',source_mode:'idea',brief:'',visual_style:'cinema',stage:'input'};journey.session=intelligentUI.session; jInput(); };
makeProject=function() { return jCreate('drama','idea'); };
openDirectorPick=function() { jDirector(); };
const jOpenTab=openIntelligence;
openIntelligence=async function(tab) { await jOpenTab(tab);if(journeyRoot.hidden && journey.view!=='discussion')jLayout(tab==='素材'?'assets':tab==='成片'?'film':'prompts'); };
const jUpdateHeader=updateWorkspaceHeader;
updateWorkspaceHeader=function() {
  jUpdateHeader();
  const active=state.projectId && !state.browsing;
  if(!active)return;
  const project=state.projectList.find(p=>p.id===state.projectId);
  document.getElementById('workspaceProject').textContent=(project?.name || '当前项目')+' · '+(state.videoModel==='h3'?'H3':'Seedance 2.5')+'导演';
  document.getElementById('nextActionButton').onclick=async()=>{try{await workspaceNextAction();}catch(e){showBanner(e.message);}};
  if(!state.scenes.length) {
    document.getElementById('nextActionCopy').replaceChildren();jNode('strong','把讨论整理成可拍的分镜',document.getElementById('nextActionCopy'));
    jNode('p','先与导演聊定内容，准备好后进入资产阶段。',document.getElementById('nextActionCopy'));
    nextButton.textContent='整理分镜 →';
  }
  if(!journeyRoot.hidden)return;
  if(!document.querySelector('#thread .chat-label')){const label=jNode('div','导演对话',undefined,'chat-label');document.getElementById('thread').prepend(label);}
};
workspaceNextAction=async function() {
  if(!state.scenes.length) {
    const session=await intelligentAPI('/api/creation/plan');syncIntelligence(session);jLayout('assets');await openIntelligence('素材');return;
  }
  if(journey.session?.intelligence.pending_plan)return openIntelligence('修改与版本');
  if(state.assets.some(a=>a.kind!=='音频'&&(!a.file||a.needs_redraw)) || !state.assets.length){jLayout('assets');return openIntelligence('素材');}
  if(state.scenes.some(s=>!s.prompt || s.needs_rewrite || !s.confirmation)){jLayout('prompts');return openIntelligence('分镜');}
  if(isFilmCurrent(journey.session)){jLayout('film');return openIntelligence('成片');}
  return submitEpisode();
};
// Script uploads inside established projects must never silently discard existing work.
document.getElementById('scriptFile').onchange=async event=>{
  const f=event.target.files?.[0];if(!f)return;
  try { if(state.scenes.length || state.assets.length) throw new Error('已有分镜或素材，请新建项目上传另一份剧本，或在对话中提出修改。');
    await intelligentAPI('/api/script',{name:f.name,data_base64:await fileToBase64(f)});journey.session=await reloadIntelligence();showBanner('剧本已上传。跟导演讨论，准备好后点击整理分镜。');
  } catch(e){showBanner(e.message);}finally{event.target.value='';}
};
document.getElementById('say').placeholder='跟导演聊想法、节奏，或点名修改某一场…';
// index.html starts boot only after these overrides have loaded.
