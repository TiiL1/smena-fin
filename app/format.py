def format_money(amount: float) -> str:
    rounded = round(amount)
    sign = "\u2212" if rounded < 0 else ""  # minus sign, matches frontend
    grouped = f"{abs(rounded):,}".replace(",", " ")
    return f"{sign}{grouped} \u20b8"
