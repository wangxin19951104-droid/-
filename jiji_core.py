"""Pure project, reference, change-plan and storage primitives."""
import copy
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path


def atomic_write(path, text, backup=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if backup and path.is_file():
            previous = path.read_text(encoding='utf-8')
            # Never replace a healthy JSON backup with corrupt JSON.
            if path.suffix != '.json' or valid_json(previous):
                atomic_write(path.with_name(path.name + '.bak'), previous, False)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def valid_json(text):
    try:
        json.loads(text)
        return True
    except (TypeError, ValueError):
        return False


def read_json(path, default):
    path = Path(path)
    for candidate in (path, path.with_name(path.name + '.bak')):
        try:
            return json.loads(candidate.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
    return copy.deepcopy(default)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def ensure_ids(rows, prefix):
    seen = set()
    for row in rows:
        if not row.get('id') or row['id'] in seen:
            row['id'] = prefix + '_' + uuid.uuid4().hex[:16]
        seen.add(row['id'])
        row.setdefault('version', 1)


def merge_history(stored, incoming):
    """Accept an append or a suffix update, never replace earlier history."""
    def clean(rows):
        result = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            role = 'assistant' if row.get('role') == 'director' else row.get('role')
            text = str(row.get('content') or '')[:16000]
            if role in ('user', 'assistant') and text.strip():
                result.append({'role': role, 'content': text})
        return result
    old, new = clean(stored), clean(incoming)
    if not old:
        return new
    if not new:
        return old
    if new[:len(old)] == old:
        return new
    if old[:len(new)] == new:
        return old
    for overlap in range(min(len(old), len(new)), 0, -1):
        if old[-overlap:] == new[:overlap]:
            return old + new[overlap:]
    # Stale snapshots cannot replace history; a new user turn may append.
    return old + [new[-1]] if new[-1]['role'] == 'user' and new[-1] != old[-1] else old


def bind_references(prompt, assets, kind, limit, frozen=None):
    pool = [a for a in assets if a.get('file') and ((a.get('kind') == '音频') == (kind == '音频'))]
    numbers = [int(number) for number in re.findall(r'@' + kind + r'\s*(\d+)', prompt)]
    if not numbers:
        return [], {}, prompt
    selected, mapping = [], {}
    for number in numbers:
        if frozen is not None:
            asset = next((a for a in pool if a.get('id') == frozen.get(str(number))), None)
            if asset is None:
                raise RuntimeError(f'@{kind}{number} 绑定的素材已删除或缺失，请重新绑定。')
        else:
            if number < 1 or number > len(pool):
                raise RuntimeError(f'@{kind}{number} 没有对应素材，请重新绑定。')
            asset = pool[number - 1]
        if asset['file'] not in [a['file'] for a in selected]:
            selected.append(asset)
        mapping[number] = 1 + next(i for i, a in enumerate(selected) if a['file'] == asset['file'])
    if len(selected) > limit:
        raise RuntimeError(f'本场{kind}超过{limit}个，请明确删减，不能静默截断。')
    rewritten = re.sub(r'@' + kind + r'\s*(\d+)', lambda m: '@' + kind + str(mapping[int(m.group(1))]), prompt)
    return selected, mapping, rewritten


def scene_payload(scene, assets):
    prompt = re.sub(r'<Picture\s+(\d+)>', lambda m: '@图片' + m[1], str(scene.get('prompt') or ''))
    frozen = scene.get('reference_bindings') or {}
    pictures, image_map, rewritten = bind_references(prompt, assets, '图片', 10, frozen.get('图片'))
    audios, audio_map, rewritten = bind_references(rewritten, assets, '音频', 3, frozen.get('音频'))
    if not image_map:
        requested = scene.get('asset_ids') or []
        text = ' '.join(str(scene.get(key) or '') for key in ('who', 'place', 'remember', 'prompt'))
        pictures = [a for a in assets if a.get('kind') != '音频' and a.get('file') and
                    (a.get('id') in requested or (a.get('name') and a['name'] in text))]
        if len(pictures) > 10:
            raise RuntimeError('本场图片超过10张，请明确绑定。')
    return {'prompt': rewritten, 'assets': [a['file'] for a in pictures],
            'audios': [a['file'] for a in audios], 'asset_ids': [a['id'] for a in pictures + audios],
            'image_map': image_map, 'audio_map': audio_map}


def default_intelligence():
    return {'memory': [], 'pending_plan': None, 'revisions': [], 'feedback': [], 'reviews': [],
            'budget': {'limit': None, 'image_price': None, 'video_prices': {}, 'currency': 'CNY'},
            'creation': {}, 'ledger': [], 'source_videos': [], 'director_drafts': [], 'auto_review': False, 'speech_model': '', 'style_version': 1}


def project_snapshot(scenes, assets, state):
    return digest({'scenes': scenes, 'assets': assets, 'memory': state.get('memory'), 'style': state.get('style_version')})


def validate_plan(plan, scenes, assets):
    if not isinstance(plan, dict) or not isinstance(plan.get('changes'), list):
        raise RuntimeError('修改计划格式不正确。')
    if len(plan['changes']) > 30:
        raise RuntimeError('一次最多修改30项。')
    targets = {row['id']: row for row in scenes + assets}
    scene_ids = {row['id'] for row in scenes}
    allowed_scene = {'seconds', 'place', 'who', 'remember', 'prompt', 'asset_ids'}
    allowed_asset = {'picture', 'reference_ids'}
    changes = []
    for item in plan['changes']:
        if not isinstance(item, dict) or item.get('target_id') not in targets:
            raise RuntimeError('修改目标不存在，请按当前项目重新生成计划。')
        row = targets[item['target_id']]
        field = item.get('field')
        if field not in (allowed_scene if row['id'] in scene_ids else allowed_asset):
            raise RuntimeError('不支持这个修改字段；删除或生成必须使用对应按钮。')
        value = item.get('value')
        if field == 'seconds':
            if isinstance(value, bool) or not isinstance(value, int) or not 4 <= value <= 30:
                raise RuntimeError('场景时长只能是4～30秒的整数。')
        elif field in {'asset_ids', 'reference_ids'}:
            if not isinstance(value, list) or not all(isinstance(v, str) and v in {a['id'] for a in assets} for v in value):
                raise RuntimeError('素材绑定含有不存在的资产ID。')
        elif not isinstance(value, str) or len(value) > 16000:
            raise RuntimeError('修改内容必须是有效文本。')
        changes.append({'target_id': row['id'], 'field': field, 'before': copy.deepcopy(row.get(field)), 'value': value})
    if len({(c['target_id'], c['field']) for c in changes}) != len(changes):
        raise RuntimeError('同一字段不能在一次计划中修改两次。')
    return {'id': uuid.uuid4().hex, 'summary': str(plan.get('summary') or '局部修改')[:200], 'changes': changes}


def apply_plan(plan, scenes, assets, state):
    if plan.get('base') != project_snapshot(scenes, assets, state):
        raise RuntimeError('项目已变化，这份计划已过期，请重新提出修改。')
    clean = validate_plan(plan, scenes, assets)
    revision = {'id': uuid.uuid4().hex, 'at': time.time(), 'label': clean['summary'],
                'scenes': copy.deepcopy(scenes), 'assets': copy.deepcopy(assets), 'memory': copy.deepcopy(state['memory'])}
    targets = {row['id']: row for row in scenes + assets}
    changed_assets = set()
    for item in clean['changes']:
        target = targets[item['target_id']]
        target[item['field']] = copy.deepcopy(item['value'])
        target['version'] = int(target.get('version') or 1) + 1
        target.pop('confirmation',None)
        if target in assets:
            target['needs_redraw'] = True
            changed_assets.add(target['id'])
        elif item['field'] != 'prompt':
            target['needs_rewrite'] = True
        else:
            target['needs_rewrite'] = False
            target.pop('reference_bindings', None)
    for scene in scenes:
        if changed_assets.intersection(scene.get('asset_ids') or []):
            scene['needs_rewrite'] = True
        if any(c['target_id'] == scene['id'] and c['field'] == 'prompt' for c in clean['changes']):
            scene['needs_rewrite'] = False
    state['revisions'] = (state['revisions'] + [revision])[-20:]
    state['pending_plan'] = None
    return clean


def job_fingerprint(scene, payload, seconds, ratio, resolution, engine, assets):
    return digest({'scene': scene['id'], 'prompt': payload['prompt'], 'seconds': seconds,
                   'ratio': ratio, 'resolution': resolution, 'engine': engine,
                   'reference_content': payload.get('reference_content'),
                   'assets': [(a['id'], a.get('version'), a.get('file')) for a in assets if a['id'] in payload['asset_ids']]})


def rate_for(state, kind, engine='', resolution=''):
    budget = state['budget']
    value = budget.get('image_price') if kind == 'image' else budget.get('video_prices', {}).get(engine + ':' + resolution)
    if value is None or value == '':
        return None
    rate = float(value)
    if rate < 0 or not rate < float('inf'):
        raise RuntimeError('费用单价必须是有限的非负数。')
    return rate


def budget_spent(state):
    return round(sum(float(row.get('amount') or 0) for row in state['ledger'] if row['status'] != 'released'), 6)


def estimate(state, kind, units, engine='', resolution=''):
    rate = rate_for(state, kind, engine, resolution)
    return None if rate is None else round(rate * units, 6)


def reserve(state, kind, units, label, engine='', resolution=''):
    amount = estimate(state, kind, units, engine, resolution)
    limit = state['budget'].get('limit')
    if limit is not None:
        if amount is None:
            raise RuntimeError('已启用预算上限，请先填写对应生成单价。')
        if budget_spent(state) + amount > float(limit) + 0.000001:
            raise RuntimeError('这次生成会超过项目预算，已停止提交。')
    row = {'id': uuid.uuid4().hex, 'at': time.time(), 'kind': kind, 'units': units, 'label': label,
           'amount': amount, 'status': 'reserved', 'engine': engine, 'resolution': resolution}
    state['ledger'].append(row)
    return row
