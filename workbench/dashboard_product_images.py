from contextlib import closing
"""Fill dashboard image URLs from the already collected complete weekly snapshot."""
import argparse
import json
from pathlib import Path
import re
import sqlite3


def fill_from_snapshot(workspace):
    workspace = Path(workspace)
    raw = workspace / 'raw'
    window = json.loads((raw / '_window.json').read_text(encoding='utf-8-sig'))
    week = max(window['weeks'], key=lambda w: w['week_end'])
    database = workspace / 'database/alibaba_growth.db'
    if not database.is_file():
        raise ValueError('缺少本次看板数据库')
    with closing(sqlite3.connect(database)) as c, c:
        period = c.execute('SELECT stat_week_start,stat_week_end FROM store_weekly_stats ORDER BY stat_week_end DESC LIMIT 1').fetchone()
    if period != (week['week_start'], week['week_end']):
        raise ValueError('产品快照与看板统计期间不一致')
    native_manifest = raw / 'native_week_products' / week['week_start'] / 'manifest.json'
    if native_manifest.is_file():
        stores = json.loads((workspace / 'stores.json').read_text(encoding='utf-8-sig'))
        active = stores.get('active')
        store_id = str((stores.get('stores', {}).get(active) or {}).get('store_id') or '')
        if not store_id.isdigit():
            raise ValueError('缺少已核验店铺ID，保留原主图数据')
        from dashboard_native_week import snapshot
        native = snapshot(workspace, week['week_start'], week['week_end'], store_id)
        if native is None:
            raise ValueError('缺少本期平台自然周商品分页快照')
        manifest, products = native
        page_count = len(manifest.get('pages') or [])
        snapshot_source = 'verified-platform-native-week'
    else:
        pages = sorted(raw.glob('shop_product_w1_p*.json'))
        if not pages:
            raise ValueError('缺少本期产品分页快照')
        products, expected = {}, None
        for number, path in enumerate(pages, 1):
            match = re.fullmatch(r'shop_product_w1_p(\d+)\.json', path.name)
            if not match or int(match[1]) != number:
                raise ValueError('产品分页不连续')
            response = json.loads(path.read_text(encoding='utf-8-sig'))
            data = response.get('data')
            if response.get('success') is not True or not isinstance(data, dict):
                raise ValueError('产品快照接口未完整成功')
            count, rows = data.get('recordCount'), data.get('data')
            if type(count) is not int or count < 0 or not isinstance(rows, list):
                raise ValueError('产品快照格式无效')
            if expected is None:
                expected = count
            if count != expected:
                raise ValueError('产品分页声明总数不一致')
            for row in rows:
                pid = str(row.get('id') or '')
                if not pid or pid in products:
                    raise ValueError('产品分页存在缺失或重复编号')
                products[pid] = row
        if len(products) != expected:
            raise ValueError('产品分页不完整，保留原主图数据')
        page_count = len(pages)
        snapshot_source = 'verified-weekly-snapshot'
    top, updated = [], 0
    with closing(sqlite3.connect(database)) as c, c:
        for pid, row in products.items():
            image = row.get('prodImage') or ''
            if not image:
                continue
            image = image.replace('_100x100.jpg', '_300x300.jpg').replace('_100x100.JPG', '_300x300.jpg')
            updated += c.execute('UPDATE products SET main_image=? WHERE product_id=?', (image, pid)).rowcount
        for pid, row in list(products.items())[:60]:
            image = row.get('prodImage') or ''
            if image:
                top.append({'product_id':pid,'img':image.replace('_100x100.jpg','_300x300.jpg').replace('_100x100.JPG','_300x300.jpg'),
                            'title':(row.get('subject') or '')[:70],'prod_level':row.get('prodLevel3') or '',
                            'cate':row.get('cateName') or '', 'inq':row.get('sumProdFbNum') or 0})
    (raw / 'top_imgs.json').write_text(json.dumps(top, ensure_ascii=False, indent=1), encoding='utf-8')
    return {'products':len(products),'updatedImages':updated,'pages':page_count,
            'start':week['week_start'],'end':week['week_end'],'source':snapshot_source}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()
    print(json.dumps(fill_from_snapshot(args.workspace), ensure_ascii=False))
