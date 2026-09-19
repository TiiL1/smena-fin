from app.categorize import categorize_expense, categorize_income


class TestExpenseCategorize:
    def test_автобус(self):
        cat, tag = categorize_expense("проезд автобус")
        assert cat == "Транспорт"
        assert tag == "Автобус"

    def test_лрт(self):
        cat, tag = categorize_expense("лрт")
        assert cat == "Транспорт"
        assert tag == "ЛРТ/Метро"

    def test_такси(self):
        cat, tag = categorize_expense("-1500 такси")
        assert cat == "Транспорт"
        assert tag == "Такси"

    def test_ресторан(self):
        cat, tag = categorize_expense("на ресторан")
        assert cat == "Еда"
        assert tag == "Ресторан"

    def test_свидание(self):
        cat, tag = categorize_expense("свидание")
        assert cat == "Развлечения"
        assert tag == "Свидание"

    def test_магнит(self):
        cat, tag = categorize_expense("в магнит")
        assert cat == "Еда"
        assert tag == "Супермаркет"

    def test_аптека(self):
        cat, tag = categorize_expense("аптека витамин")
        assert cat == "Здоровье"
        assert tag == "Аптека"

    def test_other_hint_does_not_block_auto_category(self):
        """«Другое» — это не выбор пользователя, а дефолт, поэтому автоопределение
        побеждает: именно это чинит баг «-110 проезд автобус → Другое»."""
        cat, tag = categorize_expense("автобус", "Другое")
        assert cat == "Транспорт"
        assert tag == "Автобус"

    def test_hint_is_real_category_wins_over_auto(self):
        """Если пользователь выбрал реальную категорию — она побеждает, tag берём из текста."""
        cat, tag = categorize_expense("на чай чайкин", "Здоровье")
        assert cat == "Здоровье"
        # tag fallback — «на» < 3 chars → пусто, но category корректен
        assert tag == ""

    def test_empty_note_returns_other(self):
        cat, tag = categorize_expense("")
        assert cat == "Другое"
        assert tag == ""

    def test_unknown_text_fallback_tag(self):
        cat, tag = categorize_expense("обед в куцая")
        assert cat == "Еда"  # «обед» в словаре еды
        assert tag == "Продукты"

    def test_benzine(self):
        cat, tag = categorize_expense("заправка бензин")
        assert cat == "Транспорт"
        assert tag == "Бензин"


class TestIncomeCategorize:
    def test_яндекс(self):
        src, tag = categorize_income("яндекс доставка")
        assert src == "Курьерка"
        assert tag == "Яндекс"

    def test_glovo(self):
        src, tag = categorize_income("глово заказ")
        assert src == "Курьерка"
        assert tag == "Glovo"

    def test_продажа_авито(self):
        src, tag = categorize_income("продал на авито")
        assert src == "Продажа"
        assert tag == "Продажа"
