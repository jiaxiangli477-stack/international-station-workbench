"""Validate a declared evidence-backed Alibaba field plan locally. No network or browser actions."""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

TEXT_CONTROLS={'text','textarea','number'}
OPTION_CONTROLS={'select','multiselect','autocomplete','tags'}
def source_ok(value):
    return isinstance(value,str) and bool(value.strip()) and value.strip().lower() not in {'none','null','unknown','n/a','待确认'}
def fact_value(item, product_id=None):
    if not isinstance(item,dict) or item.get('status')!='confirmed' or not source_ok(item.get('source')):
        return None,'未确认或缺少有效来源标记'
    if item.get('conflict'):
        return None,'存在未解决的资料冲突'
    if product_id is not None and item.get('product_id')!=product_id:
        return None,'产品标识缺失或与当前SKU不一致'
    value=item.get('value')
    if isinstance(value,float) and not math.isfinite(value):return None,'数值不是有限值'
    if value is None or (isinstance(value,str) and not value.strip()) or value==[] or value=={}:
        return None,'确认值为空'
    return value,None

def build_plan(data):
    errors=[];warnings=[];fields={};audit=[];skipped=[]
    result={'status':'blocked','product_id':None,'fields':fields,'field_audit':audit,'skipped':skipped,
            'errors':errors,'warnings':warnings,'publishable':False,'uploaded':False,
            'evidence_scope':'仅检查调用者声明的来源与匹配，不证明原始材料真实或已读取','platform':'Alibaba.com'}
    if not isinstance(data,dict):
        errors.append('输入必须为对象');return result
    pid=data.get('product_id');result['product_id']=pid
    if not source_ok(pid):errors.append('缺少当前产品标识')
    if data.get('company_profile_confirmed') is not True:errors.append('公司资料尚未确认')
    company=data.get('company',{})
    product=data.get('product',{})
    if not isinstance(company,dict) or fact_value(company.get('name'))[1] or not source_ok(fact_value(company.get('name'))[0]):errors.append('公司名称缺少有效确认来源')
    if not isinstance(product,dict) or fact_value(product.get('name'),pid)[1] or not source_ok(fact_value(product.get('name'),pid)[0]):errors.append('产品名称缺少同SKU确认来源')
    schema=data.get('category_schema')
    if not isinstance(schema,dict):errors.append('缺少真实类目页面配置');return result
    url=schema.get('publishing_url')
    try:parsed=urlparse(url) if isinstance(url,str) else None
    except ValueError:parsed=None
    if not parsed or parsed.scheme!='https' or parsed.hostname!='post.alibaba.com' or not parsed.path.startswith('/product/') or parsed.username or parsed.password:
        errors.append('类目发布URL未确认或不是国际站发布页')
    else:
        query=parse_qs(parsed.query)
        if any(any(word in k.lower() for word in ('token','cookie','secret','session','auth')) for k in query):errors.append('发布URL含会话或凭据类参数，需移除')
        if schema.get('category_id') and query.get('catId') and query['catId']!=[str(schema['category_id'])]:errors.append('URL类目与配置类目不一致')
    if not (source_ok(schema.get('category_id')) or source_ok(schema.get('category_path'))):errors.append('类目标识或路径尚未确认')
    if not source_ok(schema.get('source')):errors.append('页面配置缺少来源')
    try:datetime.fromisoformat(schema.get('observed_at',''))
    except (TypeError,ValueError):errors.append('页面配置缺少有效核查日期')
    if schema.get('coverage')!='reviewed_for_product':errors.append('页面字段尚未针对当前产品复核')
    definitions=schema.get('fields')
    if not isinstance(definitions,list) or not definitions:errors.append('缺少页面字段定义');return result
    attributes=data.get('attributes',{})
    if not isinstance(attributes,dict):errors.append('属性数据必须为对象');return result
    seen=set()
    for definition in definitions:
        if not isinstance(definition,dict):errors.append('字段定义必须为对象');continue
        key=definition.get('key');label=definition.get('label')
        if not source_ok(key) or key in seen:errors.append(f'字段key缺失或重复: {key}');continue
        seen.add(key)
        if not source_ok(label):errors.append(f'{key}: 字段标签未确认')
        required=definition.get('required')
        if not isinstance(required,bool):errors.append(f'{key}: 必填状态未确认');continue
        if (definition.get('conditions') or definition.get('depends_on')) and ('active' not in definition or not source_ok(definition.get('condition_evidence'))):
            errors.append(f'{key}: 条件或联动尚未核实');continue
        active=definition.get('active',True)
        if not isinstance(active,bool):errors.append(f'{key}: 条件字段是否启用尚未确认');continue
        if active is False:
            if not source_ok(definition.get('inactive_reason')):errors.append(f'{key}: 不适用缺少解释')
            elif key in attributes:errors.append(f'{key}: 不适用字段却有待填写值')
            else:skipped.append({'key':key,'reason':definition['inactive_reason']})
            continue
        item=attributes.get(key)
        if item is None:
            if required:errors.append(f'{key}: 缺少必填属性')
            else:skipped.append({'key':key,'reason':'选填未提供'})
            continue
        value,error=fact_value(item,pid)
        if error:
            if required:errors.append(f'{key}: {error}')
            else:warnings.append(f'{key}: {error}，未填写');skipped.append({'key':key,'reason':error})
            continue
        control=definition.get('control_type')
        issue=None
        if control in OPTION_CONTROLS:
            options=definition.get('observed_options');allow_custom=definition.get('allows_custom_value')
            if not isinstance(options,list) or not source_ok(definition.get('options_evidence')) or not isinstance(allow_custom,bool):
                issue='选项或自定义机制缺少页面证据'
            else:
                values=value if isinstance(value,list) else [value]
                if control in {'select','autocomplete'} and isinstance(value,list):issue='单选字段不能填写列表'
                elif not all(isinstance(v,str) and bool(v.strip()) for v in values):issue='选项值类型错误'
                elif len(values)!=len(set(values)):issue='多选值重复'
                elif any(v not in options for v in values):
                    if not allow_custom or not source_ok(definition.get('custom_value_evidence')):issue='未核实的选项，禁止近似匹配'
        elif control in TEXT_CONTROLS:
            if not isinstance(value,(str,int,float)) or isinstance(value,bool):issue='文本或数字字段值类型错误'
            if control=='number' and (not isinstance(value,(int,float)) or isinstance(value,bool)):issue='数字字段需要有限数值'
        else:issue='尚未支持或未确认的控件类型'
        limits=definition.get('limits',{})
        if not isinstance(limits,dict):issue='字段限制格式错误'
        elif set(limits)-{'min','max','max_length'}:issue='存在尚未实现的页面限制，需要补充适配'
        elif 'max_length' in limits:
            maximum=limits['max_length']
            if not isinstance(maximum,int) or isinstance(maximum,bool) or maximum<0:issue='页面字符限制格式错误'
            elif len(str(value))>maximum:issue='超出页面字符限制'
        if definition.get('unit_required') is True and not source_ok(definition.get('unit')):issue='字段单位尚未确认'
        if control=='number' and issue is None:
            for bound in ('min','max'):
                limit=limits.get(bound)
                if limit is not None:
                    if not isinstance(limit,(int,float)) or isinstance(limit,bool) or not math.isfinite(limit):issue='页面数值限制无效'
                    elif (bound=='min' and value<limit) or (bound=='max' and value>limit):issue='超出页面数值范围'
        if issue:errors.append(f'{key}: {issue}');continue
        fields[key]=value;audit.append({'key':key,'label':label,'value':value,'source':item['source'],'product_id':pid,'control_type':control,'unit':definition.get('unit')})
    for key in attributes:
        if key not in seen:errors.append(f'{key}: 属性没有对应的已核实页面字段')
    if not errors:result['status']='ready_for_local_review'
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    if out.drive.upper() not in ('D:','E:'):raise ValueError('output must be on D: or E:')
    result=build_plan(json.loads(args.input.read_text(encoding='utf-8-sig')));out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');print(result['status'],out)
    return 2 if result['errors'] else 0
if __name__=='__main__':raise SystemExit(main())
