"""Сверка результатов разных движков.

Зачем: ускорение засчитывается, только если движок вернул ТОТ ЖЕ ответ.
Сравнение «в лоб» не работает по двум причинам:
  1. Порядок строк может отличаться — поэтому сортируем оба результата.
  2. Числа с плавающей точкой у разных движков могут отличаться в последних
     знаках (разный порядок суммирования) — поэтому сравниваем с допуском.
Также разные движки возвращают целые числа разных типов (Int64, UInt32),
поэтому числовые колонки приводим к Float64 перед сравнением.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Polars: результаты всех движков приводятся к polars.DataFrame.


def compare(reference: pl.DataFrame, candidate: pl.DataFrame, sort_by: list[str],
            rel_tol: float = 1e-6, abs_tol: float = 1e-9) -> list[str]:
    """Сравнить результат candidate с эталоном reference.

    Возвращает список найденных расхождений. Пустой список — результаты совпали.
    rel_tol — допустимая относительная погрешность, abs_tol — абсолютная (для чисел около нуля).
    """
    problems: list[str] = []  # Сюда будем записывать найденные расхождения.
    ref = reference.rename({c: c.lower() for c in reference.columns})  # Имена колонок к нижнему регистру (движки могут вернуть «SUM_QTY»).
    cand = candidate.rename({c: c.lower() for c in candidate.columns})  # То же для проверяемого результата.

    if set(ref.columns) != set(cand.columns):  # Наборы колонок должны совпадать.
        problems.append(f"разные колонки: {sorted(ref.columns)} против {sorted(cand.columns)}")  # Описываем расхождение.
        return problems  # Дальше сравнивать бессмысленно.
    if ref.height != cand.height:  # Число строк должно совпадать (height — число строк).
        problems.append(f"разное число строк: {ref.height} против {cand.height}")
        return problems  # Дальше сравнивать бессмысленно.

    cand = cand.select(ref.columns)  # Ставим колонки кандидата в том же порядке, что у эталона.
    if sort_by:  # Если указаны колонки сортировки...
        ref = ref.sort(sort_by)  # ...сортируем эталон...
        cand = cand.sort(sort_by)  # ...и кандидата одинаково, чтобы строки шли в одном порядке.

    for col in ref.columns:  # Сравниваем колонку за колонкой.
        a, b = ref[col], cand[col]  # Колонки эталона и кандидата (тип Series).
        if a.dtype.is_numeric() and b.dtype.is_numeric():  # Обе колонки числовые?
            pair = pl.DataFrame({"a": a.cast(pl.Float64), "b": b.cast(pl.Float64)})  # Кладём обе колонки рядом, приведя к Float64.
            diff = (pl.col("a") - pl.col("b")).abs()  # Выражение: абсолютная разница в каждой строке.
            allowed = pl.max_horizontal(pl.col("a").abs(), pl.col("b").abs()) * rel_tol + abs_tol  # Выражение: допустимая разница в строке.
            check = pair.select(  # Считаем три числа по всей колонке за один проход.
                nulls_differ=(pl.col("a").is_null() != pl.col("b").is_null()).sum(),  # Сколько строк, где пропуск только у одного движка.
                too_far=(diff > allowed).sum(),  # Сколько строк вышли за допуск (строки с пропусками сюда не попадают).
                max_diff=diff.max(),  # Максимальная разница — для отчёта.
            ).row(0, named=True)  # Берём единственную строку результата как словарь.
            if check["nulls_differ"]:  # Пропуски не совпали по положению — это ошибка.
                problems.append(f"колонка {col}: пропуски (null) в разных строках: {check['nulls_differ']}")
            if check["too_far"]:  # Есть значения вне допуска — записываем проблему.
                problems.append(f"колонка {col}: {check['too_far']} значений вне допуска (макс. разница {check['max_diff']:.3g})")
        elif not a.cast(pl.String).equals(b.cast(pl.String)):  # Нечисловые колонки (строки, даты) сравниваем как текст, точно.
            problems.append(f"колонка {col}: значения не совпадают")
    return problems  # Пустой список означает полное совпадение.
