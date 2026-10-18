import json
import sys
import os
import argparse

def main():
    parser = argparse.ArgumentParser(description="Format JSON output based on a specification.")
    parser.add_argument("--mode", choices=["json", "labelled", "fixed"], help="Override the mode from the spec.")
    args = parser.parse_args()

    # Load spec
    spec_path = os.path.join(os.path.dirname(__file__), "formatter_spec.json")
    try:
        with open(spec_path, "r") as f:
            spec = json.load(f)
    except Exception as e:
        sys.stderr.write(f"Error loading spec: {e}\n")
        sys.exit(1)

    # Read input from stdin
    try:
        input_data = json.load(sys.stdin)
    except Exception as e:
        sys.stderr.write(f"Error reading stdin: {e}\n")
        sys.exit(1)

    # Extract configuration
    mode = args.mode if args.mode else spec.get("mode", "json")
    result_key = spec.get("result_key", "result")
    label = spec.get("label", "")
    decimals = spec.get("decimals", 0)

    # Extract value
    if result_key not in input_data:
        sys.stderr.write(f"Key '{result_key}' not found in input.\n")
        sys.exit(1)
    
    value = input_data[result_key]

    # Formatting logic
    if mode == "json":
        # Compact sorted-key JSON
        output = json.dumps(value, sort_keys=True, separators=(',', ':'))
        print(output)
    elif mode == "labelled":
        # label + "=" + compact JSON value
        output = json.dumps(value, sort_keys=True, separators=(',', ':'))
        print(f"{label}={output}")
    elif mode == "fixed":
        # numeric value with decimals decimal places
        try:
            # Ensure it's a number
            num_value = float(value)
            # Format with specified decimals
            format_str = f"{{:.{decimals}f}}"
            print(format_str.format(num_value))
        except (ValueError, TypeError):
            sys.stderr.write(f"Value '{value}' is not a number for 'fixed' mode.\n")
            sys.exit(1)

if __name__ == "__main__":
    main()
