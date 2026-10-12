/* Project memory, safe edit plans, versions, feedback and generation planning. */
const intelligentUI = { session: null, tab: '项目记忆', busy: false };

function uiNode(tag, text, parent) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (parent) parent.appendChild(node);
  return node;
}

function uiButton(text, action, parent) {
  const button = uiNode('button', text, parent);
  button.type = 'button';
  button.onclick = async () => {
    button.disabled = true;
    try { await action(); }
    catch (error) {
      const message = error.message || '操作没有完成，可以重试。';
      showBanner(message);
      const dialog = document.getElementById('workspaceBody');
      if (dialog && !state.browsing) {
        let errorNode = dialog.querySelector('.smart-error');
        if (!errorNode) { errorNode = uiNode('p'); errorNode.className = 'smart-error'; dialog.prepend(errorNode); }
        errorNode.textContent = message;
      }
    }
    finally { button.disabled = false; updateWorkspaceHeader(); }
  };
  return button;
}

async function intelligentAPI(path, data = {}) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '操作失败');
  if (['/api/memory', '/api/budget', '/api/feedback', '/api/scenes/edit'].includes(path)) intelligentUI.dirty = false;
  return result;
}

function syncIntelligence(session) {
  if (session.project_id !== state.projectId) return;
  intelligentUI.session = session;
  if (session.scenes) state.scenes = session.scenes;
  if (session.assets) state.assets = session.assets;
  if (session.task) paintTask(session.task);
  updateWorkspaceHeader();
  const notice = document.getElementById('intelligenceNotice');
  if (!notice) return;
  notice.replaceChildren();
  const skill = session.skill;
  if (skill && skill.ready) uiNode('span', skill.name + '经验已用于全部阶段 · ', notice);
  if (session.intelligence && session.intelligence.pending_plan) {
    uiButton('有待应用修改，查看变化', () => openIntelligence('修改与版本'), notice);
  }
  if (workspaceShell.classList.contains('project-open') && !intelligentUI.dirty) renderIntelligenceSession(session, intelligentUI.tab);
}

async function reloadIntelligence() {
  const session = await intelligentAPI('/api/intelligence');
  syncIntelligence(session);
  return session;
}

function uiField(parent, label, value, multiline = false) {
  const wrap = uiNode('label', undefined, parent);
  wrap.className = 'smart-field';
  uiNode('span', label, wrap);
  const input = uiNode(multiline ? 'textarea' : 'input', undefined, wrap);
  input.value = value === undefined || value === null ? '' : value;
  if (multiline) input.rows = 4;
  return input;
}

function money(value) { return value === null || value === undefined ? '单价未设置，费用未知' : Number(value).toFixed(2) + ' 元（估算）'; }

async function openIntelligence(tab = intelligentUI.tab) {
  if (!state.projectId) throw new Error('先打开一个项目。');
  if (intelligentUI.dirty && !await confirmLeaveWorkspace()) return;
  intelligentUI.dirty = false;
  intelligentUI.tab = tab;
  await reloadIntelligence();
}

function renderIntelligenceSession(session, tab) {
  if (session.project_id !== state.projectId || state.browsing) return;
  intelligentUI.dirty = false;
  const dialog = document.getElementById('workspaceBody');
  dialog.replaceChildren();
  const body = uiNode('section', undefined, dialog);
  body.className = 'smart-content';
  updateWorkspaceHeader();
  const data = session.intelligence;
  if (tab === '项目记忆') {
    uiNode('p', '这里的设定会用于聊天、分场、资产描述、生图、视频写词与质量检查。当前明确要求优先于旧设定。', body);
    if (session.skill && session.skill.ready) uiNode('p', '导演：' + session.skill.name + ' · 规则版本 ' + session.skill.version + ' · ' + session.skill.stages.join(' / '), body);
    const fact = uiField(body, '新增明确的项目设定', '', true);
    uiButton('保存设定', async () => { await intelligentAPI('/api/memory', { fact: fact.value }); await openIntelligence(tab); }, body);
    data.memory.slice().reverse().forEach(entry => {
      const row = uiNode('article', undefined, body);
      uiNode('p', entry.fact, row);
      if (entry.evidence) uiNode('small', '依据：' + entry.evidence, row);
      uiButton('删除这条设定', async () => { await intelligentAPI('/api/memory', { delete_id: entry.id }); await openIntelligence(tab); }, row);
    });
  } else if (tab === '分镜') {
    uiNode('p', '先调整分镜，再准备提示词。修改秒数或内容会要求重新检查时间轴；资产只重画被修改的内容。', body);
    uiButton('请导演写视频提示词', prepareIntelligentPrompts, body);
    renderDirectorDrafts(body, session);
    if (!session.scenes.length) renderEmpty(body, '先把想法变成分镜', '跟导演描述故事、产品和时长，或上传剧本。');
    session.scenes.forEach((scene, index) => {
      const row = uiNode('article', undefined, body); row.className = 'scene-editor';
      uiNode('h3', '第' + (index + 1) + '场 · 版本' + scene.version + (scene.needs_rewrite ? ' · 需要更新提示词' : ''), row);
      const fields = {};
      const grid = uiNode('div', undefined, row); grid.className = 'field-grid';
      ['place', 'who', 'remember', 'seconds', 'prompt'].forEach((key, i) => {
        fields[key] = uiField(grid, ['地点', '画面主体', '观众记住什么', '时长（秒）', '提示词 / 时间轴'][i], scene[key], key === 'prompt');
        registerEditor(fields[key], scene, key);
      });
      uiButton('保存这场修改', async () => {
        const changes = collectEditorChanges(body);
        if (!changes.length) return;
        await intelligentAPI('/api/scenes/edit', { changes }); intelligentUI.dirty = false; await openIntelligence(tab);
      }, row);
      uiButton(scene.confirmation ? '查看并重新确认提示词' : '查看并确认提示词', () => confirmPrompt('video',scene.id), row);
      uiNode('small', scene.confirmation ? '已有确认记录；内容、参考或规格变化后需重新确认。' : '草稿 · 确认后才可提交', row);
      uiNode('small', '引用资产：' + (scene.asset_ids || []).map(id => (session.assets.find(a => a.id === id) || {}).name || '已缺失').join('、'), row);
    });
  } else if (tab === '参考视频') {
    renderSourceVideos(body, session);
  } else if (tab === '素材') {
    renderAssetTools(body, session);
    session.assets.filter(asset => asset.kind !== '音频').forEach(asset => {
      const row = uiNode('article', undefined, body);
      row.className = 'asset-editor';
      uiNode('h3', asset.kind + ' · ' + asset.name + (asset.needs_redraw ? ' · 待重画' : ''), row);
      if (asset.file) { const image = uiNode('img', undefined, row); image.src = mediaUrl('/library/', asset.file); image.alt = asset.name; image.onclick = () => openViewer(image.src); }
      const picture = uiField(row, '这张资产应锁定的样子', asset.picture, true);
      registerEditor(picture, asset, 'picture');
      const select = uiNode('select', undefined, row); select.multiple = true;
      registerEditor(select, asset, 'reference_ids');
      session.assets.filter(a => a.id !== asset.id && a.kind !== '音频' && a.file).forEach(a => {
        const option = uiNode('option', a.kind + ' / ' + a.name, select); option.value = a.id;
        option.selected = (asset.reference_ids || []).includes(a.id);
      });
      uiNode('small', '身份参考：按住 Ctrl 可多选；生成时只绑定选中的参考。', row);
      uiButton('保存资产要求', async () => {
        const changes = collectEditorChanges(body);
        if (!changes.length) return;
        await intelligentAPI('/api/scenes/edit', { changes }); intelligentUI.dirty = false; await openIntelligence(tab);
      }, row);
      uiButton(asset.confirmation ? '查看并重新确认提示词' : '查看并确认提示词', () => confirmPrompt('image',asset.id), row);
      uiButton('请导演重新写这张提示词', () => draftAssetPrompts(asset.id), row);
      uiNode('small', asset.confirmation ? '已有确认记录；生成前会复核是否仍有效。' : '草稿 · 保存与确认是两个步骤', row);
      if (asset.file) uiButton('删除这张素材', async () => { await deleteAsset(asset.file, asset.kind, 'board'); await openIntelligence(tab); }, row);
    });
  } else if (tab === '修改与版本') {
    const plan = data.pending_plan;
    if (plan) {
      uiNode('h3', plan.summary, body);
      plan.changes.forEach(change => {
        const target = session.scenes.find(s => s.id === change.target_id) || session.assets.find(a => a.id === change.target_id);
        renderComparison(body, (target?.name || target?.place || change.target_id) + ' · ' + fieldName(change.field), change.before, change.value);
      });
      uiNode('p', '应用只修改项目设定，不自动触发生图或视频生成。', body);
      uiButton('应用这些修改', async () => { await intelligentAPI('/api/plan/apply', { id: plan.id }); await openIntelligence(tab); }, body);
      uiButton('放弃计划', async () => { await intelligentAPI('/api/plan/discard'); await openIntelligence(tab); }, body);
    } else uiNode('p', '可直接跟导演说：“人物别动，只把第二场背景换成雨夜。”待应用计划会出现在这里。', body);
    if (data.revisions.length) uiButton('撤销最近一次编辑', async () => { await intelligentAPI('/api/revisions/undo'); await openIntelligence(tab); }, body);
    renderRevisions(body, session);
  } else if (tab === '质量与偏好') {
    uiNode('p', '视觉检查会调用当前写作模型，需要支持图片输入。视频检查使用抽样关键帧，不会自动重生成。', body);
    uiButton('检查已生成资产图', async () => { await intelligentAPI('/api/review', { kind: 'image' }); await openIntelligence(tab); }, body);
    uiButton('检查已生成视频', async () => { await intelligentAPI('/api/review', { kind: 'video' }); await openIntelligence(tab); }, body);
    data.reviews.slice().reverse().forEach(review => {
      const section = uiNode('article', undefined, body);
      uiNode('h3', review.kind === 'video' ? '视频检查' : '资产检查', section);
      renderReviewEvidence(section, review, session);
    });
    const reason = uiField(body, '认可或否决的原因', '', true);
    const target = uiNode('select', undefined, body);
    const overall = uiNode('option', '当前项目版本', target); overall.value = 'project';
    [...session.scenes, ...session.assets].forEach(item => { const option = uiNode('option', item.name || item.place || item.id, target); option.value = item.id; });
    const pref = uiNode('label', undefined, body); const check = uiNode('input', undefined, pref); check.type = 'checkbox';
    uiNode('span', '同时保存为跨项目偏好（可删除）', pref);
    [true, false].forEach(accepted => uiButton(accepted ? '认可这版' : '否决这版', async () => {
      await intelligentAPI('/api/feedback', { reason: reason.value, accepted, target_id: target.value, remember_preference: check.checked }); await openIntelligence(tab);
    }, body));
    uiNode('h3', '主动保存的个人偏好', body);
    (session.preferences || []).forEach(preference => {
      const row = uiNode('article', undefined, body); uiNode('p', (preference.accepted ? '喜欢：' : '避免：') + preference.reason, row);
      uiButton('删除偏好', async () => { await intelligentAPI('/api/preferences/delete', { id: preference.id }); await openIntelligence(tab); }, row);
    });
    data.feedback.slice(-10).reverse().forEach(entry => uiNode('p', (entry.accepted ? '认可' : '否决') + ' · ' + entry.reason, body));
  } else if (tab === '成片') {
    renderFinishedFilms(body, session);
  } else {
    uiNode('p', '预算仅约束图片与视频生成，按你填写的单价估算；写作、视觉检查及可选语音识别费用未计入。未知受理结果会保留预算占用，防止重复生成。', body);
    const limit = uiField(body, '项目上限（元，留空不设上限）', data.budget.limit);
    const image = uiField(body, '图片单价（元/张，留空表示未知）', data.budget.image_price);
    const prices = {};
    ['seedance', 'h3'].forEach(engine => ['480p', '720p', '1080p'].forEach(resolution => {
      const key = engine + ':' + resolution; prices[key] = uiField(body, key + ' 单价（元/秒）', data.budget.video_prices[key]);
    }));
    const autoLabel = uiNode('label', undefined, body); const auto = uiNode('input', undefined, autoLabel); auto.type = 'checkbox'; auto.checked = data.auto_review;
    uiNode('span', '生成后自动做视觉检查（会调用写作模型）', autoLabel);
    const speech = uiField(body, '可选语音模型名（留空不转写；当前写作接口需支持语音转写，会产生额外费用）', data.speech_model || '');
    uiButton('保存预算与检查设置', async () => {
      await intelligentAPI('/api/budget', { limit: limit.value, image_price: image.value, video_prices: Object.fromEntries(Object.entries(prices).map(([k, v]) => [k, v.value])), auto_review: auto.checked, speech_model: speech.value });
      await openIntelligence(tab);
    }, body);
    uiButton('核对未知提交与外部队列', async () => {
      const result = await intelligentAPI('/api/reconcile'); showBanner('找回' + result.recovered + '个任务；仍有' + result.unknown + '个结果未知。'); await openIntelligence(tab);
    }, body);
    (session.job.jobs || []).forEach(job => {
      uiNode('p', job.place + ' · ' + taskStatusName(job.status), body);
      if (job.status === 'unknown') uiButton('我已核实这场未受理，允许重试', async () => {
        if (!window.confirm('请先在ComfyUI及供应商队列核实没有受理。确认错误可能重复扣费。确实未受理？')) return;
        await intelligentAPI('/api/jobs/resolve', { fingerprint: job.fingerprint, confirmed_not_submitted: true }); await openIntelligence(tab);
      }, body);
    });
    uiButton('重试失败场，复用成功任务', () => submitEpisode(), body);
    data.ledger.slice().reverse().forEach(entry => uiNode('p', entry.label + ' · ' + entry.status + ' · ' + money(entry.amount), body));
  }
  dialog.oninput = event => { if (event.target.type === 'file' || event.target.dataset.transient) return; intelligentUI.dirty = true; updateWorkspaceHeader(); };
  if (!body.children.length) renderEmpty(body, '还没有内容', '从右侧告诉导演这次想做什么。');
  markWorkspaceNavigation();
}

async function prepareIntelligentPrompts() {
  if (intelligentUI.dirty) throw new Error('请先保存分镜或素材修改。');
  showBanner('正在按统一导演经验与当前分镜准备提示词。');
  const result = await intelligentAPI('/api/prompts', { director_id: state.directorId, messages: state.messages, ratio: state.ratio });
  if (result.scenes) state.scenes = result.scenes;
  await reloadIntelligence();
  if (result.stills) throw new Error('已整理静帧要求，请先生成或上传参考资产，再准备视频提示词。');
  showBanner('导演草稿已准备。请到分镜中查看完整提示词、参考与规格，再确认。');
}

submitEpisode = async function () {
  if (intelligentUI.generationPending) return;
  intelligentUI.generationPending = true; updateWorkspaceHeader();
  try {
    if (intelligentUI.dirty) throw new Error('请先保存工作区修改。');
    if (!state.scenes.length || state.scenes.some(scene => !scene.prompt || scene.needs_rewrite)) throw new Error('请先让导演写完整视频提示词，再到分镜中查看并确认。提交不会自动写词。');
    const args = { ratio: state.ratio, resolution: state.resolution, video_model: state.videoModel || 'seedance', seconds_choice: state.seconds || 'auto' };
    const plan = await intelligentAPI('/api/preflight', args);
    if (!plan.ok) { showBanner(plan.errors.join('\n')); return; }
    if (!await showGenerationPlan('video', plan, args)) return;
    const result = await intelligentAPI('/api/episode', { ...args, preflight_fingerprint: plan.fingerprint });
    addBubble('director', '已按场提交，任务记录已保存。', false);
    await pollEpisode();
    return result;
  } catch (error) { showBanner(error.message || '提交未完成，请查看任务记录。'); }
  finally { intelligentUI.generationPending = false; updateWorkspaceHeader(); }
};

const originalMakeAssets = makeAssets;
makeAssets = async function () {
  if (intelligentUI.generationPending) return;
  intelligentUI.generationPending = true; updateWorkspaceHeader();
  try {
    if (intelligentUI.dirty) throw new Error('请先保存工作区修改。');
    const args = { image_model:state.imageModel || 'banana' };
    const plan = await intelligentAPI('/api/draw-plan',args);
    if (!plan.ok) throw new Error(plan.errors.join('\n'));
    if (!await showGenerationPlan('image', plan,args)) return;
    intelligentUI.imagePlanFingerprint = plan.fingerprint;
    await originalMakeAssets(); await reloadIntelligence();
  } catch (error) { state.waiting = false; showBanner(error.message); }
  finally { intelligentUI.generationPending = false; updateWorkspaceHeader(); }
};

const originalOnUserText = onUserText;
onUserText = async function (text) {
  try { await originalOnUserText(text); await reloadIntelligence(); }
  catch (error) {
    state.waiting = false; document.getElementById('say').value = text;
    showBanner('连接中断，输入已恢复。可重新发送或刷新查看任务状态。');
  } finally { if (!document.getElementById('thinking')) state.waiting = false; }
};

const originalRestore = restore;
restore = function (session) { originalRestore(session); syncIntelligence(session); };

uiButton('准备提示词', prepareIntelligentPrompts, document.getElementById('dock')).id = 'preparePrompts';
uiNode('p', undefined, document.getElementById('composer')).id = 'intelligenceNotice';

uiButton('按题材推荐导演', async () => {
  const brief = window.prompt('这次想做什么？例如：产品使用广告、带货步骤、汽车外观或人物短剧。');
  if (!brief) return;
  const topics = {
    'product-ad': ['广告', '品牌', '产品', '材质', '宣传', '香水'],
    'live-commerce': ['带货', '电商', '直播', '步骤', '演示', '衣服', '商品'],
    'automotive': ['汽车', '车', '内饰', '摩托', '轮胎', '驾驶'],
    'drama': ['短剧', '剧情', '人物', '对白', '故事', '动漫', '电影']
  };
  const ranked = state.directors.map(item => ({ ...item, score: topics[item.id].filter(word => brief.includes(word)).length })).sort((a, b) => b.score - a.score);
  if (!ranked[0] || !ranked[0].score || (ranked[1] && ranked[0].score === ranked[1].score)) {
    showBanner('这个题材可能涉及多个方向，可以手动选择最主要的导演。'); return;
  }
  showBanner('按题材关键词建议：' + ranked[0].name + '导演。仍由你选择。');
  addDirectorCards(ranked, true);
}, document.querySelector('.mast-left'));

window.addEventListener('unhandledrejection', event => {
  showBanner('连接或操作未完成。可刷新恢复项目；已受理任务会保留记录。');
  state.waiting = false;
});

/* Persistent creation workspace. Existing generation APIs remain authoritative. */
const workspaceTabs = ['分镜', '素材', '参考视频', '成片', '项目记忆', '修改与版本', '质量与偏好', '预算与任务'];
const workspaceShell = document.querySelector('.shell');
const workspace = uiNode('main', undefined, workspaceShell); workspace.id = 'workspace';
const workspaceHead = uiNode('header', undefined, workspace); workspaceHead.className = 'workspace-head';
const workspaceTitle = uiNode('div', undefined, workspaceHead);
uiNode('small', 'CREATIVE WORKSPACE', workspaceTitle);
uiNode('h1', '分镜', workspaceTitle).id = 'workspaceTitle';
uiNode('p', '', workspaceTitle).id = 'workspaceProject';
const chatToggle = uiButton('收起导演对话', () => {
  workspaceShell.classList.toggle('chat-collapsed');
  chatToggle.textContent = workspaceShell.classList.contains('chat-collapsed') ? '展开导演对话' : '收起导演对话';
  chatToggle.setAttribute('aria-expanded', String(!workspaceShell.classList.contains('chat-collapsed')));
}, workspaceHead);
chatToggle.setAttribute('aria-expanded', 'true');
const actionStrip = uiNode('section', undefined, workspace); actionStrip.className = 'next-action';
uiNode('div', undefined, actionStrip).id = 'nextActionCopy';
const nextButton = uiButton('下一步', () => workspaceNextAction(), actionStrip); nextButton.id = 'nextActionButton';
const workspaceStatus = uiNode('div', undefined, workspace); workspaceStatus.className = 'workspace-status';
workspaceStatus.append(document.getElementById('banner'), document.getElementById('taskLine'));
const workspaceSettings = uiNode('details', undefined, workspace); workspaceSettings.className = 'workspace-settings';
const settingsSummary = uiNode('summary', '生成设置与任务控制', workspaceSettings);
workspaceSettings.append(document.getElementById('dock'));
const workspaceBody = uiNode('div', undefined, workspace); workspaceBody.id = 'workspaceBody';
const workNav = uiNode('nav', undefined, document.getElementById('readout')); workNav.id = 'workNav'; workNav.setAttribute('aria-label', '项目工作区');
document.getElementById('readout').prepend(workNav);
workspaceTabs.forEach((tab, index) => {
  const b = uiButton(tab, () => openIntelligence(tab), workNav);
  b.dataset.tab = tab;
  b.appendChild(uiNode('small', String(index + 1).padStart(2, '0')));
});
const projectSwitch = uiNode('label', '当前项目', workNav); projectSwitch.className = 'project-switch';
const projectSelect = uiNode('select', undefined, projectSwitch); projectSelect.setAttribute('aria-label', '切换项目');
projectSelect.onchange = async () => { try { await openProject(projectSelect.value); } catch (e) { showBanner(e.message); } };
const chatLabel = uiNode('div', '导演对话 · 想法与局部修改', document.getElementById('thread')); chatLabel.className = 'chat-label';
document.getElementById('thread').prepend(chatLabel);
document.getElementById('say').placeholder = '告诉导演你的想法，或点名修改某一场…';
document.getElementById('dockSubmit').textContent = '视频生成计划';
document.getElementById('dockBanana').textContent = '图片生成计划';
document.querySelectorAll('.readout .k').forEach((n, i) => n.textContent = ['导演', '分镜', '素材', '画幅', '输出规格'][i]);

function fieldName(key) {
  return ({place: '地点', who: '画面主体', remember: '观众记住什么', seconds: '时长', prompt: '提示词', picture: '素材要求', asset_ids: '素材引用', reference_ids: '身份参考', file: '素材文件'})[key] || key;
}
function registerEditor(input, item, key) {
  input.dataset.targetId = item.id; input.dataset.field = key;
  input.dataset.original = JSON.stringify(key === 'reference_ids' ? (item[key] || []) : key === 'seconds' ? Number(item[key]) : String(item[key] ?? ''));
  if (key === 'seconds') { input.type = 'number'; input.min = '4'; input.max = '30'; input.step = '1'; }
}
function collectEditorChanges(parent) {
  return Array.from(parent.querySelectorAll('[data-target-id]')).flatMap(input => {
    const field = input.dataset.field;
    const value = field === 'reference_ids' ? Array.from(input.selectedOptions).map(o => o.value) : field === 'seconds' ? Number(input.value) : input.value;
    return JSON.stringify(value) === input.dataset.original ? [] : [{target_id: input.dataset.targetId, field, value}];
  });
}
function displayValue(value) { return typeof value === 'string' ? value : JSON.stringify(value ?? '—', null, 2); }
function renderEmpty(parent, title, detail) {
  const node = uiNode('div', undefined, parent); node.className = 'empty-state';
  uiNode('small', '开始创作', node); uiNode('h2', title, node); uiNode('p', detail, node);
  uiButton('跟导演聊聊', () => {
    workspaceShell.classList.remove('chat-collapsed'); chatToggle.textContent = '收起导演对话'; chatToggle.setAttribute('aria-expanded', 'true'); document.getElementById('say').focus();
  }, node);
}
function markWorkspaceNavigation() {
  workNav.querySelectorAll('button[data-tab]').forEach(b => {
    const on = b.dataset.tab === intelligentUI.tab; b.classList.toggle('active', on);
    if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
}
function workspaceNextAction() {
  const session = intelligentUI.session;
  if (!session || session.project_id !== state.projectId) return reloadIntelligence();
  if (session.intelligence.pending_plan) return openIntelligence('修改与版本');
  if (!state.scenes.length) { document.getElementById('say').focus(); return; }
  if (state.assets.some(a => a.kind !== '音频' && (!a.file || a.needs_redraw))) return openIntelligence('素材');
  if (state.scenes.some(s => !s.prompt || s.needs_rewrite || !s.confirmation)) return openIntelligence('分镜');
  if (isFilmCurrent(session)) return openIntelligence('成片');
  return submitEpisode();
}
function isFilmCurrent(session) {
  return session?.job?.phase === 'done' && !state.scenes.some(s => !s.prompt || s.needs_rewrite) && !state.assets.some(a => a.needs_redraw) && !session.intelligence.revisions.some(r => r.at > session.job.started);
}
function updateWorkspaceHeader() {
  const active = !!state.projectId && !state.browsing && !!state.directorId;
  workspaceShell.classList.toggle('project-open', active);
  const composer = document.getElementById('composer');
  for (const id of ['banner', 'taskLine', 'dock']) {
    const node = document.getElementById(id), parent = active ? (id === 'dock' ? workspaceSettings : workspaceStatus) : composer;
    if (node.parentElement !== parent) {
      if (active) parent.append(node);
      else parent.insertBefore(node, composer.querySelector('.row'));
    }
  }
  if (!active) return;
  const session = intelligentUI.session?.project_id === state.projectId ? intelligentUI.session : null;
  document.getElementById('workspaceTitle').textContent = intelligentUI.tab;
  const project = state.projectList.find(p => p.id === state.projectId);
  document.getElementById('workspaceProject').textContent = (project?.name || '当前项目') + ' / ' + (state.directorName || '导演') + '导演';
  document.getElementById('readScenes').textContent = pad(state.scenes.length);
  document.getElementById('readAssets').textContent = pad(state.assets.length);
  settingsSummary.textContent = '生成设置与任务控制 · ' + state.ratio + ' / ' + state.resolution + ' / ' + choiceFace('video-model');
  if (projectSelect.dataset.project !== state.projectId || projectSelect.options.length !== state.projectList.length) {
    projectSelect.replaceChildren(); state.projectList.forEach(p => { const o = uiNode('option', p.name || p.id, projectSelect); o.value = p.id; });
    projectSelect.value = state.projectId; projectSelect.dataset.project = state.projectId;
  }
  let title = '告诉导演这次想做什么', detail = '从一句想法或上传剧本开始，分镜与素材会保存在这里。', action = '开始对话';
  if (state.scenes.length) {
    title = '分镜已就绪，先检查素材'; detail = state.scenes.length + ' 场 · 计划 ' + state.scenes.reduce((n, s) => n + Number(s.seconds || 0), 0) + ' 秒'; action = '查看素材';
    if (!state.assets.some(a => a.kind !== '音频' && (!a.file || a.needs_redraw))) {
      title = '素材已就绪，准备视频提示词'; action = '准备提示词';
      if (!state.scenes.some(s => !s.prompt || s.needs_rewrite)) { title = '检查提示词确认与生成计划'; detail += ' · 提交前查看新增任务、复用任务与费用'; action = '查看生成计划'; }
    }
  }
  if (isFilmCurrent(session)) { title = '成片已完成'; detail = '可播放、下载，或查看质量检查证据。'; action = '查看成片'; }
  if (session?.intelligence?.pending_plan) { title = '导演提出了修改，等待你应用'; detail = '查看前后变化，再决定是否更新项目。'; action = '查看修改'; }
  const copy = document.getElementById('nextActionCopy'); copy.replaceChildren(); uiNode('strong', title, copy); uiNode('p', detail, copy);
  nextButton.textContent = action;
  const busy = ['running', 'paused', 'stopping'].includes(currentTask.state) || intelligentUI.generationPending;
  nextButton.disabled = busy || !!intelligentUI.dirty;
  ['dockBanana', 'dockSubmit', 'preparePrompts'].forEach(id => { document.getElementById(id).disabled = busy || !!intelligentUI.dirty; });
  if (intelligentUI.dirty) uiNode('small', '有未保存的编辑，请先保存。', copy);
  markWorkspaceNavigation();
}
function renderComparison(parent, title, before, after) {
  const row = uiNode('article', undefined, parent); row.className = 'comparison';
  uiNode('h4', title, row);
  const columns = uiNode('div', undefined, row); columns.className = 'comparison-columns';
  [[before, '修改前'], [after, '修改后']].forEach(([value, label]) => { const cell = uiNode('div', undefined, columns); uiNode('small', label, cell); uiNode('pre', displayValue(value), cell); });
}
function renderRevisions(body, session) {
  uiNode('h3', '编辑记录与版本对比', body);
  if (!session.intelligence.revisions.length) uiNode('p', '保存分镜或素材要求后，这里会记录前后版本。', body);
  const revisions = session.intelligence.revisions;
  revisions.slice().reverse().forEach((revision, reversedIndex) => {
    const details = uiNode('details', undefined, body); details.className = 'revision';
    uiNode('summary', new Date(revision.at * 1000).toLocaleString() + ' · ' + revision.label, details);
    const index = revisions.length - 1 - reversedIndex;
    const after = revisions[index + 1] || session;
    for (const kind of ['scenes', 'assets']) {
      const oldRows = revision[kind] || [], newRows = after[kind] || [];
      newRows.forEach((item, n) => {
        const old = oldRows.find(x => x.id === item.id);
        if (!old) return;
        ['place', 'who', 'remember', 'seconds', 'prompt', 'picture', 'reference_ids', 'asset_ids', 'file'].forEach(key => {
          if (JSON.stringify(old[key]) !== JSON.stringify(item[key])) renderComparison(details, (item.name || '第' + (n + 1) + '场') + ' · ' + fieldName(key), old[key], item[key]);
        });
      });
    }
  });
}
function renderReviewEvidence(section, review, session) {
  const layout = uiNode('div', undefined, section); layout.className = 'review-evidence';
  const report = uiNode('div', undefined, layout); uiNode('pre', review.text, report); uiNode('small', review.limitations || '模型判断需人工确认。', report);
  const evidence = uiNode('div', undefined, layout); evidence.className = 'evidence-grid';
  (review.evidence || []).slice(0, 20).forEach(e => {
    if (!e.frame && !e.file) return;
    const figure = uiNode('figure', undefined, evidence);
    const img = uiNode('img', undefined, figure); img.src = mediaUrl(e.frame ? '/review-frames/' : '/library/', e.frame || e.file);
    const asset = session.assets.find(a => a.id === e.asset_id);
    img.alt = e.frame ? (session.scenes.find(s => s.id === e.scene_id)?.place || '视频') + ' · ' + e.seconds + ' 秒' : asset?.name || '检查素材';
    img.onclick = () => openViewer(img.src); uiNode('figcaption', img.alt, figure);
  });
  if (!evidence.children.length) uiNode('p', '这条记录未包含画面证据。', evidence);
}
function renderAssetTools(body, session) {
  const bar = uiNode('div', undefined, body); bar.className = 'asset-tools';
  ['人物', '场景', '道具', '音频'].forEach(kind => {
    const label = uiNode('label', '上传' + kind, bar); label.className = 'filebtn'; label.tabIndex = 0; label.setAttribute('role', 'button');
    const input = uiNode('input', undefined, label); input.type = 'file'; input.accept = kind === '音频' ? '.mp3,.wav,.m4a' : '.png,.jpg,.jpeg,.webp';
    label.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } };
    input.onchange = async e => { try { await sendAsset(kind, e); await openIntelligence('素材'); } catch (err) { showBanner(err.message); } };
  });
  uiButton('寻找风格参考', () => { workspaceShell.classList.remove('chat-collapsed'); return findStyle(); }, bar);
  uiButton('请导演写资产提示词', () => draftAssetPrompts(), bar);
  uiButton('查看图片生成计划', makeAssets, bar);
  if (!session.assets.length) renderEmpty(body, '素材会收在这里', '让导演整理需要的人物、场景和道具，或直接上传参考素材。');
  session.assets.filter(a => a.kind === '音频' && a.file).forEach(a => {
    const row = uiNode('article', undefined, body); uiNode('h3', '音频 · ' + a.name, row);
    const audio = uiNode('audio', undefined, row); audio.controls = true; audio.src = mediaUrl('/library/', a.file);
    uiButton('删除音频', async () => { await deleteAsset(a.file, a.kind, 'board'); await openIntelligence('素材'); }, row);
  });
}
function renderFinishedFilms(body, session) {
  if (!session.job?.film || session.job.phase !== 'done') {
    renderEmpty(body, '成片还在路上', '确认分镜、素材与提示词后，查看生成计划并提交。受理后的任务可在预算与任务中跟踪。');
  } else {
    if (state.scenes.some(s => s.needs_rewrite) || state.assets.some(a => a.needs_redraw) || session.intelligence.revisions.some(r => r.at > session.job.started)) uiNode('p', '这条成片生成后项目已有修改，视频可能对应之前的版本。', body);
    const video = uiNode('video', undefined, body); video.controls = true; video.playsInline = true; video.src = '/film?project=' + encodeURIComponent(state.projectId); video.className = 'workspace-film';
    const save = uiNode('a', '下载成片', body); save.href = '/film?save=1&project=' + encodeURIComponent(state.projectId); save.setAttribute('download', ''); save.className = 'save-film';
    uiButton('查看画面质量与证据', () => openIntelligence('质量与偏好'), body);
  }
  uiNode('h3', '分场任务', body);
  (session.job?.jobs || []).forEach(job => { const row = uiNode('article', undefined, body); uiNode('strong', job.place + ' · ' + job.seconds + ' 秒', row); uiNode('p', taskStatusName(job.status) + (job.error ? ' · ' + job.error : ''), row); });
}
function taskStatusName(status) { return ({done:'已完成', queued:'已受理', unknown:'受理结果待核实', error:'失败', submitting:'正在提交', not_submitted:'确认未受理'})[status] || status; }

function showChoiceDialog(title, build, acceptLabel = '确认') {
  return new Promise(resolve => {
    const dialog = uiNode('dialog', undefined, document.body); dialog.className = 'generation-dialog';
    dialog.setAttribute('aria-label', title);
    const head = uiNode('header', undefined, dialog); uiNode('h2', title, head);
    const content = uiNode('section', undefined, dialog); build(content);
    const footer = uiNode('footer', undefined, dialog);
    let accepted = false;
    uiButton('取消', () => dialog.close(), footer);
    uiButton(acceptLabel, () => { accepted = true; dialog.close(); }, footer).className = 'primary';
    dialog.addEventListener('close', () => { dialog.remove(); resolve(accepted); }, {once: true});
    dialog.showModal(); footer.querySelector('button').focus();
  });
}
function confirmLeaveWorkspace() {
  return showChoiceDialog('有未保存的编辑', p => uiNode('p', '离开会放弃当前输入。选择取消可回到工作区继续保存。', p), '放弃输入并继续');
}
async function showGenerationPlan(kind, plan, args = {}) {
  if (intelligentUI.dirty) { showBanner('请先保存工作区中的编辑，再查看生成计划。'); return false; }
  const projectId = state.projectId;
  const accepted = await showChoiceDialog(kind === 'video' ? '视频生成计划' : '图片生成计划', body => {
    uiNode('p', kind === 'video' ? choiceFace('video-model') + ' · ' + args.ratio + ' · ' + args.resolution + ' · ' + plan.total_seconds + ' 秒' : choiceFace('image-model') + ' · 21:9 · 1K', body);
    uiNode('p', '以下是已确认的实际提交内容。生成入口只校验和提交，不调用模型改词。', body);
    const stats = uiNode('div', undefined, body); stats.className = 'plan-stats';
    const rows = kind === 'video' ? plan.scenes : plan.assets;
    const reused = kind === 'video' ? rows.filter(r => r.reuse).length : 0;
    uiNode('strong', '新增 ' + (rows.length - reused) + (kind === 'video' ? ' 场' : ' 张'), stats);
    uiNode('strong', '复用 ' + reused + ' 场', stats).hidden = kind !== 'video';
    uiNode('strong', kind === 'image' && !rows.length ? '清单待确认，费用未知' : money(plan.estimate), stats);
    rows.forEach(r => {
      const row = uiNode('article', undefined, body);
      uiNode('strong', kind === 'video' ? '第' + r.index + '场 · ' + (r.place || '') : r.kind + ' · ' + r.name, row);
      renderPromptDetails(row,r);
      uiNode('p', kind === 'video' ? r.seconds + ' 秒 · ' + r.images + ' 图 / ' + r.audios + ' 音频 · ' + (r.reuse ? '复用已受理任务' : '新增生成 · ' + money(r.estimate)) : '生成或重画这张素材', row);
    });
    if (!rows.length) uiNode('p', '没有待生成素材，请先整理并确认资产提示词。', body);
    uiNode('small', '费用按填写的单价估算，实际收费以供应商为准。写作、视觉检查、语音识别费用另计。', body);
    if (kind === 'image') uiNode('p', '已有且不需更新的素材将保留；每张实际提交前仍会检查预算。', body);
  }, '确认' + (kind === 'video' ? '提交' : '生成'));
  if (projectId !== state.projectId) throw new Error('项目已切换，请重新检查生成计划。');
  return accepted;
}

const workspacePaintChrome = paintChrome;
let workspaceProjectId = '';
let workspaceSyncQueued = false;
paintChrome = function() {
  workspacePaintChrome(); updateWorkspaceHeader();
  if (workspaceShell.classList.contains('project-open') && workspaceProjectId !== state.projectId) {
    workspaceProjectId = state.projectId; intelligentUI.dirty = false; intelligentUI.tab = '分镜';
    openIntelligence('分镜').catch(e => showBanner(e.message));
  } else if (workspaceShell.classList.contains('project-open') && !intelligentUI.dirty && !workspaceSyncQueued && intelligentUI.session?.project_id === state.projectId && (state.scenes !== intelligentUI.session.scenes || state.assets !== intelligentUI.session.assets)) {
    workspaceSyncQueued = true;
    reloadIntelligence().catch(e => showBanner(e.message)).finally(() => { workspaceSyncQueued = false; });
  }
};
const workspacePaintTask = paintTask;
paintTask = function(task) { const previous = currentTask.state; workspacePaintTask(task); if (task.state === 'idle' && previous !== 'idle' && state.projectId && !intelligentUI.dirty) reloadIntelligence().catch(e => showBanner(e.message)); if (task.state !== previous && ['running','paused','stopping'].includes(task.state)) workspaceSettings.open = true; updateWorkspaceHeader(); };
const workspaceShowFilm = showFilm;
showFilm = function(data) {
  workspaceShowFilm(data);
  if (intelligentUI.session?.project_id === state.projectId) {
    intelligentUI.session.job = data;
    if (!intelligentUI.dirty && intelligentUI.tab === '成片') renderIntelligenceSession(intelligentUI.session, '成片');
  }
  updateWorkspaceHeader();
};
const workspaceOriginalOpen = openProject;
openProject = async function(id) {
  if (intelligentUI.dirty && !await confirmLeaveWorkspace()) { projectSelect.value = state.projectId; return; }
  intelligentUI.dirty = false; workspaceProjectId = ''; await workspaceOriginalOpen(id);
};
const workspaceGoFolders = goFolders;
goFolders = async function() {
  if (intelligentUI.dirty && !await confirmLeaveWorkspace()) return;
  intelligentUI.dirty = false; workspaceProjectId = ''; await workspaceGoFolders();
};
const workspaceOpenAssets = openAssets;
openAssets = function() { workspaceOpenAssets(); return openIntelligence('素材'); };
const workspaceShowPocket = showAssetPocket;
showAssetPocket = function(kind) { workspaceShowPocket(kind); if (!intelligentUI.dirty) openIntelligence('素材').catch(e => showBanner(e.message)); };
window.addEventListener('beforeunload', event => { if (intelligentUI.dirty) { event.preventDefault(); event.returnValue = ''; } });
let workspaceRefreshBusy = false;
setInterval(async () => {
  if (workspaceRefreshBusy || !workspaceShell.classList.contains('project-open') || intelligentUI.dirty || document.querySelector('dialog[open]') || !['running', 'paused', 'stopping'].includes(currentTask.state)) return;
  workspaceRefreshBusy = true;
  try { await reloadIntelligence(); } catch (_) {} finally { workspaceRefreshBusy = false; }
}, 6000);
updateWorkspaceHeader();


function generationArgs(kind) {
  return kind === 'image' ? {image_model:state.imageModel || 'banana'} : {ratio:state.ratio || '16:9',resolution:state.resolution || '720p',video_model:state.videoModel || 'seedance',seconds_choice:state.seconds || 'auto'};
}
function renderPromptDetails(parent, data) {
  uiNode('pre', data.prompt || '', parent).className = 'final-prompt';
  if (data.spec) {
    const s=data.spec,model=({banana:'Banana',seedream:'Seedream',image25:'GPT Image',seedance:'Seedance 2.5',h3:'H3'})[s.model] || s.model;
    uiNode('p',model+' · '+s.ratio+' · '+s.resolution+(s.seconds ? ' · '+s.seconds+'秒' : '')+(s.actual_seconds ? ' · 实际输出约'+s.actual_seconds+'秒' : '')+(s.canvas ? ' · '+s.canvas.join('×') : ''),parent);
    const mapping=Object.entries(s.reference_mapping || {}).flatMap(([kind,map])=>Object.entries(map).filter(([before,after])=>Number(before)!==Number(after)).map(([before,after])=>'@'+kind+before+' → @'+kind+after));
    if (mapping.length) uiNode('small','参考编号对应：'+mapping.join('；'),parent);
  }
  const refs = uiNode('div', undefined, parent); refs.className = 'evidence-grid';
  (data.references || []).forEach((r,n) => {
    const figure = uiNode('figure', undefined, refs);
    if (r.kind !== '音频') {
      const img = uiNode('img',undefined,figure); img.src = mediaUrl(r.source === 'refs' ? '/refs/' : '/library/',r.file); img.alt = r.name;
      img.onclick=()=>openViewer(img.src);
    } else { const audio=uiNode('audio',undefined,figure);audio.controls=true;audio.src=mediaUrl('/library/',r.file); }
    uiNode('figcaption',r.name + ' · '+r.file + (r.version ? ' · v'+r.version : ''),figure);
  });
  if (!data.references?.length) uiNode('small','无参考文件',parent);
}
async function confirmPrompt(kind,targetId) {
  if (intelligentUI.dirty) throw new Error('请先保存编辑，再查看并确认。');
  const projectId=state.projectId,args=generationArgs(kind);
  const preview=await intelligentAPI('/api/prompt-preview',{kind,target_id:targetId,...args});
  const ok=await showChoiceDialog('确认实际提交提示词 · '+preview.name,body=>{
    uiNode('p','确认后提交此处全文、参考与规格。任何变化都会要求重新确认。',body);
    if (preview.source_prompt !== preview.prompt) uiNode('p','参考编号已按本次文件顺序重排；下面是实际提交的最终文本。',body);
    renderPromptDetails(body,preview);
  },'确认这份提示词');
  if (!ok) return;
  if (state.projectId !== projectId || JSON.stringify(args)!==JSON.stringify(generationArgs(kind))) throw new Error('项目或生成设置已变化，请重新查看。');
  const session=await intelligentAPI('/api/prompt-confirm',{kind,target_id:targetId,...args,fingerprint:preview.fingerprint});
  syncIntelligence(session);showBanner('已确认。生图或提交视频时不会再次改写这份提示词。');
}
async function draftAssetPrompts(targetId) {
  if (intelligentUI.dirty) throw new Error('请先保存资产编辑。');
  showBanner('导演正在写完整资产提示词草稿。');
  const result=await intelligentAPI('/api/assets/prompts',targetId ? {target_id:targetId} : {});
  syncIntelligence(result);await openIntelligence('素材');
  if (result.talk) addBubble('director',result.talk,false);
}
function renderDirectorDrafts(parent,session) {
  (session.intelligence.director_drafts || []).forEach(draft=>{
    const scene=session.scenes.find(s=>s.id===draft.scene_id);
    if (!scene) return;
    const row=uiNode('article',undefined,parent);uiNode('h3','导演对话中的草稿 · '+scene.place,row);
    uiNode('pre',draft.prompt,row);
    uiButton('将这份草稿放入该场',async()=>{
      if (intelligentUI.dirty) throw new Error('请先保存编辑。');
      syncIntelligence(await intelligentAPI('/api/director-draft/adopt',{id:draft.id}));
      showBanner('已原样放入分镜，请查看并确认后提交。');
    },row);
  });
}
function renderSourceVideos(parent,session) {
  uiNode('p','上传本地参考片，解析内容、主体、镜头、运镜、转场与视觉风格。视频保存在本项目，最多10个，每个200MB / 10分钟。',parent);
  uiNode('p','解析会把最多24张带时间点的关键帧交给当前写作模型，需要模型支持图片。可选语音转写另调语音接口；这些费用未计入生成预算。',parent);
  const label=uiNode('label','上传参考视频',parent);label.className='filebtn';
  const input=uiNode('input',undefined,label);input.type='file';input.accept='.mp4,.mov,.mkv,.webm,.m4v';
  const progress=uiNode('p','',parent);
  input.onchange=async()=>{
    const file=input.files[0];if (!file) return;
    input.disabled=true;
    try {
      if (file.size>200*1024*1024) throw new Error('视频超过200MB，请先压缩或截取。');
      progress.textContent='正在上传并读取视频信息…';
      const res=await fetch('/api/source-video/upload?name='+encodeURIComponent(file.name),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
      const data=await res.json();if (!res.ok) throw new Error(data.error);
      await reloadIntelligence();showBanner('视频已上传。点击解析内容后，导演才会分析。');
    } catch(e) { progress.textContent=e.message;showBanner(e.message); }
    finally { input.disabled=false; }
  };
  const rows=session.intelligence.source_videos || [];
  if (!rows.length) uiNode('p','还没有参考视频。也可以从下方上传入口进入。',parent);
  rows.slice().reverse().forEach(v=>{
    const row=uiNode('article',undefined,parent);
    uiNode('h3',v.name,row);uiNode('p',Number(v.seconds).toFixed(1)+' 秒 · '+v.width+'×'+v.height+' · '+({uploaded:'已上传',analyzing:'解析中',analyzed:'已解析',error:'解析失败'}[v.status] || v.status),row);
    if (v.error) uiNode('p',v.error,row).className='smart-error';
    const speechLabel=uiNode('label',undefined,row),speech=uiNode('input',undefined,speechLabel);speech.type='checkbox';speech.dataset.transient='true';
    speech.disabled=!v.has_audio || !session.intelligence.speech_model;
    uiNode('span','同时转写对白（需要在预算与任务配置语音模型）',speechLabel);
    if (v.status !== 'analyzing') uiButton(v.analysis ? '重新解析' : '解析内容',async()=>{
      syncIntelligence(await intelligentAPI('/api/source-video/analyze',{id:v.id,transcribe:speech.checked}));
    },row);
    if (v.analysis) {
      uiNode('pre',v.analysis,row);uiNode('small',v.limitations,row);
      uiNode('p',v.use_for_creation ? '导演已将这份分析作为创作参考；提示词不会自动修改。' : '当前仅供查看，未加入导演创作依据。',row);
      uiButton(v.use_for_creation ? '停用这份创作参考' : '用作导演创作依据',async()=>{
        syncIntelligence(await intelligentAPI('/api/source-video/use',{id:v.id,enabled:!v.use_for_creation}));
        showBanner('创作依据已变化，原有提示词需要重新查看并确认。');
      },row);
    }
    const frames=uiNode('div',undefined,row);frames.className='evidence-grid';
    (v.frames || []).forEach(f=>{
      const figure=uiNode('figure',undefined,frames),img=uiNode('img',undefined,figure);
      img.src='/source-video-frames/'+encodeURIComponent(v.id)+'/'+encodeURIComponent(f.file)+'?project='+encodeURIComponent(state.projectId);
      img.alt=f.seconds+'秒关键帧';img.onclick=()=>openViewer(img.src);uiNode('figcaption',img.alt,figure);
    });
    (v.transcripts || []).forEach(t=>uiNode('p',t.start+'–'+t.end+'秒对白：'+t.text,row));
  });
}
const sourceVideoOpen=uiButton('上传参考视频',()=>openIntelligence('参考视频'));
sourceVideoOpen.className='filebtn';sourceVideoOpen.id='sourceVideoOpen';
document.getElementById('composer').querySelector('.row').insertBefore(sourceVideoOpen,document.getElementById('say'));
