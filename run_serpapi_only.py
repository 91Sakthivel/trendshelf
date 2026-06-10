"""Run collect_serpapi() in isolation."""
import sys
sys.path.insert(0, '.')
from collect_apis import collect_serpapi
ok = collect_serpapi()
sys.exit(0 if ok else 1)
