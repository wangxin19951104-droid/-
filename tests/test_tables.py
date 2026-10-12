"""Spreadsheet upload regression fixtures; no model/provider calls."""
import io
import pathlib
import sys
import unittest
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from jiji_tables import read_table


def workbook(rows, target="worksheets/sheet1.xml", shared=True):
    output = io.BytesIO()
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("xl/workbook.xml", '<workbook xmlns="' + namespace + '" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="分镜" sheetId="1" r:id="rId1"/><sheet name="产品" sheetId="2" r:id="rId2"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Target="' + target + '"/><Relationship Id="rId2" Target="/xl/worksheets/sheet2.xml"/></Relationships>')
        if shared:
            archive.writestr("xl/sharedStrings.xml", '<sst xmlns="' + namespace + '"><si><t>镜头</t></si><si><r><t>雨夜</t></r><r><t>街道</t></r></si></sst>')
        archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="' + namespace + '"><sheetData>' + rows + '</sheetData></worksheet>')
        archive.writestr("xl/worksheets/sheet2.xml", '<worksheet xmlns="' + namespace + '"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>卖点</t></is></c><c r="B1" t="inlineStr"><is><t>防水</t></is></c></row></sheetData></worksheet>')
    return output.getvalue()


class TablesTests(unittest.TestCase):
    def test_csv_preserves_titles_quotes_newlines_and_blank_columns(self):
        content = '\ufeff镜头,画面,备注,台词\r\n1,"雨夜,街道",,"第一行\n第二行"\r\n'
        result = read_table("分镜.CSV", content.encode("utf-8"))
        self.assertIn('A="镜头"', result)
        self.assertIn('D="台词"', result)
        self.assertIn('B="雨夜,街道"', result)
        self.assertIn('D="第一行\\n第二行"', result)
        self.assertNotIn('C="第一行', result)

    def test_excel_csv_separator_and_windows_chinese_encoding(self):
        result = read_table("广告.csv", "sep=;\r\n产品;卖点\r\n雨伞;防水".encode("gb18030"))
        self.assertIn('B="防水"', result)
        self.assertNotIn('sep=', result)

    def test_utf16_tsv(self):
        result = read_table("广告.tsv", "镜头\t时长\r\n1\t5秒".encode("utf-16"))
        self.assertIn('B="5秒"', result)

    def test_xlsx_multiple_sheets_shared_rich_inline_and_cached_formula(self):
        raw = workbook('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><t>画面</t></is></c></row><row r="5"><c r="A5"><v>1</v></c><c r="C5" t="s"><v>1</v></c><c r="D5"><f>2+3</f><v>5</v></c><c r="XFD5" s="1"/></row>')
        result = read_table("分镜.xlsx", raw)
        self.assertIn('【工作表："分镜"】', result)
        self.assertIn('【工作表："产品"】', result)
        self.assertIn('第5行：A="1" | C="雨夜街道" | D="5"', result)
        self.assertIn('B="防水"', result)

    def test_xlsx_without_shared_strings_and_formula_result_missing(self):
        result = read_table("分镜.xlsx", workbook('<row r="1"><c r="A1" t="inlineStr"><is><t>分镜</t></is></c><c r="B1"><f>2+3</f></c></row>', shared=False))
        self.assertIn('A="分镜"', result)
        self.assertIn('公式无已保存结果', result)

    def test_bad_excel_and_legacy_format_have_actionable_errors(self):
        with self.assertRaisesRegex(ValueError, "另存为"):
            read_table("广告.xlsx", b"not a zip")
        with self.assertRaisesRegex(ValueError, ".xls"):
            read_table("广告.xls", b"legacy")

    def test_outside_workbook_path_rejected(self):
        with self.assertRaisesRegex(ValueError, "路径无效"):
            read_table("分镜.xlsx", workbook('', target="../../outside.xml"))

    def test_size_limit_signals_clipping_to_upload_handler(self):
        result = read_table("广告.csv", ("镜头,画面\n1," + "雨" * 1000).encode("utf-8"), limit=80)
        self.assertEqual(len(result), 81)

    def test_empty_delimited_file_returns_no_script(self):
        self.assertEqual(read_table("空表.csv", b",,\n,,\n"), "")


if __name__ == "__main__":
    unittest.main()
