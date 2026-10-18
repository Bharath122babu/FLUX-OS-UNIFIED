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
        with open(spec_path, 'r') as f:
            spec = json.load(f)
    except Exception as e:
        sys.exit(1)

    result_key = spec.get("result_key", "result")
    label = spec.get("label", "")
    decimals = spec.get("decimals", 0)
    
    # Determine mode: command line argument takes precedence if provided, 
    # but the prompt says "In mode json... in mode labelled... in mode fixed...".
    # It doesn't explicitly say how mode is passed. 
    # Usually, if it's a CLI, it's an argument.
    # Let's re-read: "In mode json emit... in mode labelled emit... in mode fixed emit..."
    # It doesn't say the mode is in the spec, but it's common.
    # Wait, the spec has a "mode" key. Let's check if I should use the spec's mode or an argument.
    # "In mode json... in mode labelled... in mode fixed..." 
    # If I use argparse, I can allow overriding.
    
    # Let's check the spec again.
    # {"decimals":2,"label":"total","mode":"labelled","result_key":"result"}
    # The spec has a mode.
    
    mode = args.mode if args.mode else spec.get("mode")

    # Read stdin
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
        # If val is a dict/list, use sort_keys=True
        if isinstance(val, (dict, list)):
            print(json.dumps(val, sort_keys=True, separators=(',', ':')))
        else:
            print(json.dumps(val, separators=(',', ':')))
    elif mode == "labelled":
        # emit label + "=" + the compact JSON value
        if isinstance(val, (dict, list)):
            json_val = json.dumps(val, sort_keys=True, separators=(',', ':'))
        else:
            json_val = json.dumps(val, separators=(',', ':'))
        print(f"{label}={json_val}")
    elif mode == "fixed":
        # emit the numeric value with decimals decimal places
        try:
            print(f"{float(val):.{decimals}f}")
        except (ValueError, TypeError):
            sys.exit(1)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
