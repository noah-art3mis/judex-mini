#!/usr/bin/env python3
"""
Compare the actual content/data being extracted vs ground truth
Focus on data quality, not field names
"""
import json
from typing import Any, Dict, List

def load_json(filepath: str) -> Any:
    """Load JSON file"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def analyze_content_quality(ground_truth: Dict[str, Any], generated: Dict[str, Any]) -> None:
    """Analyze the quality and completeness of extracted content"""
    
    print("=" * 80)
    print("CONTENT QUALITY ANALYSIS")
    print("=" * 80)
    
    # Key data points to analyze
    critical_fields = {
        'incidente': 'Incident number',
        'data_protocolo': 'Protocol date', 
        'origem': 'Origin state',
        'relator': 'Judge/Rapporteur',
        'primeiro_autor': 'First author',
        'partes': 'Parties involved',
        'andamentos': 'Process steps',
        'deslocamentos': 'File movements',
        'assuntos': 'Subjects/topics'
    }
    
    print(f"\n🔍 CRITICAL DATA EXTRACTION ANALYSIS:")
    print("-" * 50)
    
    for field, description in critical_fields.items():
        print(f"\n📋 {description} ({field}):")
        
        # Try to find equivalent fields in generated data
        gt_val = ground_truth.get(field)
        
        # Map to generated field names
        gen_field_map = {
            'incidente': 'incidente',
            'data_protocolo': 'data_protocolo', 
            'origem': 'origem',
            'relator': 'relator',
            'primeiro_autor': 'primeiro_autor',
            'partes': 'partes_total',  # Different name in generated
            'andamentos': 'andamentos',
            'deslocamentos': 'deslocamentos',
            'assuntos': 'lista_assuntos'  # Different name in generated
        }
        
        gen_field = gen_field_map.get(field, field)
        gen_val = generated.get(gen_field)
        
        # Analyze content quality
        if gt_val is None and gen_val is None:
            print(f"   ✅ Both missing (expected)")
        elif gt_val is None and gen_val is not None:
            print(f"   ⚠️  Ground truth missing, but extracted: {str(gen_val)[:50]}...")
        elif gt_val is not None and gen_val is None:
            print(f"   ❌ MISSING: Should be '{gt_val}' but got None")
        elif gt_val == gen_val:
            print(f"   ✅ PERFECT MATCH: '{gt_val}'")
        elif str(gt_val).strip() == str(gen_val).strip():
            print(f"   ✅ MATCH (whitespace): '{gt_val}'")
        else:
            print(f"   ⚠️  DIFFERENT:")
            print(f"      Expected: {gt_val}")
            print(f"      Got:      {gen_val}")
    
    # Analyze list/array data quality
    print(f"\n📊 ARRAY DATA ANALYSIS:")
    print("-" * 50)
    
    array_fields = ['andamentos', 'deslocamentos', 'partes']
    for field in array_fields:
        gt_field = field
        gen_field = 'partes_total' if field == 'partes' else field
        
        gt_list = ground_truth.get(gt_field, [])
        gen_list = generated.get(gen_field, [])
        
        print(f"\n🔸 {field.upper()}:")
        print(f"   Ground Truth: {len(gt_list)} items")
        print(f"   Generated:     {len(gen_list)} items")
        
        if len(gt_list) == 0 and len(gen_list) == 0:
            print(f"   ✅ Both empty (expected)")
        elif len(gt_list) == len(gen_list):
            print(f"   ✅ Same count: {len(gt_list)} items")
        else:
            print(f"   ⚠️  Count mismatch: GT={len(gt_list)}, Gen={len(gen_list)}")
        
        # Show sample items if available
        if len(gt_list) > 0:
            print(f"   GT Sample: {gt_list[0]}")
        if len(gen_list) > 0:
            print(f"   Gen Sample: {gen_list[0]}")

def main():
    """Main content analysis function"""
    try:
        print("Loading files...")
        ground_truth = load_json("tests/ground_truth/RE_1234567.json")[0]
        generated = load_json("output/judex-mini_RE_1234567-1234567.json")[0]
        
        analyze_content_quality(ground_truth, generated)
        
        print(f"\n" + "=" * 80)
        print("CONTENT ANALYSIS COMPLETE")
        print("=" * 80)
        
    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
