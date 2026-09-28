import unittest

from app.remnawave import parse_nodes


class RemnawavePayloadTests(unittest.TestCase):
    def test_nested_v3_payload_is_supported(self):
        nodes = parse_nodes(
            {
                "response": {
                    "data": {
                        "nodes": [
                            {
                                "uuid": "node-1",
                                "name": "RU 1",
                                "address": " 192.0.2.1 ",
                            }
                        ]
                    }
                }
            }
        )
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].address, "192.0.2.1")

    def test_disabled_nodes_and_invalid_rows_are_skipped(self):
        nodes = parse_nodes(
            [
                {"uuid": "disabled", "address": "192.0.2.1", "isDisabled": True},
                {"uuid": "missing-address"},
                {"id": "enabled", "host": "192.0.2.2", "remark": "RU 2"},
            ]
        )
        self.assertEqual([node.uuid for node in nodes], ["enabled"])

    def test_duplicate_uuid_uses_latest_panel_record(self):
        nodes = parse_nodes(
            [
                {"uuid": "node-1", "address": "192.0.2.1"},
                {"uuid": "node-1", "address": "192.0.2.2"},
            ]
        )
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].address, "192.0.2.2")

    def test_reality_sni_and_port_are_extracted_without_private_material(self):
        nodes = parse_nodes([
            {
                "uuid": "node-1",
                "address": "192.0.2.1",
                "configProfile": {
                    "activeInbounds": [{
                        "rawInbound": {
                            "port": 8443,
                            "streamSettings": {
                                "realitySettings": {
                                    "serverNames": ["example.com", "www.example.com"],
                                    "privateKey": "must-not-be-copied",
                                }
                            },
                        }
                    }]
                },
            }
        ])
        self.assertEqual(nodes[0].port, 8443)
        self.assertEqual(nodes[0].server_names, ("example.com", "www.example.com"))
        self.assertNotIn("must-not-be-copied", repr(nodes[0]))
