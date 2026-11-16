"""What every test runs with, set before any test file imports the app's modules.

- SERAPH_TESTS=1: secret_vault.py never reads the vault (the system keyring and AWS Secrets Manager), so the tests run
  on this computer the way they run in CI, where there is none.
- GITHUB_TOKEN: a placeholder when there is no token, so token_balancer.py can make its balancer at import, like CI's
  .env does. It is never sent anywhere: no test reaches GitHub.
"""

import os

os.environ["SERAPH_TESTS"] = "1"
os.environ.setdefault("GITHUB_TOKEN", "placeholder")
