"""
On-demand full data dump for ML engineers.

Authenticates, triggers a FullDataDumpWorkflow via the admin API,
polls until complete, then downloads all output files.

Usage:
    python -m scripts.full_dump --api https://koala.science/api/v1 \
        --email alice.chen@stanford.edu --password password123 --out ./my-dump
"""
import argparse
import asyncio
from pathlib import Path

import httpx


async def main():
    parser = argparse.ArgumentParser(description="Trigger and download a full data dump")
    parser.add_argument("--api", type=str, default="https://koala.science/api/v1", help="API base URL")
    parser.add_argument("--email", type=str, required=True, help="Login email")
    parser.add_argument("--password", type=str, required=True, help="Login password")
    parser.add_argument("--out", type=str, default="./dump", help="Local output directory")
    parser.add_argument("--poll-interval", type=int, default=5, help="Seconds between status checks")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Authenticate
        print(f"Logging in as {args.email}...")
        resp = await client.post(f"{args.api}/auth/login", json={
            "email": args.email,
            "password": args.password,
        })
        if resp.status_code != 200:
            print(f"Login failed: {resp.status_code} {resp.text}")
            return
        token = resp.json().get("access_token")
        if not token:
            print("No access_token in response")
            return
        headers = {"Authorization": f"Bearer {token}"}
        print("Authenticated ✓\n")

        # 2. Trigger the dump
        print("Triggering full data dump...")
        resp = await client.post(f"{args.api}/export/full-dump", headers=headers)
        if resp.status_code != 202:
            print(f"Failed to trigger dump: {resp.status_code} {resp.text}")
            return

        workflow_id = resp.json()["workflow_id"]
        print(f"Workflow started: {workflow_id}")

        # 3. Poll until complete
        print("Waiting for dump to complete", end="", flush=True)
        while True:
            await asyncio.sleep(args.poll_interval)
            print(".", end="", flush=True)

            resp = await client.get(
                f"{args.api}/export/full-dump/{workflow_id}",
                headers=headers,
            )
            status = resp.json()

            if status["status"] == "completed":
                print(" done!\n")
                files = status["files"]
                counts = status.get("counts", {})
                break
            elif status["status"] == "failed":
                print(f"\nDump failed: {status.get('error', 'unknown')}")
                return

        # 4. Download all files
        base_url = args.api.replace("/api/v1", "")
        print(f"Downloading {len(files)} files to {out}/")
        for file_info in files:
            name = file_info["name"]
            url = file_info["url"]
            print(f"  {name}...", end=" ", flush=True)

            resp = await client.get(f"{base_url}{url}", headers=headers)
            if resp.status_code == 200:
                (out / name).write_bytes(resp.content)
                size_kb = len(resp.content) / 1024
                print(f"✓ ({size_kb:.1f} KB)")
            else:
                print(f"✗ ({resp.status_code})")

    # Summary
    print(f"\n=== Dump Complete ===")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    total_size = sum(f.stat().st_size for f in out.iterdir() if f.is_file())
    print(f"  Total size: {total_size / 1024:.1f} KB")
    print(f"  Location: {out}/")


if __name__ == "__main__":
    asyncio.run(main())
