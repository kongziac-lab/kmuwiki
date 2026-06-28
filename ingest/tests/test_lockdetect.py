import io
import unittest
import zipfile

from kmu_ingest import lockdetect


class TestLockDetect(unittest.TestCase):
    def test_pdf_encrypt_flag(self):
        enc = b"%PDF-1.7\n... /Encrypt 12 0 R ..."
        plain = b"%PDF-1.7\n... normal content ..."
        self.assertTrue(lockdetect.file_is_encrypted("a.pdf", enc))
        self.assertFalse(lockdetect.file_is_encrypted("a.pdf", plain))

    def test_docx_ole_means_encrypted(self):
        ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16
        zip_ = b"PK\x03\x04" + b"\x00" * 16
        self.assertTrue(lockdetect.file_is_encrypted("x.docx", ole))
        self.assertFalse(lockdetect.file_is_encrypted("x.docx", zip_))

    def test_zip_entry_flag(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("plain.txt", "hello")
        with zipfile.ZipFile(buf) as zf:
            info = zf.infolist()[0]
            self.assertFalse(lockdetect.zip_entry_encrypted(info))


if __name__ == "__main__":
    unittest.main()
