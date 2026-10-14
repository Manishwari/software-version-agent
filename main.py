
import csv
import json
import os
import re
import time
from urllib.parse import urlparse

import anthropic
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    raise RuntimeError("ANTHROPIC_API_KEY is missing from .env")

client = anthropic.Anthropic(api_key=api_key)

CSV_FILE = "requiredsoftwares.csv"
MODEL = "claude-sonnet-4-6"

# Official domains for the software in this exercise.
OFFICIAL_DOMAINS = {
    "python": ["python.org"],
    "git": ["git-scm.com"],
    "visual studio code": ["code.visualstudio.com"],
    "node.js": ["nodejs.org"],
    "java": ["java.com", "oracle.com", "jdk.java.net"],
    "postgresql": ["postgresql.org"],
    "docker desktop": ["docker.com"],
}


def valid_official_url(name, url):
    """Accept HTTPS URLs on an approved official domain."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()

        if parsed.scheme != "https" or not host:
            return False

        domains = OFFICIAL_DOMAINS.get(name.lower(), [])

        return any(
            host == domain or host.endswith("." + domain)
            for domain in domains
        )
    except ValueError:
        return False


def get_latest_version(name, attempts=3):
    prompt = f"""
Find the latest stable release of: {name}

Use web search and prioritize official release pages.
Do not invent a version. Do not use beta or preview releases.

Return one JSON object and no other text:
{{
  "version": "verified version string",
  "url": "official HTTPS release page URL"
}}

If you cannot verify the version, return empty strings.
"""

    for attempt in range(attempts):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=500,
                tools=[
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 3,
                    }
                ],
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )

            text_parts = [
                block.text
                for block in response.content
                if block.type == "text"
            ]
            text = "\n".join(text_parts)

            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                print("Invalid response format.")
                return None

            data = json.loads(match.group())
            version = data.get("version")
            url = data.get("url")

            if not isinstance(version, str) or not isinstance(url, str):
                print("Version or URL has the wrong data type.")
                return None

            version = version.strip()
            url = url.strip()

            if not version or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,49}",
                version,
            ):
                print("Missing or invalid version.")
                return None

            if not valid_official_url(name, url):
                print("URL is not on the approved official domain.")
                return None

            return {"version": version, "url": url}

        except anthropic.RateLimitError:
            if attempt == attempts - 1:
                print("Rate limit reached; skipping this software.")
                return None

            delay = 2 ** (attempt + 1)
            print(f"Rate limited. Retrying in {delay} seconds.")
            time.sleep(delay)

        except (anthropic.APIConnectionError, anthropic.APIStatusError) as error:
            if attempt == attempts - 1:
                print(f"API request failed: {error}")
                return None

            delay = 2 ** (attempt + 1)
            print(f"Temporary API error. Retrying in {delay} seconds.")
            time.sleep(delay)

        except (json.JSONDecodeError, TypeError, ValueError) as error:
            print(f"Could not parse response: {error}")
            return None

    return None


def main():
    with open(CSV_FILE, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        columns = reader.fieldnames
        rows = list(reader)

    required = {"sno", "name", "version", "url"}

    if not columns or not required.issubset(columns):
        raise ValueError(
            "CSV must contain sno, name, version, and url columns."
        )

    for row in rows:
        name = row["name"].strip()

        if not name:
            continue

        print(f"\nChecking: {name}")
        result = get_latest_version(name)

        if result is None:
            print("Lookup failed. Existing CSV values preserved.")
            continue

        # Update only after all validation checks pass.
        row["version"] = result["version"]
        row["url"] = result["url"]

        print("Version:", row["version"])
        print("URL:", row["url"])

    # Write to a temporary file first to reduce the risk of
    # losing the original CSV if writing fails.
    temp_file = CSV_FILE + ".tmp"

    with open(temp_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    os.replace(temp_file, CSV_FILE)
    print("\nCSV update completed.")


if __name__ == "__main__":
    main()
