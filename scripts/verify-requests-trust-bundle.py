# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""API image gate for certifi's emSign distrust (GHSA-6q48-6c7w-9gw2)."""

import hashlib
import ssl
from pathlib import Path

import certifi
from requests import Session
from requests.adapters import DEFAULT_CA_BUNDLE_PATH


# eMudhra incident, Mozilla bugs 2083449 and 2083709. Certifi restored
# the unaffected emSign G1 root in 2026.10.19, so check exact CA fingerprints.
DISTRUSTED_ROOTS = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b": "emSign ECC Root CA - G3",
    "125609aa301da0a249b97a8239cb6a34216f44dcac9f3954b14292f2e8c8608f": "emSign Root CA - C1",
    "bc4d809b15189d78db3e1d8cf4f9726a795da1643ca5f1358e1ddb0edc0d7eb3": "emSign ECC Root CA - C3",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4": "AAA Certificate Services",
}


def test_requests_rejects_compromised_emsign_roots():
    url = "https://eodhd.com/"
    with Session() as session:
        verify = session.merge_environment_settings(url, {}, None, None, None)["verify"]
    assert verify, "Requests certificate verification must be enabled"
    bundle = Path(DEFAULT_CA_BUNDLE_PATH if verify is True else verify)
    assert bundle.is_file(), bundle
    context = ssl.create_default_context(cafile=str(bundle))
    fingerprints = {hashlib.sha256(cert).hexdigest() for cert in context.get_ca_certs(binary_form=True)}
    assert fingerprints
    compromised = sorted(DISTRUSTED_ROOTS[digest] for digest in fingerprints & DISTRUSTED_ROOTS.keys())
    assert not compromised, f"{bundle} trusts removed roots: {compromised}"
    assert bundle.resolve() == Path(certifi.where()).resolve()
    print(f"Requests CA bundle: {bundle} certifi={certifi.__version__} "
          f"sha256={hashlib.sha256(bundle.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    test_requests_rejects_compromised_emsign_roots()
