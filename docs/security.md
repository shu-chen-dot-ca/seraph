# Security

- **Agents have no host access.** They get no shell, no files and no web access on your computer. They only have Seraph's tools: reading GitHub, the lists, drafts, and their VM desktop. Everything they run, runs in a VM.
- **Tokens live in [AWS Secrets Manager](#secrets-in-aws-secrets-manager)**, or on your computer (`.env`, and `data/github_account.json` with mode 600) until you move them. They never reach the browser, an agent or a VM. Seraph clones code on your computer and copies it into the VM.
- **What's sent is what you reviewed.** A pull request is rebuilt on your computer, from the reviewed diff and the project's files on GitHub. Diffs that contain a secret are refused.
- **Secret values stay hidden from agents.** Environment variables you set for the VMs are written into them. Agents see only their names, and any value that shows up in an agent's output is replaced with `[hidden]`.
- **Only you can reach the app.** The backend listens on 127.0.0.1 only, and checks the Host and Origin of every request.
- **Text from GitHub is never treated as instructions.** One-shot judgments, such as issue checks, review tone and AI policy, run with no tools at all.
- **VMs can't reach your computer or your network.** See [setup](setup.md#1-incus).

## Secrets in AWS Secrets Manager

**Settings → Secrets → Move secrets** moves every secret off your computer: the search tokens, the agents' Claude login, your GitHub sign-in and the sign-in app's client secret. They become one secret, `seraph/secrets`, and Seraph reads it when it starts and keeps the values in memory only. If AWS can't be reached, Seraph doesn't start. Nothing falls back to disk.

The only key left on your computer is the AWS access key that reads the secret. It is kept in the system keyring (GNOME Keyring, unlocked when you log in), not in a file. Give it to an IAM user that can do nothing else:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue", "secretsmanager:CreateSecret", "secretsmanager:DescribeSecret"],
    "Resource": "arn:aws:secretsmanager:*:<account-id>:secret:seraph/*"
  }]
}
```

To change a token, edit it in the AWS console (**Open in AWS** on Settings → Secrets), then restart Seraph. `./run.sh` and `./live.sh` each have their own `.env`, so run **Move secrets** from both.
