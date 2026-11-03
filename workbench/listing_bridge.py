"""Local preparation through the authenticated publishflow bridge; never publishes."""
import json
from pathlib import Path
import shutil

import bridge_catalog
import task_store
import weekly_update


def read_result(text):
    try:
        value=json.loads(text)
    except (TypeError,ValueError):
        raise ValueError('桥接未返回可核验JSON') from None
    if not isinstance(value,dict) or value.get('success') is not True:
        raise ValueError('桥接阶段未成功，未继续提交')
    return value


def prepare(product,root,runner=None):
    """Reuse approved images and original Skill manifest, then obey native dependencies."""
    import listing_adapter
    import single_approval_flow
    single_approval_flow.require_hero(product)
    if single_approval_flow.visual_gaps(product):
        raise ValueError('当前套图质检尚未通过，不准备平台素材')
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    delivery=listing_adapter.export_images(product,root)
    material=root/'material';material.mkdir()
    for row in delivery:
        shutil.copyfile(root/row['file'],material/(row['slot']+Path(row['file']).suffix))
    proposal=(product.get('attributePlan') or {}).get('manifest')
    if not isinstance(proposal,dict):raise ValueError('缺少原Skill属性方案')
    (material/'product-brief.txt').write_text(json.dumps(proposal,ensure_ascii=False,indent=2),encoding='utf-8')
    bridge=bridge_catalog.current_bridge()
    key=(product.get('facts') or {}).get('store')
    expected=weekly_update.STORES.get(key,{}).get('expected_id')
    if not expected:raise ValueError('草稿目标店铺未绑定')
    weekly_update.require_identity(bridge,root/'identity-private.json',expected)
    run=runner or weekly_update.run
    def call(stage,*extra):
        command=[bridge/'workctl.cmd','publishflow',stage,'--work_dir',material,*extra,'--format','json']
        return read_result(run(command,cwd=task_store.ROOT,timeout=120))
    extraction=call('material-extract')
    if extraction.get('imageCount')!=len(delivery):raise ValueError('桥接提取图片数量与当前套图不符')
    result_dir=material/'result'
    if not result_dir.is_dir():raise ValueError('桥接未留下本次素材提取文件')
    # Exact native CLI error/help contract, not a guessed product material JSON.
    (result_dir/'decoration_plan.json').write_text('{"decorationPlan":"none"}',encoding='utf-8')
    collection=call('material-collect')
    # success=true can mean pending_dependency, not that upload happened.
    ready=collection.get('ready') is True and collection.get('status')!='pending_dependency'
    if ready:
        # Keep returned URLs/cache identifiers private; they are upstream inputs only.
        (root/'collection-private.json').write_text(json.dumps(collection,ensure_ascii=False),encoding='utf-8')
    weekly_update.require_identity(bridge,root/'identity-after-private.json',expected)
    result={'transport':'workctl-publishflow','status':'MATERIAL_READY' if ready else 'PENDING_DEPENDENCY',
            'revision':product['revision'],'images':len(delivery),'materialExtracted':True,
            'materialUploaded':ready,'draftSaved':False,'published':False,
            'missing':collection.get('missing',[]),'checkedAt':task_store.now(),
            'message':'本地素材已通过原生桥接整理；等待平台解析与草稿契约核验' if ready else
                      '桥接已提取当前套图；原生流水线仍等待本地图片转CDN链接，未保存草稿',
            'next':'原生read/CDN工具上传图片并保持有序映射；不得将本地路径或虚构URL写入image_list'}
    (root/'preparation-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def draft_command(product_json):
    """Any future native submission must select draft explicitly; validation is separate."""
    return [bridge_catalog.current_bridge()/'workctl.cmd','publishflow','publish-from-json',
            '--input',str(Path(product_json).resolve()),'--publish_type','draft','--format','json']


def run(job,product,root,skills):
    result=prepare(product,Path(root)/'publishflow')
    if not result['materialUploaded']:
        raise ValueError(result['message']+'；需要原生read/CDN能力，未回退浏览器登录')
    raise ValueError('桥接素材已整理；尚未取得原生解析商品JSON与保存回读契约，不创建未经核验的草稿')
