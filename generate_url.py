#!/usr/bin/env python3
"""
RestoSuite Exam URL Generator
Usage: python3 generate_url.py [options]

Options:
  --module MODULE     Module filter (all, KDS, POS, Marketing, Supply Chain, Singapore/Malaysia Localization)
  --difficulty DIFF   Difficulty filter (all, L1, L2, L3)
  --questions N       Number of questions (default: 20)
  --duration M        Exam duration in minutes (default: 30)
  --pass-rate P       Pass rate percentage (default: 80)
"""

import urllib.request
import urllib.parse
import json
import sys

BASE_URL = "http://localhost:8500"

def generate_exam_url(module="all", difficulty="all", num_questions=20, duration_minutes=30, pass_rate=80.0):
    params = urllib.parse.urlencode({
        "module": module,
        "difficulty": difficulty,
        "num_questions": num_questions,
        "duration_minutes": duration_minutes,
        "pass_rate": pass_rate
    })
    
    url = f"{BASE_URL}/generate-exam?{params}"
    
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate RestoSuite Exam URL")
    parser.add_argument("--module", default="all", help="Module filter")
    parser.add_argument("--difficulty", default="all", help="Difficulty filter (L1, L2, L3)")
    parser.add_argument("--questions", type=int, default=20, help="Number of questions")
    parser.add_argument("--duration", type=int, default=30, help="Exam duration in minutes")
    parser.add_argument("--pass-rate", type=float, default=80.0, help="Pass rate percentage")
    
    args = parser.parse_args()
    
    result = generate_exam_url(
        module=args.module,
        difficulty=args.difficulty,
        num_questions=args.questions,
        duration_minutes=args.duration,
        pass_rate=args.pass_rate
    )
    
    print("\n" + "="*60)
    print("📝 RestoSuite Exam URL Generated")
    print("="*60)
    print(f"🔗 Exam URL: {result['full_url']}")
    print(f"📦 Module: {result.get('module', 'all')}")
    print(f"📊 Difficulty: {result.get('difficulty', 'all')}")
    print(f"❓ Questions: {result['num_questions']}")
    print(f"⏱️  Duration: {result['duration_minutes']} minutes")
    print(f"✅ Pass Rate: {result['pass_rate']}%")
    print(f"⏰ Expires: {result['expires_at']}")
    print("="*60)

if __name__ == "__main__":
    main()
