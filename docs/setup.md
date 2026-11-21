# Setup

## Requirements

- **Linux with systemd.** Developed on Fedora 44.
- **[Incus](https://linuxcontainers.org/incus/) with KVM virtual machines.** Developed on Incus 6.23. Your user needs to be in the `incus-admin` group.
- **Python 3.14 with [uv](https://docs.astral.sh/uv/)**, and **Node.js 22+ with npm**.
- **Memory.** Each VM and each image build takes 8 GB, and Seraph always keeps 8 GB free.
- **A Claude Code token** for the agents. Make one with `claude setup-token`.
- **GitHub tokens for reading.** Read access to public repos is enough. More tokens, ideally from different accounts, make searches faster.

## 1. Incus

Seraph needs a bridge, `sandboxbr0`, that blocks traffic to your computer and your local network, and a profile, `sandbox`, that uses it:

```bash
incus network acl create sandbox-egress
incus network acl rule add sandbox-egress egress action=reject \
  destination=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,100.64.0.0/10,0.0.0.0/8,127.0.0.0/8,224.0.0.0/4,240.0.0.0/4

incus network create sandboxbr0 ipv4.nat=true ipv6.address=none \
  security.acls=sandbox-egress \
  security.acls.default.egress.action=allow \
  security.acls.default.ingress.action=allow

incus profile create sandbox
incus profile device add sandbox eth0 nic network=sandboxbr0 name=eth0
incus profile device add sandbox root disk pool=default path=/
```

## 2. Configure

```bash
cp .env.example .env
```

| Variable | Default | |
|---|---|---|
| `BACKEND_PORT` | `8001` | The backend's port, on 127.0.0.1 only |
| `DATA_DIR` | `data` | Everything Seraph keeps |
| `SERAPH_REPO` | | This repo on GitHub (owner/name), for updates and Fix all. `deploy/install.sh` sets it. |

The tokens aren't in `.env`: add them in Seraph, under Settings → Secrets (step 4).

## 3. Run

```bash
./run.sh      # http://localhost:5173, reloads as you edit, Ctrl+C stops
```

## 4. First steps

1. **Settings → Secrets.** Add your GitHub tokens (more tokens, ideally from different accounts, make searches faster), the Claude Code token, and a second Claude Code token for Fix all.
2. **VMs → Images → New image → Save and build**, then **Make default**.
3. **VMs → New VM.**
4. **GitHub → Account → Sign in with GitHub.** The page walks you through registering an OAuth App once. Until you sign in, Approve works but nothing is sent.
5. **Explore → Profile**, then **Start**. Approve the repos you like.
6. **Issues → Assign.** Then watch the agent on the VM page or in its chat.
