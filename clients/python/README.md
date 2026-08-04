# lolm_client (Python)

Stdlib-only client for the LOLM public API.

```bash
# from repo
export PYTHONPATH=clients/python
python -c '
from lolm_client import LOLM
c = LOLM()
print(c.usage())
# key = c.create_key(tier="free", label="ci")
# c = LOLM(api_key=key["api_key"])
r = c.run_code_collect("print(42) from main.py and run it")
print(r["done"])
'
```

Headers: `X-LOLM-Api-Key`, `X-LOLM-License`, `X-Workspace-Owner`  
Docs: https://lolm.imagineqira.com/developers.html
