"""Chinese text processing utilities."""

import re


def count_chinese_chars(text: str) -> int:
    """Count Chinese characters in text (excludes punctuation, spaces, and non-CJK)."""
    cjk_pattern = re.compile(r"[一-鿿㐀-䶿\U00020000-\U0002a6df]")
    return len(cjk_pattern.findall(text))


def count_words_cn(text: str) -> int:
    """Estimate word count for Chinese text.

    Chinese "word count" is typically character count for web novel platforms.
    This counts all Chinese characters + treats each English word as one.
    """
    # Count CJK characters
    cjk = count_chinese_chars(text)
    # Count English words
    english = len(re.findall(r"[a-zA-Z]+", text))
    # Count numbers as one "word" each
    numbers = len(re.findall(r"\d+", text))
    return cjk + english + numbers


def split_paragraphs(text: str, max_lines: int = 5) -> list[str]:
    """Split text into paragraphs suitable for web novel reading.

    Ensures no paragraph is too long (max_lines heuristic).
    """
    paragraphs = text.strip().split("\n")
    result = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # If paragraph is very long, split at sentence boundaries
        if len(para) > 200:
            sentences = re.split(r"(?<=[。！？…])", para)
            current = ""
            for sent in sentences:
                if len(current) + len(sent) < 200:
                    current += sent
                else:
                    if current:
                        result.append(current)
                    current = sent
            if current:
                result.append(current)
        else:
            result.append(para)
    return result


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    # Remove characters invalid in Windows filenames
    invalid = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid, "_", name)
    # Collapse multiple underscores/spaces
    sanitized = re.sub(r"[_\s]+", "_", sanitized)
    # Trim and limit length
    return sanitized.strip("_")[:200]


def extract_dialogue_ratio(text: str) -> float:
    """Estimate the dialogue ratio in text (0.0-1.0).

    Dialogue is identified by Chinese/English quotation marks.
    """
    if not text:
        return 0.0

    total = len(text)
    dialogue_pattern = re.compile(
        r'["""][^"""]+?["""]|'  # Chinese double quotes
        r"[''][^'']+?['']|"      # Chinese single quotes
        r'"[^"]+?"|'              # English double quotes
        r"'[^']+?'"               # English single quotes
    )
    dialogue_chars = sum(len(m.group()) for m in dialogue_pattern.finditer(text))
    return min(1.0, dialogue_chars / max(1, total))


def safe_parse_json(text: str) -> dict:
    """Robust JSON parsing that handles LLM outputs with extra text or truncation.

    Tries multiple strategies in order:
    1. Direct json.loads()
    2. raw_decode() to find first complete JSON object
    3. Repair truncated JSON by closing unclosed braces/strings
    """
    if not text or not text.strip():
        raise ValueError("Empty text provided for JSON parsing")

    text = text.strip()

    # Remove markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
    if text.endswith("```"):
        text = text[: text.rfind("```")].strip()

    import json
    import re

    errors = []

    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        errors.append(f"S1: {e}")

    # Strategy 2: raw_decode — find first complete JSON object
    match = re.search(r"[\{\[]", text)
    if match:
        decoder = json.JSONDecoder()
        try:
            obj, end_idx = decoder.raw_decode(text, match.start())
            return obj
        except json.JSONDecodeError as e:
            errors.append(f"S2@{match.start()}: {e}")

    # Strategy 3: Repair truncated JSON
    repaired = _repair_truncated_json(text)
    if repaired:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            errors.append(f"S3: {e}")

    # Strategy 4: Extract text between first { and last }, try parsing
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace >= 0 and last_brace > first_brace:
        extracted = text[first_brace:last_brace + 1]
        # Fix common LLM JSON issues
        extracted = _fix_common_json_issues(extracted)
        try:
            return json.loads(extracted)
        except json.JSONDecodeError as e:
            errors.append(f"S4@{e.pos}: {e}")

    # Strategy 5: Truncation recovery
    repaired = _salvage_truncated_array(text)
    if repaired:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            errors.append(f"S5: {e}")

    # Strategy 6: Clean and try parsing from every { position
    cleaned = _fix_common_json_issues(text)
    json_re = re.compile(r'\{')
    for m in json_re.finditer(cleaned):
        candidate = cleaned[m.start():]
        try:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(candidate)
            return obj
        except json.JSONDecodeError:
            continue

    # Strategy 7: Aggressive — find outermost { ... }, strip everything else
    first = text.find('{')
    last = text.rfind('}')
    if first >= 0 and last > first:
        core = text[first:last + 1]
        core = _fix_common_json_issues(core)
        # Try to fix unmatched braces by cutting from the end
        for cut in range(len(core), first, -50):
            candidate = core[:cut]
            # Close any open structures
            depth = 0
            in_str = False
            esc = False
            for ch in candidate:
                if esc: esc = False; continue
                if ch == '\\': esc = True; continue
                if ch == '"': in_str = not in_str; continue
                if in_str: continue
                if ch in '{[': depth += 1
                elif ch in '}]': depth -= 1
            suffix = ''
            for _ in range(depth):
                suffix += '}'
            candidate += suffix
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    raise ValueError(
        f"Failed to parse JSON after {len(errors)} attempts. "
        f"Errors: {'; '.join(errors[-3:])}. "
        f"Text ends with: ...{text[-200:]}"
    )


def _fix_common_json_issues(text: str) -> str:
    """Fix common JSON formatting issues from LLM outputs."""
    import re

    # Remove any BOM or zero-width characters
    text = text.replace('﻿', '').replace('​', '').replace('‌', '').replace('‍', '')

    # Strip control characters (except \n, \r, \t which are valid in JSON strings)
    # But they cause issues inside JSON strings — replace with space
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', ' ', text)

    # Remove trailing commas before ] or } (most common LLM JSON error)
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Remove trailing comma at end of text
    text = re.sub(r',\s*$', '', text)

    # Fix unescaped newlines inside string values
    # (JSON spec doesn't allow literal newlines in strings)
    text = _fix_newlines_in_strings(text)

    return text


def _fix_newlines_in_strings(text: str) -> str:
    """Replace literal newlines within JSON string values with \\n."""
    import re
    result = []
    in_string = False
    escape_next = False
    i = 0
    while i < len(text):
        ch = text[i]
        if escape_next:
            result.append(ch)
            escape_next = False
            i += 1
            continue
        if ch == '\\':
            result.append(ch)
            escape_next = True
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue
        if in_string and ch == '\n':
            result.append('\\n')
            i += 1
            continue
        if in_string and ch == '\r':
            if i + 1 < len(text) and text[i + 1] == '\n':
                i += 1
            result.append('\\n')
            i += 1
            continue
        if in_string and ch == '\t':
            result.append('\\t')
            i += 1
            continue
        result.append(ch)
        i += 1
    return ''.join(result)


def _repair_truncated_json(text: str) -> str | None:
    """Attempt to repair JSON truncated by max_tokens limit.

    Closes unclosed strings, arrays, and objects.
    """
    import re

    # Find the start of JSON
    start_match = re.search(r"[\{\[]", text)
    if not start_match:
        return None

    json_text = text[start_match.start():]

    # Count braces/brackets to detect truncation
    depth = 0
    in_string = False
    escape_next = False

    for i, ch in enumerate(json_text):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in '{[':
            depth += 1
        elif ch in '}]':
            depth -= 1

    if depth <= 0:
        return None  # Not truncated — already balanced

    # Try to repair: close the unclosed string if any, then close all open braces
    repaired = json_text

    # If we're inside a string, close it
    if in_string:
        repaired += '"'

    # Close any open structures
    # Count actual opens vs closes to know what to close
    opens = []
    in_str = False
    esc = False
    for ch in repaired:
        if esc:
            esc = False; continue
        if ch == '\\':
            esc = True; continue
        if ch == '"' and not esc:
            in_str = not in_str; continue
        if in_str:
            continue
        if ch in '{[':
            opens.append(ch)
        elif ch in '}]':
            if opens:
                expected = '[' if ch == ']' else '{'
                if opens[-1] == expected:
                    opens.pop()

    # Close remaining open structures
    for ch in reversed(opens):
        repaired += ']' if ch == '[' else '}'

    return repaired


def _salvage_truncated_array(text: str) -> str | None:
    """Attempt to salvage JSON truncated mid-stream by truncating to the last
    complete element in the deepest/largest array.

    For example, if Claude output was:
      {"chapters": [{"number":1,...}, {"number":2,...}, {"num
    This function will return:
      {"chapters": [{"number":1,...}, {"number":2,...}]}
    """
    import json
    import re

    # Find the opening of the main JSON object
    start = text.find('{')
    if start < 0:
        return None

    # Walk the JSON character by character, tracking:
    # - String state (in/out)
    # - Depth stack of { and [
    # - Positions of complete } that close a { at the object root
    # - Last position where depth[] hit 0 (complete array element)

    depth = 0         # combined {} and [] depth
    in_string = False
    escape_next = False
    last_safe_pos = start  # last position where we had a complete state

    # For array-aware recovery: track when we're inside an array and find
    # the last position where an array element completed (i.e., `},` pattern
    # at the right depth inside an array)
    last_element_end = start

    i = start
    while i < len(text):
        ch = text[i]

        if escape_next:
            escape_next = False
            i += 1
            continue

        if ch == '\\':
            escape_next = True
            i += 1
            continue

        if ch == '"':
            in_string = not in_string
            i += 1
            continue

        if in_string:
            i += 1
            continue

        if ch in '{[':
            depth += 1
        elif ch in '}]':
            depth -= 1
            # If we just closed a structure back to a safe level, mark position
            if depth >= 0:
                last_safe_pos = i + 1
                # Check if this looks like the end of an array element
                # Pattern: `},` or `}\n` or `} ]` after a closing brace
                remaining = text[i+1:i+3]
                if ch == '}' and depth >= 0:
                    # This could be end of an object element in an array
                    last_element_end = i + 1

        i += 1

    # If JSON is balanced, no repair needed
    if depth == 0 and not in_string:
        return None

    # Strategy: Truncate to the last complete array element, then close
    # the array and object properly

    # Find the text up to the last complete element end
    # Walk backward from last_element_end to find a clean cut point
    cut_pos = last_element_end

    # Ensure we cut at a clean boundary (after a comma or whitespace)
    while cut_pos < len(text) and cut_pos > start:
        ch_before = text[cut_pos - 1] if cut_pos > 0 else ''
        if ch_before in '} ]':
            # This is a valid cut point — after a closing brace/bracket
            break
        cut_pos -= 1

    if cut_pos <= start:
        return None

    # Build repaired JSON: keep everything up to cut_pos, then close
    prefix = text[start:cut_pos]

    # Remove trailing comma (common after an element in an array)
    prefix = prefix.rstrip()
    if prefix.endswith(','):
        prefix = prefix[:-1].rstrip()

    # Count opens vs closes in the prefix to build correct closing
    opens = []
    in_str = False
    esc = False
    for ch in prefix:
        if esc:
            esc = False; continue
        if ch == '\\':
            esc = True; continue
        if ch == '"':
            in_str = not in_str; continue
        if in_str:
            continue
        if ch in '{[':
            opens.append(ch)
        elif ch in '}]':
            if opens:
                expected = '[' if ch == ']' else '{'
                if opens and opens[-1] == expected:
                    opens.pop()

    # Build closing sequence
    suffix = ''
    for ch in reversed(opens):
        suffix += ']' if ch == '[' else '}'

    repaired = prefix + suffix
    return repaired


def extract_chapter_title(content: str) -> str | None:
    """Extract a chapter title from content if present.

    Looks for patterns like "第X章 标题" or "Chapter X: Title".
    """
    patterns = [
        r"第[一二三四五六七八九十百千\d]+章\s*[：:]*\s*(.+)",
        r"Chapter\s+\d+\s*[：:]*\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip()
    return None
