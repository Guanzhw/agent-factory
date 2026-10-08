"""Explicit owned browser fixture launcher; no production import/endpoint.

Writes safe metadata only. Generated credentials remain in temporary private
server configuration files, which are removed after the owned pair stops.
"""
import json
import os
from pathlib import Path
import time

from test_governed_remote_process_postgres import OwnedRemotePair
from controlled_remote_worker import MANAGER, ORIGIN_OWNER, RECEIVER_OWNER, REVIEWER


def main():
    metadata = Path(os.environ["FACTORY_REMOTE_BROWSER_METADATA"]).resolve()
    stop = metadata.with_suffix(".stop")
    if stop.exists():
        raise ValueError("Use a fresh owned fixture metadata/stop path")
    pair = OwnedRemotePair(os.environ["FACTORY_TEST_DATABASE_URL"]).start()
    try:
        values = {"fixtureOnly": True, "providerEvidence": "controlled-no-network", "demo": False,
            "originUrl": pair.origin.url, "receiverUrl": pair.receiver.url,
            "sourceOwner": ORIGIN_OWNER, "receiverOwner": RECEIVER_OWNER, "manager": MANAGER, "reviewer": REVIEWER,
            "sourceConfigurationPath": str(pair.origin.path), "receiverConfigurationPath": str(pair.receiver.path),
            "sessionPath": "/__fixture/session", "sessionAuthenticationHeader": "X-Fixture-Control",
            "sessionBody": {"actor": "one of the generated subjects above"},
            "originPid": pair.origin.process.pid, "receiverPid": pair.receiver.process.pid,
            "stopPath": str(stop)}
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(json.dumps(values, indent=2), encoding="utf-8")
        print("Controlled browser fixture ready: " + str(metadata), flush=True)
        while not stop.exists():
            time.sleep(.2)
    finally:
        pair.close()
        print("Owned browser fixture stopped and generated databases removed.", flush=True)


if __name__ == "__main__":
    main()
