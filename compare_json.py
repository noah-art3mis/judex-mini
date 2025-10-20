#!/usr/bin/env python3
"""
Compare generated JSON output with ground truth
"""
import json
from typing import Any, Dict


def load_json(filepath: str) -> Any:
    """Load JSON file"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def compare_structures(ground_truth: Dict[str, Any], generated: Dict[str, Any]) -> None:
    """Compare the structure and content of two JSON objects"""

    print("=" * 80)
    print("JSON COMPARISON REPORT")
    print("=" * 80)

    # Get keys from both
    gt_keys = set(ground_truth.keys())
    gen_keys = set(generated.keys())

    print("\n📊 STRUCTURE COMPARISON:")
    print(f"Ground Truth keys: {len(gt_keys)}")
    print(f"Generated keys: {len(gen_keys)}")

    # Find differences
    only_in_gt = gt_keys - gen_keys
    only_in_gen = gen_keys - gt_keys
    common_keys = gt_keys & gen_keys

    print("\n🔍 KEY ANALYSIS:")
    print(f"Common keys: {len(common_keys)}")
    print(f"Only in Ground Truth: {len(only_in_gt)}")
    print(f"Only in Generated: {len(only_in_gen)}")

    if only_in_gt:
        print(f"\n❌ Missing in Generated: {sorted(only_in_gt)}")

    if only_in_gen:
        print(f"\n➕ Extra in Generated: {sorted(only_in_gen)}")

    print(f"\n✅ Common fields: {sorted(common_keys)}")

    # Compare common fields
    print("\n📋 FIELD COMPARISON:")
    for key in sorted(common_keys):
        gt_val = ground_truth[key]
        gen_val = generated[key]

        print(f"\n🔸 {key}:")
        print(
            f"   Ground Truth: {type(gt_val).__name__} = {str(gt_val)[:100]}{'...' if len(str(gt_val)) > 100 else ''}"
        )
        print(
            f"   Generated:    {type(gen_val).__name__} = {str(gen_val)[:100]}{'...' if len(str(gen_val)) > 100 else ''}"
        )

        # Check if values are similar
        if gt_val == gen_val:
            print("   ✅ MATCH")
        elif str(gt_val).strip() == str(gen_val).strip():
            print("   ⚠️  SIMILAR (whitespace difference)")
        else:
            print("   ❌ DIFFERENT")


def main():
    """Main comparison function"""
    try:
        # Load both files
        print("Loading files...")
        ground_truth = load_json("tests/ground_truth/RE_1234567.json")[
            0
        ]  # Get first item
        generated = load_json("output/judex-mini_RE_1234567-1234567.json")[
            0
        ]  # Get first item

        # Compare structures
        compare_structures(ground_truth, generated)

        print("\n" + "=" * 80)
        print("COMPARISON COMPLETE")
        print("=" * 80)

    except Exception as e:
        print(f"Error during comparison: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
