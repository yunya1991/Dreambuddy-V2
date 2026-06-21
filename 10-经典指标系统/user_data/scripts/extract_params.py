import sys
import json
import os

def main():
    if len(sys.argv) != 4:
        print("Usage: python extract_params.py <input_json> <output_json> <label>")
        print("Example: python extract_params.py temp.json params_low.json low")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    label = sys.argv[3]

    if not os.path.exists(input_path):
        print(f"Error: Input file {input_path} not found.")
        sys.exit(1)

    with open(input_path, 'r') as f:
        data = json.load(f)

    # Inject label for tracking
    data['volatility_bucket'] = label
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=4)
    
    print(f"Processed parameters for '{label}' and saved to {output_path}")

if __name__ == "__main__":
    main()
