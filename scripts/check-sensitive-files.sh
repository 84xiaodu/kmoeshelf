#!/usr/bin/env bash
set -euo pipefail

failed=0
while IFS= read -r path; do
  case "$path" in
    .env|*/.env|*.db|*.sqlite|*.sqlite3|*.epub|*.mobi|*.part|data/*|downloads/*)
      echo "Refusing tracked runtime or credential file: $path" >&2
      failed=1
      ;;
  esac
done < <(git ls-files)

if git grep -nE -- 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY' -- .; then
  echo "Private key material found in tracked files" >&2
  failed=1
fi

exit "$failed"
