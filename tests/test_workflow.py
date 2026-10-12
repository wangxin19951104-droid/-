import io
import json
import pathlib
import threading
import types
import subprocess
import tempfile
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import test_upgrade as _base
from test_upgrade import h,core
from jiji_workflow import VIDEO_LIMIT


class WorkflowTests(_base.UpgradeTests):
    # Only this class's new checks should run here; inherited regression checks run once in their own module.
    def image_asset(self):
        self.work.assets=[{'id':'asset_test','kind':'道具','name':'银色瓶','picture':'  银色瓶，白底四视图；比例21:9。\n不要文字。  ','version':1}]
        return self.work.assets[0]

    def prompt(self,text):
        h.INTELLIGENCE.handle('/api/scenes/edit',{'changes':[{'target_id':self.work.scenes[0]['id'],'field':'prompt','value':text}]})
        return self.work.scenes[0]

    def test_unconfirmed_image_does_not_call_model_or_provider(self):
        self.image_asset()
        with patch.object(h,'call_model') as model,patch.dict('sys.modules',{'banana_client':types.SimpleNamespace(generate_image=lambda *a,**k:self.fail('provider called'))}):
            plan=h.INTELLIGENCE.draw_plan('banana')
            self.assertFalse(plan['ok'])
            with self.assertRaisesRegex(RuntimeError,'尚未确认'):
                h.make_all_assets('product-ad','16:9','banana',plan['fingerprint'])
            model.assert_not_called()

    def test_confirmed_image_is_exact_and_plan_race_blocks(self):
        asset=self.image_asset();preview=self.approve('image',asset)
        plan=h.INTELLIGENCE.draw_plan('banana')
        sent=[]
        def generate(prompt,dest,**kw):
            sent.append((prompt,kw));dest.write_bytes(b'fake image')
        fake=types.SimpleNamespace(generate_image=generate)
        with patch.object(h,'call_model') as model,patch.dict('sys.modules',{'banana_client':fake}):
            with self.assertRaisesRegex(RuntimeError,'计划已变化'):
                h.make_all_assets('product-ad','16:9','banana','outdated')
            self.assertEqual(sent,[])
            result=h.make_all_assets('product-ad','16:9','banana',plan['fingerprint'])
            model.assert_not_called()
        self.assertEqual(result['drew'],1)
        self.assertEqual(sent[0][0],preview['prompt'])
        self.assertNotIn('approved',sent[0][1])
        self.assertEqual(asset['generated_prompt'],preview['prompt'])
        self.assertFalse(h.INTELLIGENCE.draw_plan()['ok'])

    def test_video_preview_remap_visible_and_submission_exact(self):
        self.assets();self.scenes()
        scene=self.prompt('  @图片3 0-4秒 比例16:9，，。\n4-8秒 镜头停稳。  ')
        approved=self.approve('video',scene)
        self.assertNotEqual(approved['source_prompt'],approved['prompt'])
        self.assertIn('@图片1',approved['prompt'])
        self.assertIn('16:9，，。',approved['prompt'])
        with patch.object(h,'call_model') as model,patch.object(h,'submit_comfy',return_value={'prompt_id':'fake'}) as submit,patch.object(h,'spawn'):
            h.start_episode('16:9','720p')
            self.assertEqual(submit.call_args.args[0],approved['prompt'])
            self.assertEqual(h.video_prompt(submit.call_args.args[0]),approved['prompt'])
            model.assert_not_called()

    def test_unconfirmed_video_never_writes_or_submits(self):
        self.scenes();self.work.scenes[0].pop('confirmation')
        with patch.object(h,'call_model') as model,patch.object(h,'submit_comfy') as submit:
            with self.assertRaisesRegex(RuntimeError,'尚未确认'): h.start_episode('16:9','720p')
            model.assert_not_called();submit.assert_not_called()

    def test_changed_context_reference_bytes_and_spec_invalidate(self):
        self.assets();self.scenes();scene=self.prompt('@图片1 0-8秒 镜头。')
        self.approve('video',scene)
        self.assertTrue(h.INTELLIGENCE.preflight('16:9','720p','seedance','auto')['ok'])
        self.assertFalse(h.INTELLIGENCE.preflight('9:16','720p','seedance','auto')['ok'])
        (h.lib()/'1.png').write_bytes(b'changed contents')
        self.assertFalse(h.INTELLIGENCE.preflight('16:9','720p','seedance','auto')['ok'])
        self.approve('video',scene)
        self.work.intelligence['memory'].append({'id':'new','fact':'不要字幕'})
        self.assertFalse(h.INTELLIGENCE.preflight('16:9','720p','seedance','auto')['ok'])

    def test_changed_reference_bytes_do_not_reuse_old_video(self):
        self.assets();self.scenes();scene=self.prompt('@图片1 0-8秒 镜头。')
        self.approve('video',scene)
        with patch.object(h,'submit_comfy',return_value={'prompt_id':'fake'}),patch.object(h,'spawn'):
            h.start_episode('16:9','720p')
        h.task_finish('video');self.work.job['phase']='error'
        (h.lib()/'1.png').write_bytes(b'changed');self.approve('video',scene)
        self.assertFalse(h.INTELLIGENCE.preflight('16:9','720p','seedance','auto')['scenes'][0]['reuse'])

    def test_confirmation_preview_race(self):
        asset=self.image_asset();preview=h.WORKFLOW.preview('image',asset['id'],{})
        asset['picture']+='新动作'
        with self.assertRaisesRegex(RuntimeError,'项目发生变化'):
            h.WORKFLOW.confirm({'kind':'image','target_id':asset['id'],'fingerprint':preview['fingerprint']})

    def test_director_chat_draft_adoption_has_no_second_model(self):
        self.scenes();prompt='0-8秒 直接使用导演写的原文，比例16:9。'
        raw='这份可以查看。<<<DRAFT>>>'+json.dumps([{'scene_id':'scene_0','prompt':prompt}],ensure_ascii=False)+'<<<END>>>'
        with patch.object(h,'call_model') as model:
            h.INTELLIGENCE.accept_reply(raw,[])
            draft=self.work.intelligence['director_drafts'][0]
            h.WORKFLOW.handle('/api/director-draft/adopt',{'id':draft['id']})
            model.assert_not_called()
        self.assertEqual(self.work.scenes[0]['prompt'],prompt)
        self.assertNotIn('confirmation',self.work.scenes[0])

    def clip_bytes(self):
        dest=self.root/'testclip.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=silver:s=320x180:r=24','-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t','2','-c:v','libx264','-c:a','aac','-y',str(dest)],check=True,capture_output=True,timeout=20)
        return dest.read_bytes()

    def test_video_upload_rejects_bad_data_extensions_and_size(self):
        for name,data,length in [('bad.mp4',b'invalid',7),('movie.exe',b'',1),('huge.mp4',b'',VIDEO_LIMIT+1)]:
            with self.assertRaises(RuntimeError): h.WORKFLOW.upload_video(name,io.BytesIO(data),length)
        self.assertEqual(h.WORKFLOW.videos(),[])
        folder=h.project_dir()/'source-videos'
        if folder.exists(): self.assertEqual(list(folder.iterdir()),[])

    def test_real_upload_analysis_persisted_and_opt_in(self):
        data=self.clip_bytes();row=h.WORKFLOW.upload_video('../../sample.mp4',io.BytesIO(data),len(data))
        self.assertNotIn('/',row['name']);self.assertGreater(row['seconds'],1)
        with patch.object(h,'call_model',return_value='抽样报告：展示银色产品，镜头停稳。') as model,patch.object(h,'spawn',side_effect=lambda fn:fn()):
            h.WORKFLOW.analyze_video({'id':row['id']})
        self.assertEqual(row['status'],'analyzed',row.get('error'))
        self.assertGreaterEqual(len(row['frames']),3)
        self.assertLessEqual(len(row['frames']),24)
        self.assertIn('image_url',str(model.call_args))
        self.assertFalse(row['use_for_creation'])
        self.assertNotIn(row['analysis'],h.INTELLIGENCE.context())
        h.WORKFLOW.handle('/api/source-video/use',{'id':row['id'],'enabled':True})
        self.assertIn(row['analysis'],h.INTELLIGENCE.context())
        h.load_session()
        self.assertEqual(h.WORKFLOW.videos()[0]['analysis'],row['analysis'])
        self.assertTrue(h.WORKFLOW.videos()[0]['use_for_creation'])

    def test_source_analysis_restart_recovers_and_failure_can_retry(self):
        data=self.clip_bytes();row=h.WORKFLOW.upload_video('sample.mp4',io.BytesIO(data),len(data))
        row['status']='analyzing';h.save_session();h.load_session()
        row=h.WORKFLOW.videos()[0];self.assertEqual(row['status'],'error')
        with patch.object(h,'call_model',side_effect=RuntimeError('model has no vision')),patch.object(h,'spawn',side_effect=lambda f:f()):
            h.WORKFLOW.analyze_video({'id':row['id']})
        self.assertEqual(row['status'],'error');self.assertIn('no vision',row['error'])
        self.assertEqual(h.TASK['state'],'idle')

    def test_optional_speech_extracts_real_audio_and_cleans_up(self):
        data=self.clip_bytes();row=h.WORKFLOW.upload_video('sample.mp4',io.BytesIO(data),len(data))
        self.work.intelligence['speech_model']='fixture'
        def transcript(job,folder):
            self.assertTrue(pathlib.Path(job['file']).is_file())
            return '测试对白'
        with patch.object(h.INTELLIGENCE,'transcribe',side_effect=transcript) as speech,patch.object(h,'call_model',return_value='报告'),patch.object(h,'spawn',side_effect=lambda f:f()):
            h.WORKFLOW.analyze_video({'id':row['id'],'transcribe':True})
        self.assertEqual(row['status'],'analyzed',row.get('error'))
        self.assertEqual(speech.call_count,1)
        self.assertEqual(row['transcripts'][0]['text'],'测试对白')
        self.assertEqual(list((h.project_dir()/'source-videos'/row['id']).glob('*.wav')),[])

    def test_provider_graphs_preserve_exact_prompt_text(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"prompt_id":"fixture"}'
        prompt='  0-8秒 比例16:9，，。\n无字幕；按原文。  '
        with patch.object(h,'comfy_status',return_value={'ok':True}),patch.object(h,'comfy_base',return_value='http://fixture.test'),patch.object(h,'h3_task_label',return_value='t2v'),patch.object(h,'urlopen',return_value=Response()) as request:
            h.submit_comfy(prompt,8,'16:9','720p','doubao-seedance-2-5',[])
            graph=json.loads(request.call_args.args[0].data)['prompt']
            self.assertEqual(graph['1']['inputs']['prompt'],prompt)
            h.submit_h3(prompt,8,'16:9','720p',[])
            graph=json.loads(request.call_args.args[0].data)['prompt']
            self.assertEqual(graph['6']['inputs']['global_prompt'],prompt)
            self.assertEqual(json.loads(graph['6']['inputs']['timeline_data'])['global']['prompt'],prompt)

    def test_gpt_and_seedream_client_graphs_do_not_add_creative_prefix(self):
        from jiji_images import generate_approved
        queued=[]
        client=types.SimpleNamespace(local_ready=lambda:True,_local_queue=lambda graph:queued.append(graph) or 'fake',
                                     _local_wait=lambda *a,**k:{},_copy_local_output=lambda hist,dest:dest)
        prompt='  画完整雨夜街道，不要白底。  '
        for model in ('gpt','seedream'):
            generate_approved(client,prompt,self.root/'out.png',model=model,aspect='21:9',resolution='1K')
            self.assertEqual(queued[-1]['1']['inputs']['prompt'],prompt)
        self.assertFalse(queued[-1]['1']['inputs']['model.thinking'])

    def test_video_limits_and_h3_adaptation_are_visible(self):
        self.scenes();scene=self.work.scenes[0]
        preview=h.WORKFLOW.preview('video',scene['id'],{'video_model':'h3'})
        self.assertEqual(preview['spec']['canvas'],h.h3_canvas('16:9','720p'))
        self.assertEqual(preview['spec']['actual_seconds'],h.h3_seconds(8)[1])
        data=self.clip_bytes()
        with patch.object(h.WORKFLOW,'videos',return_value=[{}]*10):
            with self.assertRaisesRegex(RuntimeError,'最多'): h.WORKFLOW.upload_video('sample.mp4',io.BytesIO(data),len(data))

    def test_binary_upload_http_and_frame_path_validation(self):
        service=h.ThreadingHTTPServer(('127.0.0.1',0),h.Handler)
        worker=threading.Thread(target=service.serve_forever,daemon=True);worker.start()
        headers={'X-Desk-Project':'test','X-Desk-Client':'fixture','Content-Type':'application/octet-stream'}
        base='http://127.0.0.1:'+str(service.server_port)
        try:
            with urlopen(Request(base+'/api/source-video/upload?name=sample.mp4',data=self.clip_bytes(),headers=headers)) as response:
                row=json.loads(response.read())
            self.assertEqual(row['status'],'uploaded')
            with self.assertRaises(HTTPError) as bad:
                urlopen(base+'/source-video-frames/'+row['id']+'/source.mp4?project=test')
            self.assertEqual(bad.exception.code,404)
        finally:
            service.shutdown();service.server_close();worker.join(2)


# Avoid duplicate execution of inherited checks while reusing fixture helpers.
for name in dir(_base.UpgradeTests):
    if name.startswith('test_') and name not in WorkflowTests.__dict__:
        setattr(WorkflowTests,name,None)
