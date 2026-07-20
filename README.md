# PRISMA Monitor

Невелика Windows-програма для ручного запуску, відкриття PRISMA у Chrome або Edge,
імпорту `Auction_overview.csv`, видалення дублікатів і формування Excel.

## Запуск у VS Code

1. Відкрийте папку репозиторію у VS Code.
2. Скопіюйте в неї всі файли цього шаблону.
3. Запустіть `setup.bat`.
4. Після встановлення запустіть `run.bat`.

Або через термінал VS Code:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Поточні можливості

- вибір Chrome або Edge;
- відкриття сторінки аукціонів PRISMA;
- ручний вибір CSV;
- автоматичне встановлення фільтра `Marketed Capacity >= 1000 kWh/h` після відкриття PRISMA;
- SQLite-база без дублікатів;
- Excel у `data/result/prisma_auctions.xlsx`;
- кнопки запуску, зупинки та закриття.

## Важливо

Автоматичне завантаження CSV буде додано наступним етапом.
Поточна версія вже дозволяє перевірити імпорт реального CSV та логіку дедуплікації.
