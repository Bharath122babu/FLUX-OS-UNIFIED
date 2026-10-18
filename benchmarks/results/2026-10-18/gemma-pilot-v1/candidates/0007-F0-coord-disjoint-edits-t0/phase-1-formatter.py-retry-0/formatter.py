import sys
import json
import os
import argparse

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Formatter CLI")
    parser.add_argument("--mode", choices=["json", "labelled", "fixed"], help="Output mode")
    args = parser.parse_args()

    # Load formatter_spec.json relative to __file__
    spec_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "formatter_spec.json")
    try:
        with open(spec_path, 'r') as f:
            spec = json.load(f)
    except Exception as e:
        sys.exit(1)

    # Determine mode: command line arg takes precedence, otherwise use spec
    mode = args.mode if args.mode else spec.get("mode")
    result_key = spec.get("result_key", "result")
    decimals = spec.get("decimals")

    # Read JSON from stdin
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        sys.exit(1)

    # Extract the value
    value = input_data.get(result_key)

    # If value is None, we might want to handle it, but the spec implies it exists.
    # If value is not present, we'll just output nothing or handle as error.
    # Given the requirements, we assume the key exists.

    if mode == "json":
        # Emit the extracted value as compact sorted-key JSON
        # If the value is a dict, we sort keys. If it's a primitive, it's just the value.
        # json.dumps with sort_keys=True handles dicts.
        print(json.dumps(value, sort_keys=True, separators=(',', ':')))

    elif mode == "labelled":
        # Emit label + "=" + the compact JSON value
        label = spec.get("label", "")
        print(f"{label}={json.dumps(value, sort_keys=True, separators=(',', ':'))}")

    elif mode == "fixed":
        # Emit the numeric value with decimals decimal places
        if isinstance(value, (int, float)):
            if decimals is not None:
                print(f"{value:.{decimals}f}")
            else:
                print(value)
        else:
            # If it's not a number, fixed mode might not make sense, 
            # but we'll try to format it if possible or just print it.
            print(value)
    
    # The requirement says "Finish with exactly one newline."
    # print() already adds a newline.

if __name__ == "__main__":
    main()
