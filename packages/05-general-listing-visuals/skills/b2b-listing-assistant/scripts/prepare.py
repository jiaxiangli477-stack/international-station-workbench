"""Prepare a local, evidence-traced B2B product listing review; never contacts a platform."""
import argparse, csv, json, math
from pathlib import Path

ALLOWED = {'confirmed', 'inferred', 'missing', 'blocked'}
def source_ok(value):
    return isinstance(value,str) and bool(value.strip()) and value.strip().lower() not in {'none','null','unknown','n/a','待确认'}

def nonfinite(value):
    if isinstance(value,float): return not math.isfinite(value)
    if isinstance(value,dict): return any(nonfinite(v) for v in value.values())
    if isinstance(value,list): return any(nonfinite(v) for v in value)
    return False

def safe_json(value):
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,dict):return {k:safe_json(v) for k,v in value.items()}
    if isinstance(value,list):return [safe_json(v) for v in value]
    return value

def csv_safe(value):
    text = json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else str(value)
    return "'" + text if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r','\n')) else text

def verified(group, warnings, label, product_id=None):
    if not isinstance(group, dict):
        raise ValueError(f'{label} must be an object')
    result = {}
    for key, item in group.items():
        if not isinstance(item, dict):
            warnings.append(f'{label}.{key}: expected evidence object'); continue
        status=item.get('status','missing')
        if status not in ALLOWED:
            warnings.append(f'{label}.{key}: invalid status'); continue
        value=item.get('value')
        if isinstance(value,str) and not value.strip():warnings.append(f'{label}.{key}: empty text; excluded');continue
        if nonfinite(value):warnings.append(f'{label}.{key}: non-finite value; excluded');continue
        if item.get('conflict'):
            warnings.append(f'{label}.{key}: unresolved conflict; excluded'); continue
        if product_id is not None and item.get('product_id') != product_id:
            warnings.append(f'{label}.{key}: missing or conflicting SKU binding; excluded'); continue
        if status=='confirmed' and value not in (None,'',[],{}) and source_ok(item.get('source')):
            result[key]=value
        elif value not in (None,'',[],{}):
            warnings.append(f'{label}.{key}: not confirmed with source; excluded')
    return result

def prepare(data):
    if not isinstance(data,dict): raise ValueError('input must be a JSON object')
    warnings=[]
    product_id=data.get('product_id')
    company=verified(data.get('company',{}),warnings,'company')
    product=verified(data.get('product',{}),warnings,'product',product_id)
    pricing=verified(data.get('pricing',{}),warnings,'pricing',product_id)
    platform=data.get('platform',{})
    if not isinstance(platform,dict): raise ValueError('platform must be an object')
    platform={**platform, 'name':'Alibaba.com'}
    platform.pop('target_market', None)
    missing=[]
    if not source_ok(product_id): missing.append('产品标识及逐项SKU绑定')
    if not product.get('name'): missing.append('产品名称及来源')
    if not platform.get('category'): missing.append('平台实际类目（待人工选择）')
    if not company.get('name'): missing.append('公司名称及来源')
    if data.get('company_profile_confirmed') is not True: missing.append('公司资料已确认标记')
    return {'status':'needs_input' if missing else 'ready_for_review', 'missing':missing,
            'warnings':warnings,'confirmed_company':company,'confirmed_product':product,
            'pricing':pricing,'platform':platform,'publishable':False,
            'review_scope':'基础复核；未检查来源真实性、页面结构或全部必填字段，请继续运行build_plan.py',
            'source_records':safe_json({label:group for label,group in data.items() if label in ('company','product','pricing')})}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    args=p.parse_args(); out=args.output.resolve()
    if out.drive.upper() not in ('D:','E:'): raise ValueError('output must be on D: or E:')
    data=json.loads(args.input.read_text(encoding='utf-8-sig')); result=prepare(data)
    out.mkdir(parents=True,exist_ok=True)
    (out/'review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    with (out/'review.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['section','field','value','source','status'])
        for section in ('company','product','pricing'):
            for key,item in data.get(section,{}).items():
                if isinstance(item,dict):w.writerow([csv_safe(v) for v in [section,key,item.get('value',''),item.get('source',''),item.get('status','missing')]])
    print(f"{result['status']}: {out}")
if __name__=='__main__':main()
