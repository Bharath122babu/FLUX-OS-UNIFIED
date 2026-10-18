import sys
import json
import os
import argparse

def main():
    parser = argparse.ArgumentParser(description="Standalone JSON formatter CLI.")
    parser.add_argument("--mode", choices=["json", "labelled", "fixed"], help="Output mode")
    args = parser.parse_args()

    # Load spec
    spec_path = os.path.join(os.path.dirname(__file__), "formatter_spec.json")
    try:
        with open(spec_path, "r") as f:
            spec = json.load(f)
    except Exception as e:
        sys.exit(f"Error loading spec: {e}")

    # Determine mode from args or spec
    mode = args.mode if args.mode else spec.get("mode", "json")
    result_key = spec.get("result_key", "result")
    decimals = spec.get("decimals", 2)
    label = spec.get("label", "")

    # Read input from stdin
    try:
        input_data = sys.stdin.read()
        if not input_data.strip():
            return
        data = json.loads(input_data)
    except Exception as e:
        sys.exit(f"Error reading/parsing input: {e}")

    # Extract value
    if result_key not in data:
        sys.exit(f"Key '{result_key}' not found in input data")
    
    value = data[result_key]

    # Format output
    if mode == "json":
        # Compact sorted-key JSON
        # Note: if value is a primitive, json.dumps still works.
        # If it's a dict/list, we need to ensure it's compact and sorted.
        # The requirement says "emit the extracted value as compact sorted-key JSON"
        # This usually implies if it's a dict.
        output = json.dumps(value, sort_keys=True, separators=(',', ':'))
        print(output)

    elif mode == "labelled":
        # label + "=" + the compact JSON value
        compact_json = json.dumps(value, sort_keys=True, separators=(',', ':'))
        print(f"{label}={compact_json}")

    elif mode == "fixed":
        # emit the numeric value with decimals decimal places
        try:
            # Ensure it's a number
            num_value = float(value)
            format_str = f"{{:.{decimals}f}}"
            print(format_str.format(num_value))
        except (ValueError, TypeError):
            sys.exit(f"Error: Value '{value}' is not numeric for 'fixed' mode")

if __name__ == "__main__":
    main()
