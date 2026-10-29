"""Run SonarCloud's Python rules locally, before a commit reaches CI.

SonarCloud only analyses the project in CI, so a rule it enforces shows up after the push. This script runs the same
analyser against a throwaway SonarQube server in Docker: it starts the server (kept running between runs), copies the
active rules of the project's SonarCloud quality profile into a local profile, scans the working tree, and prints
every open issue. It exits 1 when there are any, so it can gate a commit.

Nothing is sent to SonarCloud and no token is needed; the only call out is a public read of the quality profile.
Rules SonarQube Community does not ship (the ``pythonsecurity`` taint rules) cannot run locally and are reported
as skipped.

Usage: ``poe sonar`` to scan, ``poe sonar --stop`` to remove the server and its data.
"""

import argparse
import base64
import hashlib
import io
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Everything tracks the latest stable release: the images are pulled and the scanner is checked on every run.
SERVER_IMAGE = "sonarqube:community"
# The official scanner images are amd64 only, so run the platform-independent scanner jar on a multi-arch JDK.
SCANNER_IMAGE = "eclipse-temurin:latest"
SCANNER_METADATA = "https://repo1.maven.org/maven2/org/sonarsource/scanner/cli/sonar-scanner-cli/maven-metadata.xml"
SCANNER_DOWNLOADS = "https://binaries.sonarsource.com/Distribution/sonar-scanner-cli"
SCANNER_JARS = Path.home() / ".cache" / "calque-sonar"
SCANNER_CACHE = "calque-sonar-scanner-cache"
CONTAINER = "calque-sonarqube"
VOLUME = "calque-sonarqube-data"
NETWORK = "calque-sonar"
PORT = 9000
LOCAL_URL = f"http://localhost:{PORT}"

# A local-only server bound to 127.0.0.1; the password only has to satisfy SonarQube's complexity rules.
ADMIN = ("admin", "Calque-local-sonar-1")
PROJECT = "calque"
PROFILE = "SonarCloud mirror"

CLOUD_URL = "https://sonarcloud.io"
CLOUD_ORGANIZATION = "agilezebra"
CLOUD_PROJECT = "agilezebra_calque"

STARTUP_TIMEOUT = 300
PAGE_SIZE = 500

type Json = dict[str, Any]


def docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a docker command and return its result."""
    return subprocess.run(["docker", *arguments], check=check, capture_output=True, text=True)


def request(url: str, data: dict[str, str] | None = None, auth: tuple[str, str] | None = ADMIN) -> Json:
    """Call a SonarQube Web API endpoint; a GET when ``data`` is None, otherwise a form POST."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    headers = {}
    if auth is not None:
        headers["Authorization"] = "Basic " + base64.b64encode(":".join(auth).encode()).decode()
    with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=60) as response:
        text = response.read().decode()
    return json.loads(text) if text else {}


def local(path: str, data: dict[str, str] | None = None, auth: tuple[str, str] | None = ADMIN) -> Json:
    """Call the local server's Web API."""
    return request(f"{LOCAL_URL}/api/{path}", data, auth)


def paged(url: str, key: str, auth: tuple[str, str] | None = ADMIN) -> list[Json]:
    """Collect every page of a paginated search."""
    items: list[Json] = []
    page = 1
    while True:
        result = request(f"{url}&ps={PAGE_SIZE}&p={page}", auth=auth)
        items.extend(result[key])
        total = result.get("paging", result).get("total", 0)
        if page * PAGE_SIZE >= total:
            return items
        page += 1


def pull(image: str) -> None:
    """Pull the newest build of an image, carrying on with the local copy when that fails (offline, say)."""
    if docker("pull", "--quiet", image, check=False).returncode != 0:
        print(f"warning: could not pull {image}; using the local copy.")


def start_server() -> None:
    """Start the SonarQube container, creating it on first use or after a new release, and wait until it is up."""
    docker("network", "create", NETWORK, check=False)
    pull(SERVER_IMAGE)
    latest = docker("image", "inspect", "--format", "{{.Id}}", SERVER_IMAGE, check=False).stdout.strip()
    running = docker("container", "inspect", "--format", "{{.Image}}", CONTAINER, check=False)
    if running.returncode == 0 and running.stdout.strip() != latest:
        # The embedded database does not support upgrades, so start afresh; the next steps rebuild everything.
        print("A new SonarQube release is out; recreating the local server...")
        docker("rm", "--force", CONTAINER)
        docker("volume", "rm", VOLUME, check=False)
    if docker("container", "inspect", CONTAINER, check=False).returncode != 0:
        print(f"Creating {CONTAINER} (the first start takes a minute or two)...")
        docker(
            "run", "--detach", "--name", CONTAINER, "--network", NETWORK,
            "--publish", f"127.0.0.1:{PORT}:9000",
            "--env", "SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true",
            "--volume", f"{VOLUME}:/opt/sonarqube/data",
            SERVER_IMAGE,
        )  # fmt: skip
    else:
        docker("start", CONTAINER)
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        try:
            if local("system/status", auth=None).get("status") == "UP":
                return
        except (urllib.error.URLError, ConnectionError, json.JSONDecodeError):
            pass
        time.sleep(2)
    sys.exit(f"SonarQube did not come up within {STARTUP_TIMEOUT}s; see `docker logs {CONTAINER}`.")


def stop_server() -> None:
    """Remove the container, its data and its network."""
    docker("rm", "--force", CONTAINER, check=False)
    docker("volume", "rm", VOLUME, SCANNER_CACHE, check=False)
    docker("network", "rm", NETWORK, check=False)
    print(f"Removed {CONTAINER} and its data.")


def prepare_server() -> None:
    """Replace the default admin password on a fresh server and create the project."""
    if not local("authentication/validate")["valid"]:
        local(
            "users/change_password",
            {"login": ADMIN[0], "previousPassword": "admin", "password": ADMIN[1]},
            auth=(ADMIN[0], "admin"),
        )
    if not local(f"projects/search?projects={PROJECT}")["components"]:
        local("projects/create", {"project": PROJECT, "name": PROJECT})


def cloud_rules() -> dict[str, str]:
    """Return SonarCloud's active Python rules for the project, mapped to their parameters as ``k=v;k=v``."""
    profiles = request(
        f"{CLOUD_URL}/api/qualityprofiles/search?project={CLOUD_PROJECT}&organization={CLOUD_ORGANIZATION}",
        auth=None,
    )["profiles"]
    profile = next(profile["key"] for profile in profiles if profile["language"] == "py")
    rules: dict[str, str] = {}
    page = 1
    while True:
        result = request(
            f"{CLOUD_URL}/api/rules/search?organization={CLOUD_ORGANIZATION}&qprofile={profile}"
            f"&activation=true&f=actives&ps={PAGE_SIZE}&p={page}",
            auth=None,
        )
        for rule in result["rules"]:
            parameters = result["actives"][rule["key"]][0]["params"]
            rules[rule["key"]] = ";".join(f"{parameter['key']}={parameter['value']}" for parameter in parameters)
        if page * PAGE_SIZE >= result["total"]:
            return rules
        page += 1


def sync_profile() -> None:
    """Make the local profile activate exactly the rules SonarCloud does, with the same parameters."""
    profiles = local(f"qualityprofiles/search?language=py&qualityProfile={urllib.parse.quote(PROFILE)}")["profiles"]
    if profiles:
        profile = profiles[0]["key"]
    else:
        profile = local("qualityprofiles/create", {"language": "py", "name": PROFILE})["profile"]["key"]
    local("qualityprofiles/add_project", {"project": PROJECT, "qualityProfile": PROFILE, "language": "py"})
    try:
        wanted = cloud_rules()
    except (urllib.error.URLError, KeyError, StopIteration) as error:
        print(f"warning: could not read SonarCloud's quality profile ({error}); using the last copy.")
        return
    available = {rule["key"] for rule in paged(f"{LOCAL_URL}/api/rules/search?languages=py", "rules")}
    active = {
        rule["key"] for rule in paged(f"{LOCAL_URL}/api/rules/search?qprofile={profile}&activation=true", "rules")
    }
    for rule in sorted(active - wanted.keys()):
        local("qualityprofiles/deactivate_rule", {"key": profile, "rule": rule})
    for rule in sorted((wanted.keys() & available) - active):
        local("qualityprofiles/activate_rule", {"key": profile, "rule": rule, "params": wanted[rule]})
    skipped = sorted({rule.split(":")[0] for rule in wanted.keys() - available})
    if skipped:
        count = len(wanted.keys() - available)
        print(f"Skipped {count} SonarCloud rules that SonarQube Community does not ship ({', '.join(skipped)}).")


def download(url: str) -> bytes:
    """Fetch a URL's body."""
    with urllib.request.urlopen(url, timeout=120) as response:
        return bytes(response.read())


def scanner() -> Path:
    """Return the latest released scanner jar, downloading and verifying it when a new one is out."""
    try:
        release = re.search(r"<release>([^<]+)</release>", download(SCANNER_METADATA).decode())
    except urllib.error.URLError:
        release = None
    if release is None:
        cached = sorted(SCANNER_JARS.glob("sonar-scanner-cli-*.jar"), key=lambda jar: jar.stat().st_mtime)
        if not cached:
            sys.exit(f"Could not find the latest sonar-scanner release at {SCANNER_METADATA}.")
        print(f"warning: could not check for a new sonar-scanner release; using {cached[-1].name}.")
        return cached[-1]
    version = release[1]
    jar = SCANNER_JARS / f"sonar-scanner-cli-{version}.jar"
    if not jar.exists():
        print(f"Downloading sonar-scanner {version}...")
        url = f"{SCANNER_DOWNLOADS}/sonar-scanner-cli-{version}.zip"
        archive = download(url)
        if hashlib.sha256(archive).hexdigest() != download(f"{url}.sha256").decode().split()[0]:
            sys.exit(f"The download from {url} does not match its published checksum.")
        SCANNER_JARS.mkdir(parents=True, exist_ok=True)
        for old in SCANNER_JARS.glob("sonar-scanner-cli-*.jar"):
            old.unlink()
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            jar.write_bytes(bundle.read(f"sonar-scanner-{version}/lib/{jar.name}"))
    return jar


def scan() -> None:
    """Scan the working tree with a short-lived token and wait for the server to process the report."""
    local("user_tokens/revoke", {"name": PROJECT})
    token = local("user_tokens/generate", {"name": PROJECT, "type": "PROJECT_ANALYSIS_TOKEN", "projectKey": PROJECT})
    pull(SCANNER_IMAGE)
    result = docker(
        "run", "--rm", "--network", NETWORK,
        "--volume", f"{ROOT}:/usr/src",
        "--volume", f"{scanner()}:/opt/sonar-scanner.jar:ro",
        "--volume", f"{SCANNER_CACHE}:/opt/sonar-cache",
        "--workdir", "/usr/src",
        "--env", f"SONAR_HOST_URL=http://{CONTAINER}:9000",
        "--env", f"SONAR_TOKEN={token['token']}",
        "--env", "SONAR_USER_HOME=/opt/sonar-cache",
        SCANNER_IMAGE,
        "java", "-jar", "/opt/sonar-scanner.jar",
        f"-Dsonar.projectKey={PROJECT}",
        "-Dsonar.organization=",
        "-Dsonar.scm.disabled=true",
        "-Dsonar.working.directory=/tmp/.scannerwork",
        check=False,
    )  # fmt: skip
    if result.returncode != 0:
        sys.exit(f"The scan failed:\n{result.stdout}{result.stderr}")
    task = next(line for line in result.stdout.splitlines() if "api/ce/task?id=" in line).split("id=")[-1]
    while (status := local(f"ce/task?id={task}")["task"]["status"]) in {"PENDING", "IN_PROGRESS"}:
        time.sleep(1)
    if status != "SUCCESS":
        sys.exit(f"SonarQube could not process the analysis ({status}); see {LOCAL_URL}/project/background_tasks")


def report() -> int:
    """Print the open issues and return how many there are."""
    issues = paged(f"{LOCAL_URL}/api/issues/search?components={PROJECT}&issueStatuses=OPEN,CONFIRMED", "issues")
    for issue in sorted(issues, key=lambda issue: (issue["component"], issue.get("line", 0))):
        path = issue["component"].removeprefix(f"{PROJECT}:")
        print(f"{path}:{issue.get('line', 1)}: {issue['rule']} {issue['message']}")
    print(f"{len(issues)} open Sonar issue(s). Browse them at {LOCAL_URL}/project/issues?id={PROJECT}")
    return len(issues)


def main() -> None:
    """Parse the command line and run the scan, or remove the server."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stop", action="store_true", help="remove the local SonarQube server and its data")
    if parser.parse_args().stop:
        stop_server()
        return
    start_server()
    prepare_server()
    sync_profile()
    scan()
    sys.exit(1 if report() else 0)


if __name__ == "__main__":
    main()
