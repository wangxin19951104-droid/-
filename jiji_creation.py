"""Guided setup and model-specific director knowledge. Navigation never generates."""
import copy
import jiji_core as core

PROFILES = {'seedance': ('Seedance 2.5', 'Seedance2.5.md'), 'h3': ('H3', 'H3.md')}
STYLES = {
    'cinema': '写实电影：自然材质、克制色彩、有明确动机的光线，镜头为叙事服务。',
    'photoreal': '超写实摄影：真实皮肤与材质、光学景深、细节优先，避免塑料感。',
    'cinematic': '电影质感：宽银幕构图、胶片颗粒、戏剧光线与有节奏的镜头运动。',
    'cg3d': '三维 CG：体积光、PBR 材质、精确空间关系与可复用资产比例。',
    'animation': '动画：统一角色比例和线条/材质，动作清晰，保持每场的造型一致。',
    'anime': '日漫：清晰线稿、平涂色彩、夸张但可读的动作与表情，保持角色设定一致。',
    'illustration': '插画绘本：可见笔触、概括造型、统一配色与页面构图。',
    'watercolor': '水彩手绘：透明叠色、纸张肌理、柔和边缘和自然晕染。',
    'noir': '黑色电影：高反差光影、阴影叙事、冷峻气氛与有限色彩。',
    'retro': '复古胶片：褪色色彩、颗粒、灰尘划痕和怀旧光晕。',
    'cyberpunk': '赛博朋克：霓虹反射、湿润街景、科技密度与强烈冷暖对比。',
    'minimal': '极简设计：留白、几何秩序、克制色彩和清楚的信息层级。',
    'commercial': '商业广告：产品主角、清洁灯光、高识别度构图与可读卖点。',
    'studio': '商业棚拍：干净构图、准确产品比例、可辨材质与受控灯光。',
    'documentary': '纪实手持：现场光、呼吸感、观察距离与真实环境细节。',
    'music-video': '音乐 MV：节奏剪辑、强色彩、舞台能量与可记忆的视觉符号。',
    'reference': '跟随已启用参考：先描述参考的色彩、构图、节奏和材质，再提取可迁移规则；不照搬人物或品牌。',
    'custom': '遵循用户填写的具体视觉要求。',
}


def profile(host):
    key = host.MODE.get('video') or 'seedance'
    name, filename = PROFILES.get(key, PROFILES['seedance'])
    return name, (host.SKILLS / filename).read_text(encoding='utf-8')


def creative_context(state):
    data = state.get('creation') or {}
    return {k: data.get(k, '') for k in ('genre', 'source_mode', 'brief', 'visual_style', 'custom_style')}


def update(host, data):
    h = host
    if h.TASK.get('state') != 'idle':
        raise RuntimeError('当前任务结束后才能修改创作方向。')
    state = h.active().intelligence
    old = copy.deepcopy(state.get('creation') or {})
    new = {**{'genre': h.CHAT.get('director_id') or '', 'source_mode': 'idea', 'brief': '',
              'visual_style': 'cinema', 'custom_style': '', 'stage': 'input', 'ready': False}, **old}
    for key in ('genre', 'source_mode', 'brief', 'visual_style', 'custom_style', 'stage'):
        if key in data:
            if not isinstance(data[key], str): raise RuntimeError('创作设置需要文本。')
            new[key] = data[key].strip()
    engine = data.get('engine', h.MODE.get('video') or 'seedance')
    if engine not in PROFILES: raise RuntimeError('请选择 Seedance 2.5 或 H3。')
    director = h.director_by_id(new['genre'])
    if director is None: raise RuntimeError('请选择视频类型。')
    if new['source_mode'] not in {'idea', 'script', 'table', 'video'}: raise RuntimeError('输入方式不支持。')
    if new['visual_style'] not in STYLES: raise RuntimeError('画面风格不支持。')
    if new['stage'] not in {'input', 'director', 'discussion', 'assets', 'prompts', 'film'}: raise RuntimeError('步骤不支持。')
    if len(new['brief']) > 12000 or len(new['custom_style']) > 1200: raise RuntimeError('创意或风格描述太长。')
    if 'ready' in data:
        if not isinstance(data['ready'], bool): raise RuntimeError('创作确认状态不支持。')
        new['ready'] = data['ready']
    if new['ready']:
        if not (new['brief'] or h.SCRIPT.get('text') or state.get('source_videos')):
            raise RuntimeError('先写一个想法、上传剧本、表格或参考视频。')
        if new['visual_style'] == 'custom' and not new['custom_style']: raise RuntimeError('请填写自定义风格。')
        new['ready'] = True
    changed = creative_context({'creation': old}) != creative_context({'creation': new})
    engine_changed = engine != h.MODE.get('video')
    if changed or engine_changed:
        if state.get('pending_plan'): raise RuntimeError('先应用或放弃待处理修改，再调整创作方向。')
        for scene in h.SCENES:
            scene.pop('confirmation', None)
            if scene.get('prompt'): scene['needs_rewrite'] = True
        for asset in h.ASSETS: asset.pop('confirmation', None)
        state['director_drafts'] = []
        h.PROMPT_FROM['text'] = ''
    state['creation'] = new
    h.MODE['video'] = engine
    if engine == 'h3': h.CHAT['resolution'] = '720p'
    h.CHAT.update({'director_id': director[0], 'director_name': director[1], 'step': 'script' if not new['ready'] else 'assets'})
    h.save_session()
    return h.session_public()


def plan(host):
    """Explicitly turn the discussed brief into scenes; do not overwrite an existing plan."""
    h = host
    if h.TASK.get('state') != 'idle': raise RuntimeError('等当前任务结束后再整理分镜。')
    if h.SCENES: raise RuntimeError('已有分镜，请在分镜区编辑，或跟导演提出局部修改。')
    creation = h.active().intelligence.get('creation') or {}
    if not creation.get('ready'): raise RuntimeError('先完成输入与导演选择。')
    h.task_begin('write', '整理已讨论的分镜')
    try:
        if h.SCRIPT.get('text'):
            raw = h.call_model([{'role': 'system', 'content': h.classify_prompt(h.CHAT['director_id'])},
                                {'role': 'user', 'content': '按剧本和当前已确认讨论整理分镜。' + h.talk_text(12)}])
            scenes = h.split_scenes(raw)
            for asset in h.split_assets(raw):
                if not any(a.get('name') == asset['name'] for a in h.ASSETS): h.ASSETS.append(asset)
        else:
            messages = list(h.CHAT.get('messages') or [])
            if creation.get('brief'): messages.insert(0, {'role': 'user', 'content': creation['brief']})
            scenes = h.scenes_from_talk(h.CHAT['director_id'], messages)
        if not scenes: raise RuntimeError('未能整理出分镜，请补充故事或重试。')
        h.SCENES.clear(); h.SCENES.extend(scenes)
        h.INTELLIGENCE.identify()
        creation['stage'] = 'assets'
        h.save_session()
        return h.session_public()
    finally:
        h.task_finish('write')
