"""Проверки ключевых требований: python -m unittest -v."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from receipt_reader import parse_text

ROOT = Path(__file__).resolve().parent


class ReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = PdfReader(ROOT / "Приложение к заданию 1.pdf").pages[0].extract_text()
        cls.bank = PdfReader(ROOT / "Приложение к заданию 2.pdf").pages[0].extract_text()

    def test_receipt_fields_and_totals(self):
        result = parse_text(self.receipt)
        self.assertEqual(len(result["items"]), 7)
        self.assertEqual(result["delivery"], "439.00")
        self.assertEqual(result["total"], "7178.00")
        self.assertEqual(result["date"], "2026-04-04")
        self.assertEqual(result["time"], "23:35")
        self.assertEqual(result["details"]["register_number"], "0007939221007943")
        self.assertIn("PWK 1725CGLD Wi-Fi IQ Home", result["items"][0]["name"])
        self.assertEqual(result["payments"], {"cashless": "6878.00", "counter_provision": "300.00"})
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["warnings"], [])

    def test_bank_does_not_invent_receipt_fields(self):
        result = parse_text(self.bank)
        self.assertEqual(result["document_type"], "bank_operation")
        self.assertEqual(result["operation_amount"], "6878.00")
        self.assertEqual(result["time"], "23:31")  # Не время телефона 23:50.
        self.assertEqual(result["details"]["status"], "Выполняется")
        self.assertEqual(result["items"], [])
        self.assertIsNone(result["delivery"])
        self.assertIsNone(result["total"])

    def test_changed_total_is_reported(self):
        result = parse_text(self.receipt.replace("7 178.00", "7 179.00"))
        self.assertFalse(result["checks"]["items_total_matches"])
        self.assertFalse(result["checks"]["payments_total_matches"])

    def test_quantities_and_decimal_commas(self):
        text = "Кассовый чек №2\nНаименование Цена Кол-во Сумма\n1 Яблоки 12,50 2 кг 25,00\nИТОГ 25,00"
        result = parse_text(text)
        self.assertEqual(result["items"][0]["quantity"], "2")
        self.assertEqual(result["items"][0]["amount"], "25.00")
        self.assertTrue(result["checks"]["items_total_matches"])
        self.assertIsNone(result["delivery"])

    def test_missing_amount_is_not_calculated_as_observed(self):
        result = parse_text("Кассовый чек\nНаименование\n1 Чай 20.00 2 шт\nИТОГ 40.00")
        self.assertIsNone(result["items"][0]["amount"])
        self.assertNotIn("items_total_matches", result["checks"])
        self.assertTrue(result["warnings"])

    def test_unknown_and_invalid_date(self):
        result = parse_text("Просто текст 31.02.2026")
        self.assertEqual(result["document_type"], "unknown")
        self.assertIsNone(result["date"])
        self.assertTrue(result["warnings"])

    def test_cli_keeps_valid_result_when_another_file_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.json"
            run = subprocess.run([sys.executable, str(ROOT / "receipt_reader.py"),
                                  str(ROOT / "missing.pdf"), str(ROOT / "Приложение к заданию 1.pdf"),
                                  "--output", str(output)], capture_output=True)
            self.assertEqual(run.returncode, 1)
            results = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("error", results[0])
            self.assertEqual(results[1]["total"], "7178.00")


if __name__ == "__main__":
    unittest.main()
