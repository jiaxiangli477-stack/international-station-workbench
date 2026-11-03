import json
import sqlite3
import unittest
from contextlib import closing

import test_recruitment_paging as paging
import recruitment as native


class MainBusinessScopeTests(unittest.TestCase):
    setUp = paging.NativePagingTests.setUp
    tearDown = paging.NativePagingTests.tearDown
    fixture_snapshot = paging.NativePagingTests.fixture_snapshot

    def fixture_scope(self):
        self.fixture_snapshot()
        db = native.STATE / 'youhealth' / 'fixture.sqlite'
        rows = [
            ('运动营养补给', '电解质能量凝胶'),
            ('胶原蛋白', '美容护肤胶原蛋白软糖'),
            ('速溶咖啡', '菌菇速溶咖啡'),
            ('其他食品与饮料', '高蛋白奶昔粉'),
            ('其他保健用品', '女性益生菌软糖'),
            ('其他保健用品', '维生素C口腔喷雾'),
            ('草本补充剂', '速溶提神口腔能量贴片'),
            ('筋膜枪', '电动筋膜按摩枪'),
            ('口鼻身体贴', '维生素身体贴片'),
            ('其他保健用品', '外用益生菌除臭喷雾'),
            ('其他食品与饮料', '干制羊肚菌'),
            ('绿茶', '普通绿茶'),
            ('花生', '高蛋白花生零食'),
        ]
        with closing(sqlite3.connect(db)) as connection:
            for business in native.TYPES:
                for index, (leaf, title) in enumerate(rows):
                    item = {'id': 'scope' + str(index), 'title': title, 'tag': '',
                            'categoryLeaf': leaf, 'businessType': business}
                    connection.execute('INSERT INTO topics VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (business, item['id'], title, '', leaf, ',1,', '|US|', 1,
                         100 + index, json.dumps(item, ensure_ascii=False)))
            connection.commit()

    def test_main_scope_searches_entire_snapshot_and_keeps_nutrition_formats(self):
        self.fixture_scope()
        for business in native.TYPES:
            result = native.read_page('youhealth', {'businessType': business, 'category': '__main__'})
            self.assertEqual([row['id'] for row in result['records']], ['scope' + str(i) for i in range(7)])
            self.assertEqual(result['pagination']['totalRecords'], 7)
            self.assertEqual(result['pagination']['view'], 'filtered')
            self.assertEqual(result['businessScope']['retainedRecords'], 7)
            self.assertEqual(result['businessScope']['excludedRecords'], (61 if business == 'HOT_PRODUCT' else 7) + 6)

    def test_main_scope_combines_with_title_filter_and_raw_view_remains_available(self):
        self.fixture_scope()
        result = native.read_page('youhealth', {'category': '__main__', 'title': '口腔'})
        self.assertEqual(result['pagination']['totalRecords'], 2)
        self.assertEqual(result['businessScope']['retainedRecords'], 7)
        raw = native.read_page('youhealth', {'_unique': True})
        self.assertEqual(raw['pagination']['totalRecords'], 74)
        self.assertIsNone(raw.get('businessScope'))

    def test_exact_leaf_filter_still_available(self):
        self.fixture_scope()
        result = native.read_page('youhealth', {'category': '筋膜枪'})
        self.assertEqual([row['id'] for row in result['records']], ['scope7'])
