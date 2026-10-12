import copy
from unittest.mock import patch

import test_upgrade as base
from test_upgrade import h
import jiji_creation as creation


class CreationTests(base.UpgradeTests):
    def setup_creation(self, **changes):
        data = {'genre': 'drama', 'source_mode': 'idea', 'brief': '雨夜重逢，30秒短剧，不要字幕。',
                'visual_style': 'cinema', 'engine': 'seedance', 'stage': 'discussion', 'ready': True}
        data.update(changes)
        return creation.update(h, data)

    def test_table_source_is_saved_and_keeps_uploaded_rows_for_director(self):
        from unittest.mock import patch
        with patch.object(h, 'call_model') as model:
            h.store_script('分镜.csv', '镜头,画面,时长\n1,雨夜街道,5秒'.encode('utf-8'))
            result = self.setup_creation(source_mode='table', brief='')
            self.assertEqual(result['intelligence']['creation']['source_mode'], 'table')
            self.assertIn('雨夜街道', h.SCRIPT['text'])
            self.assertIn('时长', result['script_preview'])
            self.work.script['text'] = ''
            h.load_session()
            self.assertIn('雨夜街道', h.SCRIPT['text'])
            self.assertEqual(self.work.intelligence['creation']['source_mode'], 'table')
            model.assert_not_called()

    def test_model_and_style_rules_follow_every_stage(self):
        for engine in creation.PROFILES:
            self.setup_creation(engine=engine, visual_style='animation')
            rules = (h.SKILLS / creation.PROFILES[engine][1]).read_text(encoding='utf-8')
            other = (h.SKILLS / creation.PROFILES['h3' if engine == 'seedance' else 'seedance'][1]).read_text(encoding='utf-8')
            for phase in ('think', 'write', 'draw', 'video', 'review', 'style', 'analyze'):
                self.work.task['kind'] = phase
                context = h.INTELLIGENCE.prepare([{'role': 'user', 'content': '当前任务'}])[0]['content']
                self.assertIn(rules, context)
                self.assertNotIn(other, context)
                self.assertIn(creation.STYLES['animation'], context)
                self.assertIn('雨夜重逢', context)
                self.assertIn('当前阶段：' + phase, context)

    def test_direction_change_invalidates_prompts_and_preserves_work(self):
        self.setup_creation()
        self.assets(); self.scenes()
        self.work.assets[0]['picture'] = '雨夜街道'
        self.approve('image', self.work.assets[0])
        self.work.intelligence['director_drafts'] = [{'id': 'old-draft'}]
        self.work.chat['messages'] = [{'role': 'user', 'content': '之前已聊好的内容'}]
        original_files = [a['file'] for a in self.work.assets]
        self.setup_creation(engine='h3', custom_style='柔和侧光', visual_style='custom')
        self.assertNotIn('confirmation', self.work.scenes[0])
        self.assertTrue(self.work.scenes[0]['needs_rewrite'])
        self.assertNotIn('confirmation', self.work.assets[0])
        self.assertEqual(self.work.intelligence['director_drafts'], [])
        self.assertEqual([a['file'] for a in self.work.assets], original_files)
        self.assertEqual(self.work.chat['messages'][0]['content'], '之前已聊好的内容')
        self.assertEqual(h.CHAT['resolution'], '720p')

    def test_navigation_keeps_valid_confirmations(self):
        self.setup_creation(); self.scenes()
        fingerprint = self.work.scenes[0]['confirmation']['fingerprint']
        creation.update(h, {'stage': 'assets'})
        self.assertEqual(self.work.scenes[0]['confirmation']['fingerprint'], fingerprint)
        self.assertTrue(h.WORKFLOW.preview('video', 'scene_0', {})['confirmed'])

    def test_creation_persists_and_return_to_input_resumes_setup(self):
        expected = self.setup_creation(engine='h3', visual_style='custom', custom_style='低饱和，固定机位。')['intelligence']['creation']
        self.work.intelligence['creation'] = {}; self.work.mode['video'] = 'seedance'
        h.load_session()
        self.assertEqual(self.work.intelligence['creation'], expected)
        self.assertEqual(self.work.mode['video'], 'h3')
        creation.update(h, {'stage': 'input', 'ready': False})
        h.load_session()
        self.assertFalse(self.work.intelligence['creation']['ready'])
        self.assertEqual(self.work.intelligence['creation']['stage'], 'input')

    def test_navigation_does_not_generate_and_plan_requires_explicit_action(self):
        with patch.object(h, 'call_model') as model, patch.object(h, 'submit_h3') as provider:
            self.setup_creation()
            model.assert_not_called(); provider.assert_not_called()
        scene = {'place': '雨夜街道', 'who': '女主', 'remember': '她握住旧信后停下', 'seconds': 8}
        with patch.object(h, 'scenes_from_talk', return_value=[scene]) as classify:
            result = creation.plan(h)
            self.assertIn('雨夜重逢', classify.call_args.args[1][0]['content'])
            self.assertEqual(result['intelligence']['creation']['stage'], 'assets')
            with self.assertRaisesRegex(RuntimeError, '已有分镜'):
                creation.plan(h)
            self.assertEqual(classify.call_count, 1)

    def test_h3_reference_preview_exact_submission_and_reuse(self):
        self.setup_creation(engine='h3'); self.assets(); self.scenes()
        scene = self.work.scenes[0]
        scene['prompt'] = '  <Picture 3>锁定地点。0-4秒 镜头推近。\n4-8秒 镜头停稳，雨声持续。  '
        scene.pop('reference_bindings', None)
        approved = self.approve('video', scene, video_model='h3')
        self.assertIn('<Picture 1>', approved['prompt'])
        self.assertEqual(approved['references'][0]['file'], '3.png')
        self.work.assets.reverse()
        self.assertTrue(h.WORKFLOW.preview('video', scene['id'], {'video_model': 'h3'})['confirmed'])
        with patch.object(h, 'call_model') as model, patch.object(h, 'submit_h3', return_value={'prompt_id': 'offline'}) as submit, patch.object(h, 'spawn'):
            h.start_episode('16:9', '720p', 'h3')
            self.assertEqual(submit.call_args.args[0], approved['prompt'])
            self.assertEqual(submit.call_args.args[4], ['3.png'])
            model.assert_not_called()
        h.task_finish('video'); self.work.job['phase'] = 'error'
        plan = h.INTELLIGENCE.preflight('16:9', '720p', 'h3', 'auto')
        self.assertTrue(plan['ok'], plan['errors'])
        self.assertTrue(plan['scenes'][0]['reuse'])
        self.assertEqual(plan['estimate'], 0)
        with patch.object(h, 'submit_h3') as submit, patch.object(h, 'spawn'):
            h.start_episode('16:9', '720p', 'h3')
            submit.assert_not_called()

    def test_h3_rejects_unsupported_reference_tags(self):
        self.setup_creation(engine='h3'); self.scenes()
        scene = self.work.scenes[0]
        for tag in ('@音频1', '@视频 2', '<Audio 1>', '<Video 1>', '<audio 2>'):
            scene['prompt'] = tag + ' 0-8秒 镜头停稳。'
            with self.subTest(tag=tag), self.assertRaisesRegex(RuntimeError, '不支持音频/视频参考标签'):
                h.WORKFLOW.preview('video', scene['id'], {'video_model': 'h3'})
        scene['prompt'] = '0-8秒 镜头停稳，雨声与脚步声同步。'
        self.assertEqual(h.WORKFLOW.preview('video', scene['id'], {'video_model': 'h3'})['prompt'], scene['prompt'])

    def test_invalid_setup_and_busy_task_preserve_direction(self):
        self.setup_creation()
        original = copy.deepcopy(self.work.intelligence['creation'])
        for changes in ({'engine': 'unknown'}, {'visual_style': 'custom', 'custom_style': ''}, {'ready': 'true'}):
            with self.assertRaises(RuntimeError): creation.update(h, changes)
            self.assertEqual(self.work.intelligence['creation'], original)
        self.work.task['state'] = 'running'
        with self.assertRaisesRegex(RuntimeError, '当前任务结束'):
            creation.update(h, {'engine': 'h3'})
        self.assertEqual(self.work.mode['video'], 'seedance')
        self.assertEqual(self.work.intelligence['creation'], original)


for name in dir(base.UpgradeTests):
    if name.startswith('test_') and name not in CreationTests.__dict__:
        setattr(CreationTests, name, None)
