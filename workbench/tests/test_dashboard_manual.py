from pathlib import Path
import tempfile
import unittest
import dashboard_manual as manual

class ManualArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='D:/Codex');self.db=Path(self.temp.name)/'manual.sqlite3'
        self.key=('store1','week','2026-10-12','2026-10-18')
    def tearDown(self):self.temp.cleanup()
    def test_data_survives_reload_and_zero_is_not_missing(self):
        record=manual.save(*self.key,{'new_count':65,'acquisition':0,'annual_fee':246.58},0,db=self.db)
        self.assertEqual(manual.load(*self.key,db=self.db)['fields'],record['fields'])
        self.assertEqual(record['fields']['acquisition'],0)
    def test_no_cross_store_or_period_carry_and_history_is_append_only(self):
        manual.save(*self.key,{'new_count':65},0,db=self.db)
        manual.save(*self.key,{'new_count':66},1,db=self.db)
        self.assertEqual(len(manual.export_store('store1',db=self.db)['entries']),2)
        self.assertEqual(manual.load('store2',*self.key[1:],db=self.db)['revision'],0)
        self.assertEqual(manual.load('store1','week','2026-10-19','2026-10-25',db=self.db)['revision'],0)
    def test_each_week_and_month_accepts_and_retains_different_quantities(self):
        manual.save(*self.key,{'new_count':65,'sample_orders':1},0,db=self.db)
        manual.save('store1','week','2026-10-19','2026-10-25',{'new_count':7,'sample_orders':3},0,db=self.db)
        manual.save('store1','month','2026-10-01','2026-10-31',{'new_count':120,'sample_orders':9},0,db=self.db)
        self.assertEqual(manual.load(*self.key,db=self.db)['fields']['new_count'],65)
        self.assertEqual(manual.load('store1','week','2026-10-19','2026-10-25',db=self.db)['fields']['new_count'],7)
        self.assertEqual(manual.load('store1','month','2026-10-01','2026-10-31',db=self.db)['fields']['new_count'],120)
    def test_stale_tabs_cannot_overwrite_newer_edits(self):
        manual.save(*self.key,{'new_count':65},0,db=self.db)
        with self.assertRaises(manual.Conflict):manual.save(*self.key,{'new_count':1},0,db=self.db)
        self.assertEqual(manual.load(*self.key,db=self.db)['fields']['new_count'],65)
    def test_invalid_fields_and_numbers_are_rejected(self):
        for fields in ({'new_count':-1},{'new_count':True},{'annual_fee':float('nan')},{'unexpected':'x'}):
            with self.assertRaises(ValueError):manual.save(*self.key,fields,0,db=self.db)
    def test_build_snapshot_recovers_exact_period_and_leaves_next_week_blank(self):
        manual.save(*self.key,{'sample_orders':1,'sample_products':'甘氨酸复合固体饮料'},0,db=self.db)
        data={'meta':{'store_id':'store1'},'audit_periods':{'week:2026-10-12':{'period':{'week_start':'2026-10-12','week_end':'2026-10-18'},'boss':{'manual':{'sample_orders':None}}},'week:2026-10-19':{'period':{'week_start':'2026-10-19','week_end':'2026-10-25'},'boss':{'manual':{'sample_orders':None}}}}}
        manual.merge_into_data(data,db=self.db)
        self.assertEqual(data['audit_periods']['week:2026-10-12']['boss']['manual']['sample_orders'],1)
        self.assertIsNone(data['audit_periods']['week:2026-10-19']['boss']['manual']['sample_orders'])
    def test_backup_roundtrip_keeps_history_and_never_overwrites_conflicts(self):
        manual.save(*self.key,{'new_count':65},0,db=self.db)
        bundle=manual.export_store('store1',db=self.db)
        target=Path(self.temp.name)/'restored.sqlite3'
        manual.import_backup(bundle,'store1',db=target)
        self.assertEqual(manual.load(*self.key,db=target)['fields']['new_count'],65)
        self.assertEqual(manual.import_backup(bundle,'store1',db=target)['imported'],0)
        with self.assertRaises(ValueError):manual.import_backup(bundle,'store2',db=target)

if __name__=='__main__':unittest.main()
