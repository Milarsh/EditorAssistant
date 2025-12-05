_CYR_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

def slugify_code(value: str) -> str:
    value = (value or "").strip().lower()
    result = []
    prev_dash = False

    for ch in value:
        if ch in _CYR_MAP:
            repl = _CYR_MAP[ch]
        elif ch.isalnum():
            repl = ch
        else:
            repl = "-"

        for rc in repl:
            if rc == "-":
                if not prev_dash and result:
                    result.append("-")
                prev_dash = True
            else:
                result.append(rc)
                prev_dash = False

    slug = "".join(result).strip("-")
    return slug or "item"
