"""Run only the Google Trends collector from collect_apis.py."""
import sys
sys.path.insert(0, '.')
import collect_apis

ok = collect_apis.collect_google_trends()
print(f"\nResult: {'PASS' if ok else 'FAIL'}")
