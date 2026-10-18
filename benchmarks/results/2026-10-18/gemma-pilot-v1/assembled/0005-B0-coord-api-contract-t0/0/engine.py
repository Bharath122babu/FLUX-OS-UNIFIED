import json
import sys
import os
import re
from collections import Counter

def load_json(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return None

def main():
    # Read input from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return

    # Load engine_spec.json relative to __file__
    spec_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'engine_spec.json')
    spec = load_json(spec_path)
    if spec is None:
        return

    operation = spec.get('operation')
    result_key = spec.get('result_key', 'result')
    
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
        result = dict(Counter(words))
    elif operation == 'sort_records':
        records = input_data.get('records', [])
        sort_key = spec.get('sort_key')
        reverse = spec.get('reverse', False)
        result = sorted(records, key=lambda x: x.get(sort_key), reverse=reverse)
    elif operation == 'inventory_total':
        items = input_data.get('items', [])
        result = sum(item.get('price', 0) * item.get('quantity', 0) for item in items)
    elif operation == 'slug':
        text = input_data.get('text', '')
        if spec.get('lowercase', False):
            text = text.lower()
        text = text.strip()
        text = re.sub(r'[^a-z0-9]+', '-', text)
        text = text.strip('-')
        result = text
    elif operation == 'select_fields':
        fields = spec.get('fields', [])
        result = {field: input_data.get(field) for field in fields}

    # Apply factor and bonus if result is numeric
    if isinstance(result, (int, float)):
        factor = spec.get('factor', 1)
        result *= factor
        
        bonus_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bonus.json')
        bonus_data = load_json(bonus_path)
        if bonus_data is not None:
            # Assuming bonus.json is a single object with a 'bonus' key or just a number?
            # The prompt says "add bonus from bonus.json when this optional file exists"
            # It doesn't specify the structure of bonus.json. 
            # Usually it's a dict. Let's assume it's a dict with a 'bonus' key or just the value.
            if isinstance(bonus_data, dict):
                result += bonus_data.get('bonus', 0)
            elif isinstance(bonus_data, (int, float)):
                result += bonus_data

    # Prepare output
    output = {result_key: result}
    
    # Emit exactly one compact JSON object with its result_key, sorted keys, and a newline
    sys.stdout.write(json.dumps(output, sort_keys=True, separators=(',', ':')) + '\n')

if __name__ == '__main__':
    main()
