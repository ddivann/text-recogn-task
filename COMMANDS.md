# Команды для запуска (PowerShell)

## 1. Подготовка и установка (выполняется один раз)

```powershell
# Создать виртуальное окружение .venv
py -m venv .venv

# Установить необходимые библиотеки из requirements.txt
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 2. Запуск программы

### А. Стандартный запуск на файлах задания (чтение текстового слоя PDF)
```powershell
.venv\Scripts\python.exe receipt_reader.py "Приложение к заданию 1.pdf" "Приложение к заданию 2.pdf" --output results/results.json
```

### Б. Принудительный режим OCR (распознавание через Tesseract, игнорируя текст PDF)
```powershell
.venv\Scripts\python.exe receipt_reader.py "Приложение к заданию 1.pdf" "Приложение к заданию 2.pdf" --ocr --output results/results_ocr.json
```

### В. Запуск на фотографии чека (JPG / PNG)
```powershell
.venv\Scripts\python.exe receipt_reader.py "путь\к\фото_чека.jpg" --output results/photo.json
```

---

## 3. Запуск тестов

```powershell
.venv\Scripts\python.exe -m unittest test_receipt_reader.py
```

---

## 4. Дополнительно: если Tesseract установлен в нестандартном месте

Если Tesseract OCR установлен не в `C:\Program Files\Tesseract-OCR\tesseract.exe`, перед запуском укажите путь:

```powershell
$env:TESSERACT_CMD = 'C:\Ваш_Путь\Tesseract-OCR\tesseract.exe'
```
