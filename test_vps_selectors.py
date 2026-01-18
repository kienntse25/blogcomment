#!/usr/bin/env python3
"""
Test script to verify comprehensive selectors are working on VPS
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.form_selectors import COMMENT_TEXTAREAS, NAME_INPUTS, EMAIL_INPUTS, SUBMIT_BUTTONS

def test_selectors():
    print("=== TESTING COMPREHENSIVE SELECTORS ===")
    print(f"COMMENT_TEXTAREAS: {len(COMMENT_TEXTAREAS)} selectors")
    print(f"NAME_INPUTS: {len(NAME_INPUTS)} selectors")
    print(f"EMAIL_INPUTS: {len(EMAIL_INPUTS)} selectors")
    print(f"SUBMIT_BUTTONS: {len(SUBMIT_BUTTONS)} selectors")

    print("\nFirst 5 COMMENT_TEXTAREAS:")
    for i, sel in enumerate(COMMENT_TEXTAREAS[:5]):
        print(f"  {i+1}. {sel}")

    print("\nFirst 5 NAME_INPUTS:")
    for i, sel in enumerate(NAME_INPUTS[:5]):
        print(f"  {i+1}. {sel}")

    print("\nFirst 5 EMAIL_INPUTS:")
    for i, sel in enumerate(EMAIL_INPUTS[:5]):
        print(f"  {i+1}. {sel}")

    print("\nFirst 5 SUBMIT_BUTTONS:")
    for i, sel in enumerate(SUBMIT_BUTTONS[:5]):
        print(f"  {i+1}. {sel}")

    # Test import in commenter.py
    try:
        from src.commenter import COMMENT_TEXTAREAS as CT_FROM_COMMENTER
        print(f"\n✓ commenter.py successfully imports COMMENT_TEXTAREAS: {len(CT_FROM_COMMENTER)} selectors")
    except ImportError as e:
        print(f"\n✗ commenter.py import failed: {e}")
        return False

    return True

if __name__ == "__main__":
    success = test_selectors()
    sys.exit(0 if success else 1)
