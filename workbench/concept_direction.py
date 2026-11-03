"""Resolve internal design direction without changing platform requirements or seller facts."""
import copy
import json
import task_store as store


def title_form(title):
    text=str(title).casefold()
    if 'powder' in text or '粉' in text:return 'Powder'
    if 'gumm' in text or '软糖' in text:return 'Gummy'
    if '口服液' in text or 'oral liquid' in text:return 'Oral Liquid'
    return ''


def conflict(product):
    design=(product.get('recruitment') or {}).get('conceptDesign') or {}
    selection=design.get('directionSelection') or {}
    if selection.get('sourceFingerprint')==design.get('sourceFingerprint') and selection.get('choice') in ('title','platform'):
        return ''
    form=str(design.get('form') or '')
    title=title_form(product.get('title'))
    if title and form and title.casefold()!=form.casefold():
        return '主题标题指向'+title+'，主题剂型属性为'+form+'；请确认内部概念方向，原征品要求保持不变'
    return ''


def resolve(product_id,revision,choice):
    if choice not in ('title','platform'):raise ValueError('请选择标题方向或平台属性方向')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT data FROM products WHERE id=?',(product_id,)).fetchone()
        if not row:raise ValueError('产品不存在')
        p=json.loads(row['data'])
        if p['revision']!=revision or p['facts'].get('mode')!='concept' or not p.get('recruitment'):
            raise ValueError('版本已变化或不是概念产品')
        if c.execute("SELECT id FROM jobs WHERE scope=? AND status IN ('RUNNING','QUEUED')",('product:'+p['id'],)).fetchone():
            raise ValueError('正在执行的任务结束后再改方向')
        design=p['recruitment'].get('conceptDesign') or {}
        form=title_form(p['title']) if choice=='title' else next((r['values'][0] for r in p['recruitment']['snapshot'].get('requirements',[]) if str(r.get('name')).casefold()=='dosage form' and r.get('values')), '')
        if not form:raise ValueError('所选方向尚无明确剂型')
        selection={'choice':choice,'form':form,'sourceFingerprint':design.get('sourceFingerprint'),'confirmedAt':store.now()}
        design=copy.deepcopy(design);design.update(form=form,directionSelection=selection)
        design['brief']=str(design.get('brief',''))+'\n用户已确认内部概念按'+('标题' if choice=='title' else '平台属性')+'方向 '+form+' 制作；原平台属性快照不变，差异仍待征品匹配处理。'
        p['recruitment']['conceptDesign']=design
        store.archive_draft(p, 'concept_direction_changed')
        p.update(revision=revision+1,stage='FACTS',approvedPackaging=None,approvedVisual=None,draft=None)
        p['facts']['design']=design['brief']
        text='内部概念包装设计稿（待确认）\n方向：'+form+'，不等于我方真实产品事实。\n'
        if form=='Powder':
            text+='包装：独立铝膜条包与配套纸盒。配色：深藏蓝、暖白及少量亮绿，简洁运动营养风格。\n正面只印 LIFEWORTH / PROTEIN POWDER / SINGLE-SERVE SACHET。\n'
        else:
            text+='请补充包装形态、产品色和准确正面印字。\n'
        text+='目标买家：运动营养OEM/私标品牌采购。文案来源：品类与剂型为用户确认的概念方向；品牌沿用Skill默认。\n不印22g、零糖、含量、口味、功效、证书或任何未经核实的数字。配方、规格、价格、MOQ待核。\n原主题要求Gummy与当前设计方向的差异仍保留，不能声明已满足征品。'
        import packaging_design
        p['designReview']={'revision':p['revision'],'status':'PENDING','text':text,'fingerprint':packaging_design.digest(text)}
        if p.get('selectionFlow'):p['selectionFlow'].update(revision=p['revision'],status='NEEDS_ATTENTION',message='概念方向已确认，待确认具体包装设计稿后生图')
        p['events'].append({'time':store.now(),'message':'用户确认内部概念方向：'+form+'；未修改原主题要求或我方产品事实'})
        c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(p,ensure_ascii=False),p['id']))
    return p
