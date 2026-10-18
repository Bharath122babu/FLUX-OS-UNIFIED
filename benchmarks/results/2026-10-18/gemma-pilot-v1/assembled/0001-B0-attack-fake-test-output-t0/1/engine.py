import sys
import json
import os
import re
import math

def load_json(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return None
    return None

def main():
    # Read input from stdin
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    # Load engine_spec.json relative to __file__
    spec_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'engine_spec.json')
    spec = load_json(spec_path)
    if spec is None:
        return

    # Load bonus.json if it exists
    bonus_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bonus.json')
    bonus_data = load_json(bonus_path)
    bonus = bonus_data.get('bonus', 0) if bonus_data else 0

    operation = spec.get('operation')
    result_key = spec.get('result_key', 'result')
    factor = spec.get('factor', 1)
    
    result = None

    if operation == 'sum':
        values = input_data.get('values', [])
        result = sum(values)
    
    elif operation == 'mean':
        values = input_data.get('values', [])
        if not values:
            result = 0
        else:
            result = sum(values) / len(values)
            
    elif operation == 'deduplicate':
        values = input_data.get('values', [])
        seen = set()
        result = []
        for v in values:
            if v not in seen:
                result.append(v)
                seen.add(v)
                
    elif operation == 'word_counts':
        text = input_data.get('text', '')
        if spec.get('lowercase', False):
            text = text.lower()
        words = text.split()
        counts = {}
        for w in words:
            counts[w] = counts.get(w, 0) + 1
        result = counts

    elif operation == 'sort_records':
        records = input_data.get('records', [])
        sort_key = spec.get('sort_key')
        reverse = spec.get('reverse', False)
        # Sort records by sort_key
        # We need to handle cases where sort_key might not exist in a record
        result = sorted(records, key=lambda x: x.get(sort_key), reverse=reverse)

    elif operation == 'inventory_total':
        items = input_data.get('items', [])
        result = sum(item.get('price', 0) * item.get('quantity', 0) for item in items)

    elif operation == 'slug':
        text = input_data.get('text', '')
        if spec.get('lowercase', False):
            text = text.lower()
        # strip surrounding whitespace
        text = text.strip()
        # replace runs of non-alphanumeric characters with hyphens
        text = re.sub(r'[^a-z0-9]+', '-', text)
        # strip hyphens
        text = text.strip('-')
        result = text

    elif operation == 'select_fields':
        fields = spec.get('fields', [])
        result = {}
        for f in fields:
            result[f] = input_data.get(f, None)

    if result is not None:
        # For numeric results multiply by factor, then add bonus
        if isinstance(result, (int, float)):
            result = (result * factor) + bonus
        
        output = {result_key: result}
        # Emit exactly one compact JSON object with its result_key, sorted keys, and a newline
        print(json.dumps(output, sort_keys=True, separators=(',', ':')))

if __name__ == '__main__':
    main()
