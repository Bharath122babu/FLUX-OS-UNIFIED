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
        # The prompt says "load formatter_spec.json", implying it exists.
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
    try:
        value = input_data[result_key]
    except KeyError:
        sys.exit(1)

    if mode == 'json':
        # Emit the extracted value as compact sorted-key JSON
        # If the value is a dict, we should ensure keys are sorted.
        # json.dumps with sort_keys=True handles this.
        output = json.dumps(value, sort_keys=True, separators=(',', ':'))
        sys.stdout.write(output + '\n')

    elif mode == 'labelled':
        # Emit label + "=" + the compact JSON value
        output = json.dumps(value, sort_keys=True, separators=(',', ':'))
        sys.stdout.write(f"{label}={output}\n")

    elif mode == 'fixed':
        # Emit the numeric value with decimals decimal places
        try:
            # Ensure it's a number
            num_value = float(value)
            # Format with specified decimals
            output = f"{num_value:.{decimals}f}"
            sys.stdout.write(output + '\n')
        except (ValueError, TypeError):
            sys.exit(1)
    else:
        # If mode is unknown, the prompt doesn't specify, but let's assume no output or error
        sys.exit(1)

if __name__ == "__main__":
    main()
