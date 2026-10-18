import json
import sys
import os
import re
from pathlib import Path

def main():
    # Read input from stdin
    try:
        input_data = sys.stdin.read()
        if not input_data.strip():
            return
        data = json.loads(input_data)
    except Exception:
        return

    # Load engine_spec.json
    spec_path = Path(__file__).parent / "engine_spec.json"
    spec = {}
    if spec_path.exists():
        with open(spec_path, 'r') as f:
            spec = json.load(f)

    operation = spec.get("operation")
    result_key = spec.get("result_key", "result")
    
    result = None

    if operation == "sum":
        values = data.get("values", [])
        result = sum(values)
    elif operation == "mean":
        values = data.get("values", [])
        if not values:
            result = 0
        else:
            result = sum(values) / len(values)
    elif operation == "deduplicate":
        values = data.get("values", [])
        seen = set()
        result = []
        for v in values:
            if v not in seen:
                result.append(v)
                seen.add(v)
    elif operation == "word_counts":
        text = data.get("text", "")
        if spec.get("lowercase", False):
            text = text.lower()
        words = text.split()
        counts = {}
        for w in words:
            counts[w] = counts.get(w, 0) + 1
        result = counts
    elif operation == "sort_records":
        records = data.get("records", [])
        sort_key = spec.get("sort_key")
        reverse = spec.get("reverse", False)
        try:
            result = sorted(records, key=lambda x: x.get(sort_key), reverse=reverse)
        except Exception:
            result = records
    elif operation == "inventory_total":
        items = data.get("items", [])
        result = sum(item.get("price", 0) * item.get("quantity", 0) for item in items)
    elif operation == "slug":
        text = data.get("text", "")
        text = text.strip().lower()
        text = re.sub(r'[^a-z0-9]+', '-', text)
        text = text.strip('-')
        result = text
    elif operation == "select_fields":
        fields = spec.get("fields", [])
        result = {}
        for f in fields:
            result[f] = data.get(f, None)

    if result is not None:
        # Apply factor and bonus if result is numeric
        if isinstance(result, (int, float)):
            factor = spec.get("factor", 1)
            result *= factor
            
            bonus_path = Path(__file__).parent / "bonus.json"
            if bonus_path.exists():
                try:
                    with open(bonus_path, 'r') as f:
                        bonus_data = json.load(f)
                        result += bonus_data.get("bonus", 0)
                except Exception:
                    pass

        output = {result_key: result}
        sys.stdout.write(json.dumps(output, sort_keys=True) + "\n")

if __name__ == "__main__":
    main()
