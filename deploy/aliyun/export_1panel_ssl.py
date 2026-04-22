import argparse
import os
import sqlite3
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a 1Panel website SSL record to PEM files.")
    parser.add_argument("--db", default="/opt/1panel/db/1Panel.db", help="Path to the 1Panel sqlite database")
    parser.add_argument("--domain", required=True, help="website_ssls.primary_domain value to export")
    parser.add_argument("--out-dir", required=True, help="Output directory for privkey.pem and fullchain.pem")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT private_key, pem
        FROM website_ssls
        WHERE primary_domain = ? AND status = 'ready'
        ORDER BY id DESC
        LIMIT 1
        """,
        (args.domain,),
    ).fetchone()
    conn.close()

    if row is None:
        raise SystemExit(f"ready certificate not found for {args.domain}")

    private_key, pem = row
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    privkey_path = out_dir / "privkey.pem"
    fullchain_path = out_dir / "fullchain.pem"
    privkey_path.write_text(private_key, encoding="utf-8")
    fullchain_path.write_text(pem, encoding="utf-8")
    os.chmod(privkey_path, 0o600)
    os.chmod(fullchain_path, 0o644)

    print(str(out_dir))
    print(str(privkey_path.stat().st_size))
    print(str(fullchain_path.stat().st_size))


if __name__ == "__main__":
    main()
