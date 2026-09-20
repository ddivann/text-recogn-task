"""Локальное чтение PDF и фотографий чеков. Запуск: python receipt_reader.py чек.pdf"""

import argparse
import json
import os
import re
import shutil
import sys
import textwrap
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageOps
from pypdf import PdfReader


MONEY = r"(?:\d{1,3}(?: \d{3})+|\d+)[.,]\d{2}"
ITEM = re.compile(
    rf"^\d+\s+(.+?)\s+({MONEY})\s+(\d+(?:[.,]\d+)?)\s+"
    rf"(шт\.?|кг|г|л|мл)(?:\s+({MONEY}))?$", re.IGNORECASE
)
MONTHS = "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()


def number(value):
    """Decimal исключает погрешность float при сложении денежных сумм."""
    return Decimal(value.replace(" ", "").replace(",", "."))


def find(pattern, text):
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None


def amount_after(label, text):
    value = find(rf"{label}\s+({MONEY})", text)
    return f"{number(value):.2f}" if value else None


def read_text(path, force_ocr=False):
    """Читаем текстовый слой; для сканов и --ocr распознаём изображение."""
    import pypdfium2 as pdfium
    import pytesseract

    def ocr(image):
        executable = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
        if not executable:
            candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tesseract-OCR/tesseract.exe"
            if candidate.is_file():
                executable = str(candidate)
        if not executable:
            raise ValueError("Установите Tesseract OCR или задайте TESSERACT_CMD (см. README.md).")
        pytesseract.pytesseract.tesseract_cmd = executable
        models = Path(__file__).resolve().parent / "tessdata"
        if models.is_dir():
            os.environ["TESSDATA_PREFIX"] = str(models)
        languages = pytesseract.get_languages()
        if not {"rus", "eng"}.issubset(languages):
            raise ValueError("Для OCR нужны языки rus и eng (см. README.md).")
        image = ImageOps.grayscale(ImageOps.exif_transpose(image))
        return pytesseract.image_to_string(image, lang="rus+eng", config="--psm 3", timeout=90)

    if path.suffix.lower() != ".pdf":
        with Image.open(path) as image:
            return ocr(image), "ocr"

    reader = PdfReader(path)
    pages, methods = [], set()
    for index, page in enumerate(reader.pages):
        text = "" if force_ocr else page.extract_text()
        if text and text.strip():
            methods.add("pdf_text")
        else:
            document = pdfium.PdfDocument(path)
            try:
                image = document[index].render(scale=3).to_pil()
                text = ocr(image)
            finally:
                document.close()
            methods.add("ocr")
        pages.append(text)
    return "\n".join(pages), "+".join(sorted(methods))


def purchase_date(text):
    match = re.search(r"(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}))?", text)
    if match:
        value = datetime.strptime(match[1], "%d.%m.%Y").date().isoformat()
        return value, match[2]
    match = re.search(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\s*г\.?\s*(\d{2}:\d{2})?", text, re.I)
    if match:
        value = datetime(int(match[3]), MONTHS.index(match[2].lower()) + 1, int(match[1]))
        return value.date().isoformat(), match[4]
    return None, None


def parse_text(raw_text):
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line and not re.fullmatch(r"[-_=]+", line)]
    text = "\n".join(lines)
    result = dict(document_type="unknown", date=None, time=None, merchant=None,
                  items=[], delivery=None, total=None, operation_amount=None,
                  payments={}, details={}, checks={}, warnings=[])
    warnings = result["warnings"]
    try:
        result["date"], result["time"] = purchase_date(text)
    except ValueError:
        warnings.append("Не удалось разобрать дату; проверьте исходный текст.")

    if re.search(r"кассовый\s+чек", text, re.I):
        result["document_type"] = "receipt"
        result["merchant"] = find(r"^((?:ООО|ИП|АО|ПАО)\s+.+?)(?:\s+ИНН|$)", text)
        current, in_table = None, False
        entries = []
        for line in lines:
            if re.search(r"наименование", line, re.I):
                in_table = True
                continue
            if re.match(r"итог\b", line, re.I):
                break
            if not in_table or line.lower() in {"сумма", "цена", "кол-во"}:
                continue
            match = ITEM.fullmatch(line)
            if match:
                name, price, quantity, unit, total = match.groups()
                current = dict(name=name, quantity=str(number(quantity)), unit=unit,
                               unit_price=f"{number(price):.2f}",
                               amount=f"{number(total):.2f}" if total else None)
                entries.append(current)
            elif current and re.fullmatch(MONEY, line) and current["amount"] is None:
                current["amount"] = f"{number(line):.2f}"
            elif current:
                current["name"] += " " + line

        deliveries = []
        for item in entries:
            if item["amount"] is None:
                warnings.append(f"Не найдена сумма позиции: {item['name']}.")
            elif number(item["quantity"]) * number(item["unit_price"]) != number(item["amount"]):
                warnings.append(f"Цена × количество не совпадает с суммой: {item['name']}.")
            (deliveries if re.match(r"доставка\b", item["name"], re.I) else result["items"]).append(item)
        if deliveries and all(item["amount"] is not None for item in deliveries):
            result["delivery"] = f"{sum(number(item['amount']) for item in deliveries):.2f}"
        result["total"] = amount_after(r"^итог", text)
        for label, key in [("Безналичными", "cashless"), ("Встречным предоставлением", "counter_provision")]:
            value = amount_after(label, text)
            if value is not None:
                result["payments"][key] = value
        for key, pattern in {
            "receipt_number": r"кассовый чек\s*[№#]?\s*(\d+)",
            "inn": r"\bИНН\s+(\d{10}(?:\d{2})?)\b",
            "fiscal_document": r"Фискальный документ\s*#?(\d+)",
            "order_number": r"Номер заказа\s*#?(\d+)",
            "register_number": r"РН ККТ\s+(\d+)",
            "fiscal_drive": r"\bФН\s+(\d+)",
            "register_serial": r"Заводской номер ККТ\s+(\d+)",
            "fiscal_sign": r"Фискальный признак\s+(\d+)",
            "ffd_version": r"ФФД\s+(\d+\.\d+)",
            "tax_system": r"Система налогообложения\s+([^\n]+)",
        }.items():
            result["details"][key] = find(pattern, text)
        result["details"]["emails"] = re.findall(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", text)
        if entries and result["total"] and all(item["amount"] is not None for item in entries):
            computed = sum(number(item["amount"]) for item in entries)
            result["checks"]["items_total_matches"] = computed == number(result["total"])
            if not result["checks"]["items_total_matches"]:
                warnings.append("Сумма позиций и доставки не совпадает с итогом.")
        if result["payments"] and result["total"]:
            paid = sum(number(value) for value in result["payments"].values())
            result["checks"]["payments_total_matches"] = paid == number(result["total"])
            if not result["checks"]["payments_total_matches"]:
                warnings.append("Извлечённые способы оплаты не покрывают итог чека.")
        if not result["items"]:
            warnings.append("Товарные позиции не распознаны.")
        if result["total"] is None:
            warnings.append("Итог чека не найден.")
        if result["delivery"] is None:
            warnings.append("Стоимость доставки не найдена; это не означает бесплатную доставку.")
    elif re.search(r"Дата операции|Карта списания", text, re.I):
        result["document_type"] = "bank_operation"
        match = re.search(r"^[−—–-]\s*(\d[\d ]*(?:[.,]\d{2})?)\s*(?:₽|[РP]|руб\.?)$", text, re.M | re.I)
        if match:
            result["operation_amount"] = f"{number(match[1]):.2f}"
            previous = text[:match.start()].strip().splitlines()
            result["merchant"] = previous[-1] if previous else None
        else:
            warnings.append("Сумма банковской операции не найдена.")
        result["details"] = {
            "status": find(r"^(Выполняется|Выполнено|Отклонено|Отменено)$", text),
            "card_last4": find(r"Карта списания\s+[^\d\n]*(\d{4})\b", text),
            "mcc": find(r"[МM][СC][СC]-код\s+(\d{4})", text),
            "account_holder": find(r"Владелец счета\s+([^\n]+)", text),
        }
        warnings.append("Банковская операция: товары, доставка и итог кассового чека здесь отсутствуют.")
    else:
        warnings.append("Формат документа не распознан. Проверьте raw_text в JSON.")
    if result["date"] is None:
        warnings.append("Дата не найдена.")
    return result


def print_result(result):
    titles = {"receipt": "Кассовый чек", "bank_operation": "Банковская операция", "unknown": "Неизвестный документ"}
    print(f"\n{result['source']}\n{'=' * 80}")
    print(f"{titles[result['document_type']]} | Способ чтения: {result['method']}")
    print(f"Дата: {result['date'] or 'не найдена'} {result['time'] or ''}")
    print(f"Продавец: {result['merchant'] or 'не найден'}")
    if result["items"]:
        print(f"\n{'Наименование':44} {'Кол-во':>7} {'Цена':>10} {'Сумма':>10}")
        print("-" * 80)
        for item in result["items"]:
            name = textwrap.wrap(item["name"], 44)
            print(f"{name[0]:44} {item['quantity']:>7} {item['unit_price']:>10} {item['amount'] or '?':>10}")
            for line in name[1:]:
                print(line)
    for key, label in [("delivery", "Доставка"), ("total", "ИТОГ чека"), ("operation_amount", "Сумма списания")]:
        if result[key] is not None:
            print(f"{label}: {result[key]} руб.")
    for key, value in result["payments"].items():
        print(f"{'Безналичными' if key == 'cashless' else 'Встречным предоставлением'}: {value} руб.")
    if result["details"]:
        print("Реквизиты:", json.dumps(result["details"], ensure_ascii=False))
    for key, value in result["checks"].items():
        print(f"{'Проверка суммы позиций' if key == 'items_total_matches' else 'Проверка оплаты'}: {'OK' if value else 'НЕ СОВПАДАЕТ'}")
    for warning in result["warnings"]:
        print("Примечание:", warning)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="+", help="PDF, PNG или JPG; один документ на файл")
    parser.add_argument("--ocr", action="store_true", help="Распознавать PDF как изображение, игнорируя текстовый слой")
    parser.add_argument("--output", type=Path, default=Path("results.json"), help="Путь для JSON")
    args = parser.parse_args()
    if args.output.resolve() in {path.resolve() for path in args.files}:
        parser.error("Выходной JSON не должен перезаписывать входной документ.")
    results, errors = [], 0
    for path in args.files:
        try:
            if path.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg"}:
                raise ValueError("Поддерживаются PDF, PNG и JPG.")
            raw_text, method = read_text(path, args.ocr)
            result = parse_text(raw_text)
            result.update(source=path.name, method=method, raw_text=raw_text)
            if "ocr" in method:
                result["warnings"].append("OCR может ошибаться в буквах и цифрах; сверьте важные поля с оригиналом.")
            print_result(result)
            results.append(result)
        except Exception as error:
            errors += 1
            print(f"Ошибка: {path.name}: {error}", file=sys.stderr)
            results.append({"source": path.name, "error": str(error)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON сохранён: {args.output}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
