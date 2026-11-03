from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import inquiry_release
import public_checks
import weekly_update

class InquiryReleaseTests(unittest.TestCase):
    def test_snapshot_includes_new_modules_and_preserves_certificate_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);manifest=inquiry_release.prepare(path)
            for name in ('extract_entities.py','verify_companies.py','make_customer_table.py','customer_table_html.py','customer_rows.py','deal_blocker.py','company_strength.py','inq_brief.py','fetch_buyer_contacts.py'):
                self.assertIn(name,manifest['files']);self.assertTrue((path/name).is_file())
            verifier=(path/'verify_companies.py').read_text(encoding='utf-8')
            self.assertIn('ctx.check_hostname = True',verifier)
            self.assertNotIn('ctx.verify_mode = ssl.CERT_NONE',verifier)
            self.assertIn('require_public_url(url)',verifier)
            self.assertNotIn('ctx.check_hostname = False',verifier)
            for name in manifest['files']:
                self.assertNotIn(b'\r\r\n',(path/name).read_bytes())
                compile((path/name).read_text(encoding='utf-8'),name,'exec')
            self.assertEqual(len(inquiry_release.WORKBOOK_SHEETS),12)
            self.assertIn('9 成交卡点',inquiry_release.WORKBOOK_SHEETS)
            self.assertIn('0 结论与行动',inquiry_release.WORKBOOK_SHEETS)
            self.assertIn('10 公司档案',inquiry_release.WORKBOOK_SHEETS)
            self.assertIn('_workbench_strength[nm]',(path/'make_inquiry_report.py').read_text(encoding='utf-8'))
    def test_unrecognized_report_scoring_stops_before_publishing(self):
        import weekly_update
        with self.assertRaises(weekly_update.SyncError):
            inquiry_release.align_report_quality('print("unsupported report")')
    def test_public_checker_rejects_internal_targets_and_redirects(self):
        for url in ('http://localhost/','http://127.0.0.1/','http://server/','http://192.168.2.153/','ftp://example.com','https://example.com:8796'):
            with self.subTest(url=url),self.assertRaises(ValueError):public_checks.require_public_url(url)
        answers=[(2,1,6,'',('10.0.0.1',443))]
        with patch.object(public_checks.socket,'getaddrinfo',return_value=answers):
            with self.assertRaises(ValueError):public_checks.require_public_url('https://example.com/')
    def test_snapshot_uses_the_project_d_drive_package_even_if_c_copy_is_newer(self):
        source=Path(weekly_update.PACKAGE)
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);package=base/'d-package';c_copy=base/'c-copy';output=base/'engine'
            package.mkdir();c_copy.mkdir()
            for name in inquiry_release.FILES:
                source_file=source/name
                self.assertTrue(source_file.is_file(),name)
                shutil.copy2(source_file,package/name)
                shutil.copy2(source_file,c_copy/name)
                stat=(c_copy/name).stat()
                import os
                os.utime(c_copy/name,(stat.st_atime+30,stat.st_mtime+30))
            with patch.object(weekly_update,'PACKAGE',package),patch.object(weekly_update,'SKILL',c_copy,create=True):
                manifest=inquiry_release.prepare(output)
            self.assertEqual({Path(row['source']).parent for row in manifest['files'].values()},{package})

if __name__=='__main__':unittest.main()
