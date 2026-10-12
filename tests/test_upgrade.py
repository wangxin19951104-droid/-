import copy
import json
import pathlib
import sys
import tempfile
import unittest
import threading
import io
import types
import shutil
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import jiji_core as core
import server as h


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=str(pathlib.Path(__file__).resolve().parents[1]))
        self.root = pathlib.Path(self.temp.name)
        self.previous_root, self.previous_cache = h.PROJECTS_DIR, h.CACHE_ROOT
        h.PROJECTS_DIR, h.CACHE_ROOT = self.root / 'projects', self.root
        h.PROJECTS_DIR.mkdir()
        core.atomic_write(h.PROJECTS_DIR / 'index.json', json.dumps([{'id': 'test', 'name': 'test'}]))
        self.work = h.Work()
        self.work.current_id['id'] = 'test'
        self.work.chat['director_id'] = 'product-ad'
        self.work.loaded = True
        h.WORKS['test'] = self.work
        self.token = h.ACTIVE.set(self.work)

    def tearDown(self):
        h.ACTIVE.reset(self.token)
        h.PROJECTS_DIR, h.CACHE_ROOT = self.previous_root, self.previous_cache
        h.WORKS.pop('test', None)
        h.HOLD.pop('test', None)
        self.temp.cleanup()

    def assets(self):
        self.work.assets = [{'id': 'asset_' + str(i), 'kind': '场景', 'name': '地点' + str(i), 'file': str(i) + '.png', 'version': 1} for i in range(1, 4)]
        for asset in self.work.assets:
            (h.lib() / asset['file']).write_bytes(b'fixture')

    def scenes(self, count=1):
        self.work.scenes = [{'id': 'scene_' + str(i), 'place': '场' + str(i), 'who': '', 'seconds': 8,
                             'prompt': '0-4秒 环境与镜头。4-8秒 动作与声音。', 'version': 1} for i in range(count)]
        for scene in self.work.scenes:
            self.approve('video',scene)

    def approve(self,kind,target,**args):
        preview=h.WORKFLOW.preview(kind,target['id'],args)
        h.WORKFLOW.confirm({'kind':kind,'target_id':target['id'],'fingerprint':preview['fingerprint'],**args})
        return preview

    def test_default_duration_follows_scene(self):
        for seconds in (4, 8, 15, 24, 25, 30):
            self.assertEqual(h.seedance_seconds(seconds, 'auto'), seconds)

    def test_image_remap_and_freeze(self):
        self.assets()
        scene = {'id': 'scene', 'prompt': '@图片3 0-8秒 场景'}
        payload = h.INTELLIGENCE.payload(scene)
        self.assertEqual(payload['assets'], ['3.png'])
        self.assertIn('@图片1', payload['prompt'])
        self.work.assets.reverse()
        self.assertEqual(h.INTELLIGENCE.payload(scene)['assets'], ['3.png'])
        self.work.assets = [a for a in self.work.assets if a['id'] != 'asset_3']
        with self.assertRaisesRegex(RuntimeError, '删除或缺失'):
            h.INTELLIGENCE.payload(scene)

    def test_audio_only_selects_requested(self):
        self.work.assets = [{'id': 'a', 'kind': '音频', 'file': '1.wav'}, {'id': 'b', 'kind': '音频', 'file': '2.wav'}]
        for a in self.work.assets:
            (h.lib() / a['file']).write_bytes(b'fixture')
        payload = h.INTELLIGENCE.payload({'prompt': '@音频2 0-8秒 对白'})
        self.assertEqual(payload['audios'], ['2.wav'])
        self.assertIn('@音频1', payload['prompt'])

    def test_out_of_range_references_blocked(self):
        self.assets()
        with self.assertRaises(RuntimeError):
            h.INTELLIGENCE.payload({'prompt': '@图片4'})

    def test_missing_file_blocked(self):
        self.assets()
        (h.lib() / '3.png').unlink()
        with self.assertRaisesRegex(RuntimeError, '文件缺失'):
            h.INTELLIGENCE.payload({'prompt': '@图片3'})

    def test_time_gap_blocks_submission(self):
        self.scenes()
        self.work.scenes[0]['prompt'] = '0-3秒 镜头。5-8秒 镜头。'
        result = h.INTELLIGENCE.preflight('16:9', '720p', 'seedance', 'auto')
        self.assertFalse(result['ok'])
        self.assertIn('中间断了', str(result['errors']))

    def test_uniform_override_duration_checks_timeline(self):
        self.scenes()
        self.assertFalse(h.INTELLIGENCE.preflight('16:9', '720p', 'seedance', '23')['ok'])

    def test_skill_is_shared_across_every_stage(self):
        for director in h.DIRECTORS:
            self.work.chat['director_id'] = director[0]
            for kind in ('think', 'write', 'draw', 'video', 'review', 'style'):
                self.work.task['kind'] = kind
                messages = h.INTELLIGENCE.prepare([{'role': 'user', 'content': '当前任务'}])
                self.assertIn(director[3].read_text(encoding='utf-8'), messages[0]['content'])
                self.assertIn('当前阶段：' + kind, messages[0]['content'])

    def test_image_generation_receives_skill(self):
        class Banana:
            def generate_image(self, prompt, dest, **kwargs):
                self.prompt = prompt
                return 'ok'
        fake = Banana()
        h.generate_sheet(fake, '画产品', self.root / 'test.png')
        self.assertIn(h.DIRECTORS[0][3].read_text(encoding='utf-8'), fake.prompt)
        self.assertEqual(self.work.intelligence['ledger'][0]['status'], 'accepted')

    def test_long_history_not_truncated_on_reply_or_save(self):
        history = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': '消息' + str(i)} for i in range(100)]
        self.work.chat['messages'] = history
        h.update_chat({'messages': history[-20:]})
        self.assertEqual(len(self.work.chat['messages']), 100)
        with patch.object(h, 'stream_reply', return_value='回答'), patch.object(h, 'spawn', side_effect=lambda f: f()):
            h.begin_reply('product-ad', history[-20:] + [{'role': 'user', 'content': '新要求'}])
        self.assertEqual(len(self.work.chat['messages']), 102)
        self.assertEqual(self.work.chat['messages'][0]['content'], '消息0')

    def test_grounded_memory_and_pending_plan(self):
        self.scenes()
        raw = '建议缩短。<<<MEMORY>>>[{"fact":"不要字幕","evidence":"不要字幕"}]<<<END>>><<<EDIT>>>{"summary":"改秒数","changes":[{"target_id":"scene_0","field":"seconds","value":6}]}<<<END>>>'
        text = h.INTELLIGENCE.accept_reply(raw, [{'role': 'user', 'content': '不要字幕，缩短到6秒'}])
        self.assertNotIn('<<<', text)
        self.assertEqual(self.work.scenes[0]['seconds'], 8)
        self.assertEqual(self.work.intelligence['memory'][0]['fact'], '不要字幕')
        plan = self.work.intelligence['pending_plan']
        h.INTELLIGENCE.handle('/api/plan/apply', {'id': plan['id']})
        self.assertEqual(self.work.scenes[0]['seconds'], 6)
        self.assertTrue(self.work.scenes[0]['needs_rewrite'])
        h.INTELLIGENCE.handle('/api/revisions/undo', {})
        self.assertEqual(self.work.scenes[0]['seconds'], 8)

    def test_ungrounded_memory_rejected(self):
        h.INTELLIGENCE.accept_reply('<<<MEMORY>>>[{"fact":"角色穿红衣","evidence":"穿红衣"}]<<<END>>>', [{'role': 'user', 'content': '你好'}])
        self.assertEqual(self.work.intelligence['memory'], [])

    def test_stale_plan_cannot_overwrite_new_edits(self):
        self.scenes()
        plan = core.validate_plan({'changes': [{'target_id': 'scene_0', 'field': 'seconds', 'value': 6}]}, self.work.scenes, [])
        plan['base'] = core.project_snapshot(self.work.scenes, [], self.work.intelligence)
        self.work.scenes[0]['place'] = '新地点'
        with self.assertRaisesRegex(RuntimeError, '过期'):
            core.apply_plan(plan, self.work.scenes, [], self.work.intelligence)

    def test_asset_change_only_invalidates_dependents(self):
        self.assets()
        self.scenes(2)
        self.work.scenes[0]['asset_ids'] = ['asset_1']
        self.work.scenes[1]['asset_ids'] = ['asset_2']
        h.INTELLIGENCE.handle('/api/scenes/edit', {'changes': [{'target_id': 'asset_1', 'field': 'picture', 'value': '雨夜背景'}]})
        self.assertTrue(self.work.scenes[0]['needs_rewrite'])
        self.assertFalse(self.work.scenes[1].get('needs_rewrite', False))

    def test_budget_unknown_and_over_limit_block(self):
        state = self.work.intelligence
        state['budget']['limit'] = 5
        with self.assertRaisesRegex(RuntimeError, '单价'):
            core.reserve(state, 'image', 1, 'test')
        state['budget']['image_price'] = 3
        core.reserve(state, 'image', 1, 'test')
        with self.assertRaisesRegex(RuntimeError, '超过'):
            core.reserve(state, 'image', 1, 'test')

    def test_partial_submit_durable_and_unknown_not_retried(self):
        self.scenes(2)
        with patch.object(h, 'submit_comfy', side_effect=[{'prompt_id': 'accepted-1'}, TimeoutError('fixture timeout')]), patch.object(h, 'spawn'):
            with self.assertRaises(RuntimeError):
                h.start_episode('16:9', '720p')
        saved = core.read_json(h.session_file(), {})
        self.assertEqual(saved['job']['jobs'][0]['prompt_id'], 'accepted-1')
        self.assertEqual(saved['job']['jobs'][1]['status'], 'unknown')
        with patch.object(h, 'submit_comfy') as submit:
            with self.assertRaisesRegex(RuntimeError, '未知'):
                h.start_episode('16:9', '720p')
            submit.assert_not_called()

    def test_retry_reuses_accepted_and_costs_only_new_scene(self):
        self.scenes(2)
        with patch.object(h, 'submit_comfy', side_effect=[{'prompt_id': 'accepted-1'}, TimeoutError()]), patch.object(h, 'spawn'):
            with self.assertRaises(RuntimeError):
                h.start_episode('16:9', '720p')
        unknown = self.work.job['jobs'][1]
        h.INTELLIGENCE.handle('/api/jobs/resolve', {'fingerprint': unknown['fingerprint'], 'confirmed_not_submitted': True})
        with patch.object(h, 'submit_comfy', return_value={'prompt_id': 'accepted-2'}) as submit, patch.object(h, 'spawn'):
            plan = h.INTELLIGENCE.preflight('16:9', '720p', 'seedance', 'auto')
            self.assertTrue(plan['scenes'][0]['reuse'])
            self.assertEqual(plan['scenes'][0]['estimate'], 0)
            h.start_episode('16:9', '720p')
            self.assertEqual(submit.call_count, 1)
            self.assertEqual(self.work.job['jobs'][0]['prompt_id'], 'accepted-1')

    def test_atomic_backup_recovers_corrupt_session(self):
        path = self.root / 'state.json'
        core.atomic_write(path, '{"version":1}')
        core.atomic_write(path, '{"version":2}')
        path.write_text('{broken', encoding='utf-8')
        self.assertEqual(core.read_json(path, {})['version'], 1)

    def test_legacy_sessions_gain_ids_without_regenerating_assets(self):
        core.atomic_write(h.session_file(), json.dumps({'scenes': [{'seconds': 8, 'prompt': '0-8秒 镜头'}], 'assets': [{'kind': '人物', 'name': '甲', 'file': 'existing.png'}]}))
        h.load_session()
        self.assertTrue(self.work.scenes[0]['id'].startswith('scene_'))
        self.assertTrue(self.work.assets[0]['id'].startswith('asset_'))
        self.assertFalse(h.asset_stale(self.work.assets[0]))

    def test_explicit_feedback_can_be_reused_and_deleted(self):
        h.INTELLIGENCE.handle('/api/feedback', {'reason': '喜欢简洁稳镜头', 'accepted': True, 'remember_preference': True})
        prefs = h.INTELLIGENCE.preferences()
        self.assertEqual(len(prefs), 1)
        self.assertIn('简洁稳镜头', h.INTELLIGENCE.context())
        h.INTELLIGENCE.handle('/api/preferences/delete', {'id': prefs[0]['id']})
        self.assertEqual(h.INTELLIGENCE.preferences(), [])

    def test_http_routes_json_validation_and_origin(self):
        service = h.ThreadingHTTPServer(('127.0.0.1', 0), h.Handler)
        old_port, h.PORT = h.PORT, service.server_port
        worker = threading.Thread(target=service.serve_forever, daemon=True)
        worker.start()
        base = 'http://127.0.0.1:' + str(service.server_port)
        headers = {'Content-Type': 'application/json', 'X-Desk-Project': 'test', 'X-Desk-Client': 'fixture'}
        try:
            with urlopen(Request(base + '/api/memory', data=b'{"fact":"fixed identity"}', headers=headers)) as response:
                self.assertEqual(json.loads(response.read())['intelligence']['memory'][0]['fact'], 'fixed identity')
            with urlopen(Request(base + '/api/intelligence', data=b'{}', headers=headers)) as response:
                self.assertEqual(len(json.loads(response.read())['skill']['stages']), 6)
            with urlopen(base + '/intelligence.js') as response:
                self.assertIn(b'openIntelligence', response.read())
            with self.assertRaises(HTTPError) as bad:
                urlopen(Request(base + '/api/memory', data=b'[]', headers=headers))
            self.assertEqual(bad.exception.code, 400)
            with self.assertRaises(HTTPError) as cross:
                urlopen(Request(base + '/api/memory', data=b'{}', headers={**headers, 'Origin': 'https://untrusted.test'}))
            self.assertEqual(cross.exception.code, 403)
            with self.assertRaises(HTTPError) as rebinding:
                urlopen(Request(base + '/', headers={'Host': 'untrusted.test'}))
            self.assertEqual(rebinding.exception.code, 409)
        finally:
            service.shutdown()
            service.server_close()
            worker.join(timeout=2)
            h.PORT = old_port

    def test_actual_model_request_contains_shared_skill_and_memory(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def close(self): pass
            def read(self): return b'{"choices":[{"message":{"content":"fixture"}}]}'
        self.work.intelligence['memory'] = [{'id': 'fact', 'fact': '产品不能变形'}]
        with patch.object(h, 'load_config', return_value={'base_url': 'http://fixture.test/v1', 'model': 'fake'}), patch.object(h, 'resolve_key', return_value=''), patch.object(h, 'urlopen', return_value=Response()) as request:
            answer = h.call_model([{'role': 'user', 'content': '写词'}])
        sent = json.loads(request.call_args.args[0].data)
        self.assertEqual(answer, 'fixture')
        self.assertIn('统一导演经验', sent['messages'][0]['content'])
        self.assertIn('产品不能变形', sent['messages'][0]['content'])

    def test_quality_review_uses_real_input_and_stores_evidence(self):
        self.assets()
        with patch.object(h, 'preview_jpeg', return_value=b'jpeg'), patch.object(h, 'call_model', return_value='证据：多出文字。建议只移除文字。') as model:
            review = h.INTELLIGENCE.review('image', 'asset_1')
        self.assertEqual(review['evidence'][0]['asset_id'], 'asset_1')
        self.assertIn('未检查音频', review['limitations'])
        self.assertEqual(self.work.intelligence['reviews'][-1]['id'], review['id'])
        self.assertIn('image_url', str(model.call_args))

    def test_failed_image_keeps_budget_reservation(self):
        class Banana:
            def generate_image(self, *args, **kwargs): raise TimeoutError('uncertain provider result')
        self.work.intelligence['budget'].update({'limit': 5, 'image_price': 3})
        with self.assertRaises(TimeoutError):
            h.generate_sheet(Banana(), '产品', self.root / 'fixture.png')
        self.assertEqual(self.work.intelligence['ledger'][0]['status'], 'unknown')
        self.assertEqual(core.budget_spent(self.work.intelligence), 3)

    def test_restart_marks_inflight_submission_unknown(self):
        core.atomic_write(h.session_file(), json.dumps({'job': {'phase': 'running', 'jobs': [{'status': 'submitting'}]}}))
        h.load_session()
        self.assertEqual(self.work.job['jobs'][0]['status'], 'unknown')
        self.assertEqual(self.work.job['phase'], 'error')

    def test_pause_resume_never_resubmits_accepted_video(self):
        self.work.job['jobs'] = [{'prompt_id': 'accepted', 'status': 'queued'}]
        h.task_begin('video', '测试')
        with patch.object(h, 'comfy_stop_own') as cancel, patch.object(h, 'submit_comfy') as submit:
            h.task_pause()
            h.task_resume()
            cancel.assert_not_called()
            submit.assert_not_called()
        self.assertEqual(self.work.job['jobs'][0]['prompt_id'], 'accepted')
        h.task_finish('video')

    def test_rewrite_only_changed_scene(self):
        self.assets()
        self.scenes(2)
        first_prompt = self.work.scenes[0]['prompt']
        self.work.scenes[1]['needs_rewrite'] = True
        self.work.chat['messages'] = [{'role': 'user', 'content': '只更新第二场，不要改第一场。'}]
        raw = '<<<SEEDANCE>>>\n场次：1\n时长：8秒\n提示词：0-4秒 新动作。4-8秒 停稳。\n<<<END>>>'
        with patch.object(h, 'call_model', return_value=raw), patch.object(h, 'with_ref_images', side_effect=lambda messages: messages), patch.object(h, 'scenes_from_talk') as split:
            h.write_prompts('product-ad', self.work.chat['messages'], 0, '16:9')
            split.assert_not_called()
        self.assertEqual(self.work.scenes[0]['prompt'], first_prompt)
        self.assertIn('新动作', self.work.scenes[1]['prompt'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
