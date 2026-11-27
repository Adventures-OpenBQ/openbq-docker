"""Run inside the Workspace image: verify the trust-store repair itself."""
import hashlib
import ssl
import unittest

import certifi

DISTRUSTED_ROOTS = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
    "125609aa301da0a249b97a8239cb6a34216f44dcac9f3954b14292f2e8c8608f",
    "bc4d809b15189d78db3e1d8cf4f9726a795da1643ca5f1358e1ddb0edc0d7eb3",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
}


class WorkspaceTrustStore(unittest.TestCase):
    def context(self):
        return ssl.create_default_context(cafile=certifi.where())

    def test_all_reviewed_distrusted_root_fingerprints_are_absent(self):
        fingerprints = {
            hashlib.sha256(cert).hexdigest()
            for cert in self.context().get_ca_certs(binary_form=True)
        }
        self.assertTrue(fingerprints, "The HTTPS trust store must remain populated")
        self.assertFalse(fingerprints & DISTRUSTED_ROOTS,
                         "The HTTPS trust store retains a reviewed distrusted root")

    def test_compromised_emsign_g3_root_is_not_trusted(self):
        names = {
            value
            for certificate in self.context().get_ca_certs()
            for group in certificate['subject']
            for key, value in group
            if key == 'commonName'
        }
        self.assertFalse(
            'emSign ECC Root CA - G3' in names,
            'The compromised emSign G3 chain is still trusted.',
        )

    def test_valid_public_roots_remain_available(self):
        certificates = self.context().get_ca_certs()
        self.assertGreater(len(certificates), 100)
        self.assertTrue(any(
            key == 'commonName' and value == 'DigiCert Global Root G2'
            for certificate in certificates
            for group in certificate['subject']
            for key, value in group
        ))

    def test_certificate_and_hostname_verification_remain_enabled(self):
        context = self.context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)


if __name__ == '__main__':
    unittest.main()
