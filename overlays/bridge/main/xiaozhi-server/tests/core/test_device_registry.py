import copy
from pathlib import Path
import tempfile
import unittest
from core.utils import device_registry as registry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'devices.yaml'
        old_agents = dict(registry.DEVICE_AGENTS)
        old_labels = dict(registry.DEVICE_LABELS)
        old_dance = registry.DANCE_DEVICE
        def restore():
            registry.DEVICE_AGENTS.clear(); registry.DEVICE_AGENTS.update(old_agents)
            registry.DEVICE_LABELS.clear(); registry.DEVICE_LABELS.update(old_labels)
            registry.DANCE_DEVICE = old_dance
        self.addCleanup(restore)

    def configure(self, routes):
        import json
        self.path.write_text(json.dumps({'devices': routes}))
        registry.configure_devices(self.path)

    def route(self, **kwargs):
        return {'agent_id': 'custom-agent', 'firmware_label': 'Operator', **kwargs}

    def test_custom_id_with_explicit_push_and_motion(self):
        self.configure({'02:00:00:00:00:03': self.route(push_enabled=True, dance_enabled=True)})
        self.assertEqual(registry.DEVICE_AGENTS, {'02:00:00:00:00:03': 'custom-agent'})
        self.assertEqual(registry.DEVICE_LABELS['02:00:00:00:00:03'], 'Operator')
        self.assertEqual(registry.DANCE_DEVICE, '02:00:00:00:00:03')

    def test_unenabled_routes_cannot_receive_events(self):
        self.configure({'02:00:00:00:00:01': self.route()})
        self.assertEqual(registry.DEVICE_AGENTS, {})
        self.assertIsNone(registry.DANCE_DEVICE)

    def test_string_boolean_is_rejected(self):
        with self.assertRaises(ValueError):
            self.configure({'02:00:00:00:00:01': self.route(push_enabled='false')})

    def test_invalid_agent_is_rejected(self):
        with self.assertRaises(ValueError):
            self.configure({'02:00:00:00:00:01': self.route(agent_id='operator:openai-user')})

    def test_invalid_mac_is_rejected(self):
        with self.assertRaises(ValueError):
            self.configure({'not-a-device': self.route()})

    def test_motion_cannot_silently_select_last_device(self):
        with self.assertRaises(ValueError):
            self.configure({
                '02:00:00:00:00:01': self.route(dance_enabled=True),
                '02:00:00:00:00:03': self.route(dance_enabled=True),
            })

    def test_invalid_reload_preserves_previous_valid_enrollment(self):
        self.configure({'02:00:00:00:00:01': self.route(push_enabled=True)})
        before = copy.deepcopy(registry.DEVICE_AGENTS)
        with self.assertRaises(ValueError):
            self.configure({'02:00:00:00:00:03': self.route(push_enabled=True, firmware_label='')})
        self.assertEqual(registry.DEVICE_AGENTS, before)

    def test_reload_removes_prior_devices_and_preserves_imported_dict(self):
        imported = registry.DEVICE_AGENTS
        self.configure({'02:00:00:00:00:01': self.route(push_enabled=True)})
        self.configure({})
        self.assertIs(imported, registry.DEVICE_AGENTS)
        self.assertEqual(imported, {})


if __name__ == '__main__':
    unittest.main()
