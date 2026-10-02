#!/usr/bin/env python3
"""Initialize private local settings, then deploy the real search product."""

import argparse
import os
import secrets
import subprocess
from pathlib import Path


def initialize(deploy_dir):
    path = deploy_dir / ".env"
    if not path.exists():
        values = {
            "LITELLM_MASTER_KEY": "sk-bs-master-" + secrets.token_urlsafe(32),
            "BENSZ_SEARCH_SECRET": secrets.token_urlsafe(48),
            "BENSZ_SEARCH_ADMIN_USERNAME": "admin",
            "BENSZ_SEARCH_ADMIN_PASSWORD": secrets.token_urlsafe(18),
            "BENSZ_SEARCH_COOKIE_SECURE": "false",
            "BENSZ_SEARCH_PORT": "8898",
            "SEARXNG_API_BASE": os.getenv("SEARXNG_API_BASE", "http://host.docker.internal:8080"),
            "SEARXNG_ENGINES": os.getenv("SEARXNG_ENGINES", "github,pubmed"),
        }
        # O_EXCL prevents concurrent initializers overwriting secrets.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write("# Private local credentials. Keep this file and the data volume together.\n")
            handle.write("\n".join(key + "=" + value for key, value in values.items()) + "\n")
        print("已初始化 docs/deploy/.env，管理员初始密码与加密密钥保存在该文件。")
    else:
        print("沿用已有 docs/deploy/.env，不覆盖凭据。")
    values = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    if len(values.get("LITELLM_MASTER_KEY", "")) < 32 or len(values.get("BENSZ_SEARCH_SECRET", "")) < 32:
        raise SystemExit(".env 缺少足够强度的 master key 或加密密钥，请补齐后部署。")
    if len(values.get("BENSZ_SEARCH_ADMIN_PASSWORD", "")) < 12:
        raise SystemExit(".env 的管理员初始密码至少需要 12 个字符。")
    path.chmod(0o600)
    private = deploy_dir / ".secrets"
    private.mkdir(mode=0o700, exist_ok=True)
    initial_login = private / "local-admin.txt"
    if not initial_login.exists():
        initial_login.write_text(
            "后台：http://127.0.0.1:" + values.get("BENSZ_SEARCH_PORT", "8898") + "/admin\n"
            "初始用户名：" + values.get("BENSZ_SEARCH_ADMIN_USERNAME", "admin") + "\n"
            "初始密码：" + values["BENSZ_SEARCH_ADMIN_PASSWORD"] + "\n\n"
            "登录后可在个人设置修改密码；修改后初始密码不再有效。\n"
        )
        initial_login.chmod(0o600)
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    values = initialize(root / "docs/deploy")
    if not args.init_only:
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "docs/deploy/compose.yaml",
                "up",
                "-d",
                "--build",
                "--remove-orphans",
                "--wait",
            ],
            cwd=root,
            check=True,
        )
        print("后台：http://127.0.0.1:" + values.get("BENSZ_SEARCH_PORT", "8898") + "/admin")
        print("初始账户见 docs/deploy/.env 的 BENSZ_SEARCH_ADMIN_USERNAME / BENSZ_SEARCH_ADMIN_PASSWORD。")


if __name__ == "__main__":
    main()
