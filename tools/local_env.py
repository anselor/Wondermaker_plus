"""Small dependency-free loader for the repository's ignored .env file."""
import os
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def load_local_env(path=REPO / '.env'):
    """Load simple KEY=VALUE entries without overriding the process environment."""
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        if '=' not in line:
            raise RuntimeError('%s:%d: expected KEY=VALUE' % (path, number))
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if not key or not key.replace('_', '').isalnum() or key[0].isdigit():
            raise RuntimeError('%s:%d: invalid environment name' % (path, number))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def require(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            '%s is required; copy .env.example to .env and configure it' % name)
    return value


def configure_ssh_client(client):
    """Load known hosts; permit trust-on-first-use only by explicit opt-in."""
    client.load_system_host_keys()
    known_hosts = os.environ.get('WMP_SSH_KNOWN_HOSTS')
    if known_hosts:
        client.load_host_keys(os.path.expanduser(known_hosts))
    if os.environ.get('WMP_SSH_AUTO_ADD', '').lower() in ('1', 'true', 'yes'):
        import paramiko
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())


load_local_env()
