import sys
import json
import os
import argparse

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
        # If spec fails to load, we might want to exit or use defaults.
        # The prompt says "load formatter_spec.json relative to __file__".
        # It doesn't specify what to do if it fails, but usually we assume it exists.
        sys.exit(1)

    result_key = spec.get("result_key", "result")
    label = spec.get("label", "")
    decimals = spec.get("decimals", 0)
    
    # Determine mode: command line argument takes precedence if provided? 
    # The prompt says "In mode json emit... in mode labelled emit... in mode fixed emit...".
    # It doesn't explicitly say if the mode comes from the spec or CLI.
    # "In mode json..." usually implies the mode is a parameter.
    # Let's check if the spec has a mode. It does.
    # But usually CLI tools allow overriding.
    # Re-reading: "In mode json emit... in mode labelled emit... in mode fixed emit..."
    # It doesn't say "Use the mode from the spec".
    # However, it says "Extract its result_key (default result)".
    # It doesn't say "Extract its mode".
    # Let's assume the mode is passed via CLI.
    
    mode = args.mode if args.mode else spec.get("mode", "json")

    # Read input from stdin
    try:
        input_data = sys.stdin.read()
        if not input_data.strip():
            return
        data = json.loads(input_data)
    except Exception:
        sys.exit(1)

    # Extract value
    if result_key not in data:
        sys.exit(1)
    
    val = data[result_key]

    if mode == "json":
        # emit the extracted value as compact sorted-key JSON
        # If val is a dict/list, it should be sorted.
        # json.dumps(val, sort_keys=True, separators=(',', ':'))
        print(json.dumps(val, sort_keys=True, separators=(',', ':')))
    elif mode == "labelled":
        # emit label + "=" + the compact JSON value
        compact_json = json.dumps(val, sort_keys=True, separators=(',', ':'))
        print(f"{label}={compact_json}")
    elif mode == "fixed":
        # emit the numeric value with decimals decimal places
        try:
            # Ensure it's a number
            num = float(val)
            print(f"{num:.{decimals}f}")
        except (ValueError, TypeError):
            sys.exit(1)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
