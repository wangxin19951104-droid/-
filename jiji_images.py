"""Submit approved image text without the legacy client's creative prefixes."""

def generate_approved(client, prompt, dest, *, model, aspect, resolution, refs=None, max_refs=8, **kwargs):
    refs=list(refs or [])
    if any(not p.is_file() for p in refs): raise RuntimeError('已确认的图片参考文件缺失，请重新检查。')
    if len(refs)>max_refs: raise RuntimeError('图片参考数量超过已确认上限。')
    if model == 'nb21':
        # This client path already places the input text directly in GeminiNanoBanana2.prompt.
        return client.generate_image(prompt,dest,model=model,aspect=aspect,resolution=resolution,refs=refs,max_refs=max_refs,**kwargs)
    if model not in {'gpt','seedream'} or (aspect,resolution)!=('21:9','1K'):
        raise RuntimeError('已确认图片规格不支持。')
    if not client.local_ready(): raise RuntimeError('出图的ComfyUI未启动，请先打开本机8189。')
    if model == 'gpt':
        inputs={'prompt':prompt,'model':'gpt-image-2.5-sunburst','model.size':'Custom',
                'model.custom_width':1568,'model.custom_height':672,'model.background':'opaque',
                'model.quality':'high','n':1,'seed':42}
        class_type='OpenAIGPTImageNodeV2'
    else:
        inputs={'prompt':prompt,'model.model':'seedream 5.0 pro',
                'model.size_preset':'(1K) 1568x672 (21:9)','model.width':1568,'model.height':672,
                'model.seed':42,'model.watermark':False,'model.thinking':False,
                'model.prompt_optimization':'standard'}
        # Seedream's node has no "off" mode for reference images. "standard" passes no fast
        # optimization option. Text-only optional thinking is explicitly disabled above.
        class_type='ByteDanceSeedreamNodeV3'
    graph={'1':{'class_type':class_type,'inputs':inputs},
           '2':{'class_type':'SaveImage','inputs':{'filename_prefix':dest.stem[:40],'images':['1',0]}}}
    for n,path in enumerate(refs,1):
        node=str(10+n)
        graph[node]={'class_type':'LoadImage','inputs':{'image':client._local_upload(path)}}
        inputs['model.images.image_'+str(n)]=[node,0]
    pid=client._local_queue(graph)
    history=client._local_wait(pid,timeout=900 if model=='seedream' else 600)
    if (history.get('status') or {}).get('status_str')=='error':
        raise RuntimeError('图片生成失败，请查看ComfyUI任务记录。')
    return client._copy_local_output(history,dest)
