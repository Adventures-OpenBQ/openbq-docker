"""Exercise the actual HTTPX HTTPS trust store, not only dependency metadata."""
import hashlib

import httpx

# GHSA-6q48-6c7w-9gw2; exact distrust fingerprints from the existing
# Adventures-OpenBQ/openbq-docker PR33 trust-bundle repair.
DISTRUSTED = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
    "125609aa301da0a249b97a8239cb6a34216f44dcac9f3954b14292f2e8c8608f",
    "bc4d809b15189d78db3e1d8cf4f9726a795da1643ca5f1358e1ddb0edc0d7eb3",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
}


def test_httpx_default_https_trust_rejects_distrusted_roots():
    context = httpx.create_ssl_context(trust_env=False)
    fingerprints = {
        hashlib.sha256(cert).hexdigest()
        for cert in context.get_ca_certs(binary_form=True)
    }
    assert fingerprints, "The default HTTPS trust store must be populated"
    assert not fingerprints & DISTRUSTED, "HTTPX still trusts a distrusted root CA"
