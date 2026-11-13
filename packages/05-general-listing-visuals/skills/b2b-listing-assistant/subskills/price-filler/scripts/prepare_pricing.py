"""Validate a current-SKU confirmed quote without calculating or filling prices."""
import argparse,json,re
from decimal import Decimal,InvalidOperation
from pathlib import Path

def valid_text(value):
    return isinstance(value,str) and bool(value.strip()) and value.strip().lower() not in {'none','null','unknown','n/a','待确认'}

def prepare(data):
    errors=[];warnings=[]
    result={'status':'blocked','product_id':None,'moq':None,'currency':None,'unit':None,'tiers':[],'sources':{},'errors':errors,'warnings':warnings,'filled':False,'publishable':False,'scope':'Only declared evidence and numeric structure checked; no source authentication or browser action'}
    if not isinstance(data,dict):errors.append('输入必须为对象');return result
    pid=data.get('product_id');result['product_id']=pid if valid_text(pid) else None
    if not valid_text(pid):errors.append('缺少当前产品标识')
    pricing=data.get('pricing',{})
    if not isinstance(pricing,dict):errors.append('pricing必须为对象');return result
    values={}
    for key in ['moq','currency','unit','tiers']:
        item=pricing.get(key)
        if not isinstance(item,dict) or item.get('status')!='confirmed' or not valid_text(item.get('source')) or item.get('product_id')!=pid or item.get('conflict'):
            errors.append(key+': 缺少同SKU已确认且无冲突的来源');continue
        values[key]=item.get('value');result['sources'][key]=item['source']
    if errors:return result
    moq=values['moq'];currency=values['currency'];unit=values['unit'];tiers=values['tiers']
    if not isinstance(moq,int) or isinstance(moq,bool) or moq<1:errors.append('MOQ需为正整数')
    if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency):errors.append('币种需为资料确认的三位大写代码；本工具不验证代码实际适用性')
    if not valid_text(unit):errors.append('计价单位缺失')
    if not isinstance(tiers,list) or not tiers:errors.append('缺少确认的价格阶梯');return result
    previous=None;clean=[];previous_price=None
    for row in tiers:
        if not isinstance(row,dict) or set(row)!={'min_quantity','unit_price'}:errors.append('每档仅支持min_quantity与unit_price，其他结构需另行适配');continue
        quantity=row['min_quantity'];price=row['unit_price']
        if not isinstance(quantity,int) or isinstance(quantity,bool) or quantity<1:errors.append('阶梯数量需为正整数');continue
        if previous is not None and quantity<=previous:errors.append('阶梯数量必须递增且不重复')
        previous=quantity
        try:
            if isinstance(price,bool) or not isinstance(price,(str,int,float)):raise InvalidOperation
            decimal=Decimal(str(price))
            if not decimal.is_finite() or decimal<=0:raise InvalidOperation
        except (InvalidOperation,ValueError):errors.append('价格缺失、非有限数或不为正');continue
        if previous_price is not None and decimal>previous_price:warnings.append('数量增加但价格升高，请核对报价条件')
        previous_price=decimal;clean.append({'min_quantity':quantity,'unit_price':str(price)})
    if errors:return result
    result.update(moq=moq,currency=currency,unit=unit,tiers=clean)
    if clean[0]['min_quantity']!=moq:warnings.append('首档数量与MOQ不同，需要业务确认两者语义；未自动改价或改量')
    result['status']='needs_review' if warnings else 'ready_for_local_review'
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve()
    if out.drive.upper() not in ('D:','E:'):raise ValueError('output must be on D: or E:')
    r=prepare(json.loads(a.input.read_text(encoding='utf-8-sig')));out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');print(r['status'],out);return 0 if r['status']=='ready_for_local_review' else 2
if __name__=='__main__':raise SystemExit(main())
