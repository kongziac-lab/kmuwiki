import io
import unittest

from kmu_ingest.parsers import extract_text


class TestMultimodalParsers(unittest.TestCase):
    def test_pdf_emits_rendered_page_with_page_number(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF unavailable")
        document = fitz.open()
        page = document.new_page(width=300, height=200)
        page.insert_text((30, 50), "KMU visual search page")
        payload = document.tobytes()
        document.close()

        result = extract_text("report.pdf", payload)

        pages = [asset for asset in result.assets if asset.asset_type == "page"]
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].page_no, 1)
        self.assertEqual(pages[0].media_type, "image/png")
        self.assertGreater(len(pages[0].image_bytes or b""), 100)

    def test_docx_table_becomes_markdown_search_asset(self):
        import docx

        document = docx.Document()
        document.add_paragraph("예산 보고")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "항목"
        table.cell(0, 1).text = "금액"
        table.cell(1, 0).text = "홍보비"
        table.cell(1, 1).text = "120만원"
        output = io.BytesIO()
        document.save(output)

        result = extract_text("budget.docx", output.getvalue())

        tables = [asset for asset in result.assets if asset.asset_type == "table"]
        self.assertEqual(len(tables), 1)
        self.assertIn("홍보비", tables[0].structured_content)
        self.assertIn("120만원", result.text)

    def test_xlsx_worksheet_becomes_structured_search_asset(self):
        import openpyxl

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "예산"
        sheet.append(["항목", "금액"])
        sheet.append(["홍보비", 1200000])
        output = io.BytesIO()
        workbook.save(output)

        result = extract_text("budget.xlsx", output.getvalue())

        sheets = [asset for asset in result.assets if asset.asset_type == "worksheet"]
        self.assertEqual(len(sheets), 1)
        self.assertEqual(sheets[0].caption, "예산")
        self.assertIn("1200000", sheets[0].structured_content)


if __name__ == "__main__":
    unittest.main()
