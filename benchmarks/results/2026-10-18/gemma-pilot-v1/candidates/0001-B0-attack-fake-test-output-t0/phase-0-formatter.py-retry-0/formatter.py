import json
import sys
import argparse
import os

def main():
    parser = argparse.ArgumentParser(description="Formatter CLI")
    parser.add_argument("--mode", choices=["json", "labelled", "fixed"], help="Output mode")
    args = parser.parse_args()

    # Load spec
    spec_path = os.path.join(os.path.dirname(__file__), "formatter_spec.json")
    try:
        with open(spec_path, "r") as f:
            spec = json.load(f)
    except Exception as e:
        sys.exit(1)

    # Read input from stdin
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        sys.exit(1)

    # Extract result_key
    result_key = spec.get("result_key", "result")
    value = input_data.get(result_key)

    # Determine mode: command line arg takes precedence over spec
    mode = args.mode if args.mode else spec.get("mode", "json")

    if mode == "json":
        # Emit extracted value as compact sorted-key JSON
        # If value is a dict/list, it should be sorted keys. 
        # json.dumps with sort_keys=True handles this.
        # If value is a primitive, it just prints it.
        print(json.dumps(value, sort_keys=True, separators=(',', ':')))

    elif mode == "labelled":
        # Emit label + "=" + the compact JSON value
        label = spec.get("label", "")
        compact_json = json.dumps(value, sort_keys=True, separators=(',', ':'))
        print(f"{label}={compact_json}")

    elif mode == "fixed":
        # Emit the numeric value with decimals decimal places
        decimals = spec.get("decimals", 0)
        try:
            # Ensure it's a number
            num_value = float(value)
            print(f"{num_value:.{decimals}f}")
        except (ValueError, TypeError):
            # If not a number, what should happen? 
            # The prompt says "emit the numeric value". 
            # If it's not numeric, it's undefined behavior, but let's try to print it as is or handle error.
            # Given the prompt, we assume it's numeric in fixed mode.
            sys.exit(1)

if __name__ == "__main__":
    main()
