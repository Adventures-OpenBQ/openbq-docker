# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Qualify RSS HTTPX HTTPS trust; adapted from openbq-docker PR33's Requests gate."""
import hashlib
import httpx
import certifi

DISTRUSTED_ROOTS = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
    "125609aa301da0a249b97a8239cb6a34216f44dcac9f3954b14292f2e8c8608f",
    "bc4d809b15189d78db3e1d8cf4f9726a795da1643ca5f1358e1ddb0edc0d7eb3",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
}

def verify_httpx_trust_bundle():
    context = httpx.create_ssl_context(trust_env=True)
    fingerprints = {hashlib.sha256(cert).hexdigest() for cert in context.get_ca_certs(binary_form=True)}
    assert context.check_hostname and context.verify_mode, "HTTPS verification must remain enabled"
    assert fingerprints and not fingerprints & DISTRUSTED_ROOTS, "HTTPX trusts distrusted roots"
    print(f"HTTPX trust verified: certifi={certifi.__version__}, roots={len(fingerprints)}, bundle_sha256={hashlib.sha256(open(certifi.where(), 'rb').read()).hexdigest()}")

if __name__ == "__main__":
    verify_httpx_trust_bundle()
