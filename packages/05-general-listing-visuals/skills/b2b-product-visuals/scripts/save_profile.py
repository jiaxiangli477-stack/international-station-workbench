"""Save Agent-organized company references only after explicit user confirmation."""
import argparse,json,re
from datetime import datetime
from pathlib import Path

DOCUMENTS={'company':'company.md','category_rules':'category-rules.md','business_rules':'business-rules.md','visual_guide':'visual-guide.md','sources':'sources.md','readiness':'readiness.md'}
def text(value):return isinstance(value,str) and bool(value.strip())
def identifier(value):return text(value) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',value) is not None

def save(data,reference_root=None):
    if not isinstance(data,dict) or not identifier(data.get('company_id')):raise ValueError('safe company identifier required')
    confirmation=data.get('confirmation')
    if not isinstance(confirmation,dict) or confirmation.get('user_confirmed') is not True or not text(confirmation.get('source')):raise ValueError('explicit user confirmation and source required')
    try:datetime.fromisoformat(confirmation.get('confirmed_at',''))
    except (TypeError,ValueError):raise ValueError('confirmation date required')
    docs=data.get('documents');products=data.get('products',{})
    if not isinstance(docs,dict) or set(docs)-set(DOCUMENTS) or any(not text(docs.get(k)) for k in ['company','sources','readiness']):raise ValueError('company, sources and readiness reference text required; unknown documents are not allowed')
    if any(not text(v) for v in docs.values()):raise ValueError('provided reference documents must have text')
    if not isinstance(products,dict) or any(not identifier(k) or not text(v) for k,v in products.items()):raise ValueError('safe product identifiers and nonempty reference text required')
    root=Path(reference_root) if reference_root is not None else Path(__file__).resolve().parents[1]/'references/companies'
    root=root.resolve()
    if root.drive.upper() not in ('D:','E:'):raise ValueError('references must be on D: or E:')
    destination=root/data['company_id']
    if destination.exists():raise FileExistsError('company reference exists; review changes and confirm an explicit update instead of overwriting')
    destination.mkdir(parents=True)
    for key,content in docs.items():(destination/DOCUMENTS[key]).write_text(content.rstrip()+'\n',encoding='utf-8',newline='\n')
    if products:
        (destination/'products').mkdir()
        for key,content in products.items():(destination/'products'/(key+'.md')).write_text(content.rstrip()+'\n',encoding='utf-8',newline='\n')
    (destination/'_confirmation.json').write_text(json.dumps(confirmation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    for key,content in docs.items():
        if (destination/DOCUMENTS[key]).read_text(encoding='utf-8')!=content.rstrip()+'\n':raise ValueError('reference readback failed')
    return destination

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True,type=Path);a=p.parse_args();data=json.loads(a.input.read_text(encoding='utf-8-sig'));destination=save(data);print(json.dumps({'status':'references_saved','folder':str(destination),'scope':'references saved, not platform execution'},ensure_ascii=False))
if __name__=='__main__':main()
