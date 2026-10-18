import sys
import json
import os
import argparse

def main():
    # Load formatter_spec.json relative to __file__
    spec_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'formatter_spec.json')
    
    try:
        with open(spec_path, 'r') as f:
            spec = json.load(f)
    except Exception as e:
        # If spec fails to load, we might want to exit or use defaults.
        # The prompt says "load formatter_spec.json", implying it should exist.
        sys.exit(1)

    result_key = spec.get('result_key', 'result')
    mode = spec.get('mode', 'json')
    decimals = spec.get('decimals', 0)
    label = spec.get('label', '')

    # Read one JSON object from stdin
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        sys.exit(1)

    # Extract the result
    if result_key not in input_data:
        sys.exit(1)
    
    value = input_data[result_key]

    if mode == 'json':
        # emit the extracted value as compact sorted-key JSON
        # Note: if value is a dict/list, we use sort_keys. If it's a primitive, sort_keys doesn't matter.
        output = json.dumps(value, sort_keys=True, separators=(',', ':'))
        print(output)

    elif mode == 'labelled':
        # emit label + "=" + the compact JSON value
        output = json.dumps(value, sort_keys=True, separators=(',', ':'))
        print(f"{label}={output}")

    elif mode == 'fixed':
        # emit the numeric value with decimals decimal places
        try:
            # Ensure it's a number
            num_value = float(value)
            # Format with specified decimals
            format_str = f"{{:.{decimals}f}}"
            print(format_str.format(num_value))
        except (ValueError, TypeError):
            sys.exit(1)
    else:
        # If mode is unknown, the prompt doesn't specify, but let's assume no output or error
        sys.exit(1)

if __name__ == "__main__":
    main()
