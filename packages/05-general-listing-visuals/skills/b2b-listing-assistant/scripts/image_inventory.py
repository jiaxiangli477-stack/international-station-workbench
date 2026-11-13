"""Inspect one SKU's final images and an explicit detail-module map locally; never uploads."""
import argparse,json,re,hashlib
from pathlib import Path
from PIL import Image

EXTENSIONS={'.png','.jpg','.jpeg'}

def inventory(root, mapping=None, product_id=None):
    root=Path(root).resolve();mapping={} if mapping is None else mapping
    errors=[];main=[];detail=[]
    result={'status':'blocked','main':main,'detail':detail,'errors':errors,'uploaded':False,'product_id':product_id,'visual_review':'pending','sku_identity_review':'pending','inspection':'file integrity only; not visual or platform approval'}
    if not isinstance(product_id,str) or not product_id.strip():errors.append('缺少当前图片产品标识')
    if not root.is_dir():errors.append('产品图片目录不存在');return result
    if not isinstance(mapping,dict):errors.append('详情分类映射必须为对象');return result
    def select(names):
        found=[root/name for name in names if (root/name).is_dir()]
        if len(found)>1:errors.append('同一产品有多个候选目录，请只留一个明确入口: '+','.join(p.name for p in found));return None
        return found[0] if found else None
    main_dir=select(('主图','main'));detail_dir=select(('详情页','detail'))
    for directory,kind in [(main_dir,'main'),(detail_dir,'detail')]:
        if directory is None:continue
        for file in sorted(directory.iterdir()):
            if file.is_dir():errors.append('成品目录不允许子目录: '+str(file.relative_to(root)));continue
            if file.suffix.lower() in {'.txt','.md'} and ('说明' in file.stem or file.stem.lower() in {'readme'}):continue
            try:resolved=file.resolve();resolved.relative_to(root)
            except ValueError:errors.append('文件跳转到产品目录之外: '+file.name);continue
            if file.suffix.lower() not in EXTENSIONS:errors.append('未支持文件格式: '+file.name);continue
            if re.search(r'draft|preview|proof|tmp|草稿|预览|副本',file.stem,re.I):errors.append('成品目录包含草稿或预览: '+file.name);continue
            if kind=='main':
                match=re.fullmatch(r'm([1-6])',file.stem)
                if not match:errors.append('主图必须命名m1至m6: '+file.name);continue
                order=int(match.group(1));group=None
                if any(x['order']==order for x in main):errors.append('主图序号重复: '+file.name);continue
            else:
                if not re.fullmatch(r'd(?:[1-9]\d*|f|fac|c|rev)',file.stem):errors.append('详情图名称不明确: '+file.name);continue
                group=mapping.get(file.name)
                if not isinstance(group,dict) or not isinstance(group.get('module'),str) or not group['module'].strip() or not isinstance(group.get('source'),str) or not group['source'].strip() or not isinstance(group.get('order'),int) or isinstance(group.get('order'),bool) or group['order']<1:
                    errors.append('缺少详情模块、顺序或页面来源映射: '+file.name);continue
                order=group['order']
                if any(x['order']==order for x in detail):errors.append('详情顺序重复: '+file.name);continue
            try:
                with Image.open(file) as image:
                    size=image.size
                    expected='JPEG' if file.suffix.lower() in {'.jpg','.jpeg'} else 'PNG'
                    if image.format!=expected:raise ValueError('图片扩展名与文件格式不一致')
                    if image.convert('RGBA').getchannel('A').getbbox() is None:raise ValueError('图片全透明')
                with Image.open(file) as check:check.verify()
            except Exception as exc:errors.append('图片损坏或无法解码: '+file.name);continue
            item={'path':file.relative_to(root).as_posix(),'order':order,'width':size[0],'height':size[1],'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'product_id':product_id}
            if kind=='detail':item.update(module=group['module'],source=group['source'])
            (main if kind=='main' else detail).append(item)
    main.sort(key=lambda x:x['order']);detail.sort(key=lambda x:x['order'])
    if not main:errors.append('没有有效主图')
    elif [x['order'] for x in main]!=list(range(1,len(main)+1)):errors.append('主图序号不连续或缺少m1')
    if detail and [x['order'] for x in detail]!=list(range(1,len(detail)+1)):errors.append('详情顺序不连续')
    existing_details={Path(x['path']).name for x in detail}
    for name in mapping:
        if name not in existing_details:errors.append('映射引用缺失或未通过检查的详情图: '+str(name))
    if not errors:result['status']='ready_for_local_review'
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image-dir',required=True,type=Path);p.add_argument('--mapping',type=Path);p.add_argument('--product-id',required=True);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    out=a.output.resolve()
    if out.drive.upper() not in ('D:','E:'):raise ValueError('output must be on D: or E:')
    mapping=json.loads(a.mapping.read_text(encoding='utf-8-sig')) if a.mapping else {}
    result=inventory(a.image_dir,mapping,a.product_id);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(result['status'],out)
    return 2 if result['errors'] else 0
if __name__=='__main__':raise SystemExit(main())
