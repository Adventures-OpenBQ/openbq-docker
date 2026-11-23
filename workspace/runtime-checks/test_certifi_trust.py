"""Run inside the Workspace image: verify the trust-store repair itself."""
import ssl
import unittest

import certifi


class WorkspaceTrustStore(unittest.TestCase):
    def context(self):
        return ssl.create_default_context(cafile=certifi.where())

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
